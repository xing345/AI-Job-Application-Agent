"""自动填写投递表单节点。

流程：进入申请页 → 字段发现（Playwright）→ LLM 语义映射+值生成
→ 执行填写+上传简历 → HITL 等待用户手动提交 → 记录结果。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import ElementHandle, Page
from pydantic import BaseModel

from src.agent.state import AgentState
from src.browser.hitl import default_handler as hitl
from src.browser.manager import get_browser
from src.browser.navigator import safe_click, wait_for_load
from src.models.job import JobDetail
from src.models.match import FillField, FillStatus

logger = logging.getLogger(__name__)

_DEFAULT_RESUME_PDF = str(Path(__file__).resolve().parent.parent.parent.parent / "data" / "resume.pdf")

# 申请按钮文本关键词
APPLY_BUTTON_TEXTS = ["立即投递", "申请职位", "投递简历", "立即申请", "投简历", "Apply", "apply now", "submit"]


# ============================================================
# 1. 进入申请页
# ============================================================

async def enter_application_page(page: Page, job: JobDetail) -> bool:
    """进入岗位申请页。

    优先用 job.apply_url，否则在详情页找申请按钮点击。
    """
    if job.apply_url and job.apply_url != job.posting.detail_url:
        try:
            await page.goto(job.apply_url, wait_until="domcontentloaded", timeout=30000)
            await wait_for_load(page)
            return True
        except Exception as e:
            logger.warning("goto apply_url failed: %s", e)

    # 在详情页找申请按钮
    for text in APPLY_BUTTON_TEXTS:
        try:
            btn = page.get_by_text(text, exact=False).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(2000)
                await wait_for_load(page)
                logger.info("Clicked apply button: %s", text)
                return True
        except Exception:
            continue

    # 尝试常见 selector
    for sel in [".apply-btn", ".btn-apply", "[class*='apply']", "button[type='submit']"]:
        if await safe_click(page, sel):
            await page.wait_for_timeout(2000)
            return True

    logger.warning("No apply button found, staying on current page")
    return True


# ============================================================
# 2. 表单字段发现
# ============================================================

async def discover_form_fields(page: Page) -> List[FillField]:
    """Playwright 元素级提取所有可填写字段。

    遍历 input/textarea/select，提取 label/placeholder/name/type/options。
    不调 LLM。
    """
    fields: list[FillField] = []

    # 处理 select
    try:
        selects = await page.query_selector_all("select:not([disabled]):not([type='hidden'])")
        for i, sel in enumerate(selects):
            field = await _extract_select_field(sel, i)
            if field:
                fields.append(field)
    except Exception as e:
        logger.warning("select extraction error: %s", e)

    # 处理 textarea
    try:
        textareas = await page.query_selector_all("textarea:not([disabled]):not([type='hidden'])")
        for i, ta in enumerate(textareas):
            field = await _extract_input_field(ta, f"textarea_{i}", "textarea")
            if field:
                fields.append(field)
    except Exception as e:
        logger.warning("textarea extraction error: %s", e)

    # 处理 input（text/email/number/date 等，跳过 button/submit/hidden）
    skip_types = {"button", "submit", "reset", "hidden", "image", "file"}
    try:
        inputs = await page.query_selector_all("input:not([disabled])")
        for i, inp in enumerate(inputs):
            itype = (await inp.get_attribute("type")) or "text"
            if itype.lower() in skip_types:
                continue
            if itype.lower() in ("radio", "checkbox"):
                # radio/checkbox 单独分组处理
                continue
            field = await _extract_input_field(inp, f"input_{i}", itype)
            if field:
                fields.append(field)
    except Exception as e:
        logger.warning("input extraction error: %s", e)

    # 处理 radio 分组（按 name 分组）
    try:
        radio_groups = await _extract_radio_groups(page)
        fields.extend(radio_groups)
    except Exception as e:
        logger.warning("radio extraction error: %s", e)

    # 处理 checkbox 分组
    try:
        checkbox_groups = await _extract_checkbox_groups(page)
        fields.extend(checkbox_groups)
    except Exception as e:
        logger.warning("checkbox extraction error: %s", e)

    # 文件上传字段
    try:
        file_inputs = await page.query_selector_all("input[type='file']")
        for i, fi in enumerate(file_inputs):
            label = await _get_element_label(page, fi)
            fields.append(FillField(
                label=label or "简历上传",
                name=(await fi.get_attribute("name")) or "",
                field_type="file",
                element_selector=f"input[type='file'] >> nth={i}",
            ))
    except Exception:
        pass

    logger.info("Discovered %d form fields", len(fields))
    return fields


async def _extract_input_field(element: ElementHandle, default_id: str, ftype: str) -> Optional[FillField]:
    """提取单个 input/textarea 字段信息。"""
    page = element.page
    name = (await element.get_attribute("name")) or ""
    placeholder = (await element.get_attribute("placeholder")) or ""
    elem_id = (await element.get_attribute("id")) or ""

    label = await _get_element_label(page, element, elem_id)

    # 构造 selector（优先用 name，其次 id）
    if name:
        selector = f"{element.evaluate('el => el.tagName.toLowerCase()')}[name='{name}']"
    elif elem_id:
        selector = f"#{elem_id}"
    else:
        selector = default_id

    return FillField(
        label=label,
        placeholder=placeholder,
        name=name,
        field_type=ftype,
        element_selector=selector,
    )


async def _extract_select_field(element: ElementHandle, index: int) -> Optional[FillField]:
    """提取 select 字段信息。"""
    page = element.page
    name = (await element.get_attribute("name")) or ""
    elem_id = (await element.get_attribute("id")) or ""
    label = await _get_element_label(page, element, elem_id)

    # 提取 options
    options: list[str] = []
    try:
        option_elems = await element.query_selector_all("option")
        for opt in option_elems:
            val = await opt.get_attribute("value")
            text = (await opt.inner_text()).strip()
            if val and val not in ("", "-1", "0") and text:
                options.append(text)
    except Exception:
        pass

    if name:
        selector = f"select[name='{name}']"
    elif elem_id:
        selector = f"#{elem_id}"
    else:
        selector = f"select >> nth={index}"

    return FillField(
        label=label,
        name=name,
        field_type="select",
        options=options,
        element_selector=selector,
    )


async def _extract_radio_groups(page: Page) -> List[FillField]:
    """按 name 分组提取 radio。"""
    groups: dict[str, dict] = {}
    radios = await page.query_selector_all("input[type='radio']:not([disabled])")

    for r in radios:
        name = (await r.get_attribute("name")) or ""
        if not name:
            continue
        value = (await r.get_attribute("value")) or ""
        # 找关联 label 文本
        label_text = await _get_element_label(page, r)

        if name not in groups:
            groups[name] = {"options": [], "label": label_text, "selector": f"input[type='radio'][name='{name}']"}
        if value and value not in groups[name]["options"]:
            groups[name]["options"].append(value)
        if not groups[name]["label"] and label_text:
            groups[name]["label"] = label_text

    fields = []
    for name, g in groups.items():
        fields.append(FillField(
            label=g["label"] or name,
            name=name,
            field_type="radio",
            options=g["options"],
            element_selector=g["selector"],
        ))
    return fields


async def _extract_checkbox_groups(page: Page) -> List[FillField]:
    """按 name 分组提取 checkbox。"""
    groups: dict[str, dict] = {}
    checkboxes = await page.query_selector_all("input[type='checkbox']:not([disabled])")

    for c in checkboxes:
        name = (await c.get_attribute("name")) or ""
        if not name:
            continue
        value = (await c.get_attribute("value")) or ""
        label_text = await _get_element_label(page, c)

        if name not in groups:
            groups[name] = {"options": [], "label": label_text, "selector": f"input[type='checkbox'][name='{name}']"}
        if value and value not in groups[name]["options"]:
            groups[name]["options"].append(value)
        if not groups[name]["label"] and label_text:
            groups[name]["label"] = label_text

    fields = []
    for name, g in groups.items():
        fields.append(FillField(
            label=g["label"] or name,
            name=name,
            field_type="checkbox",
            options=g["options"],
            element_selector=g["selector"],
        ))
    return fields


async def _get_element_label(page: Page, element: ElementHandle, elem_id: str = "") -> str:
    """获取元素关联的 label 文本。

    优先级：for/id 关联的 label > 父级 label > 前面的文本 > placeholder
    """
    # 1. for/id 关联
    if elem_id:
        try:
            label_elem = await page.query_selector(f"label[for='{elem_id}']")
            if label_elem:
                text = (await label_elem.inner_text()).strip()
                if text:
                    return text
        except Exception:
            pass

    # 2. 父级 label 包裹
    try:
        parent = await element.evaluate_handle("el => el.closest('label')")
        if parent:
            text = (await parent.inner_text()).strip()
            if text and len(text) < 200:
                return text
    except Exception:
        pass

    # 3. 前面的兄弟节点文本（常见于自定义表单）
    try:
        text = await element.evaluate("""el => {
            let prev = el.previousElementSibling;
            while (prev) {
                const t = prev.innerText || prev.textContent;
                if (t && t.trim().length > 0 && t.trim().length < 100) return t.trim();
                prev = prev.previousElementSibling;
            }
            // 检查父元素的前一个兄弟
            const parent = el.parentElement;
            if (parent) {
                const prevParent = parent.previousElementSibling;
                if (prevParent) {
                    const t = prevParent.innerText || prevParent.textContent;
                    if (t && t.trim().length > 0 && t.trim().length < 100) return t.trim();
                }
            }
            return '';
        }""")
        if text:
            return text
    except Exception:
        pass

    # 4. placeholder
    try:
        ph = await element.get_attribute("placeholder")
        if ph:
            return ph
    except Exception:
        pass

    return ""


# ============================================================
# 3. LLM 字段语义理解 + 值生成
# ============================================================

async def llm_generate_values(
    fields: List[FillField],
    resume_text: str,
    profile_summary: str,
    job_title: str,
    jd_text: str,
) -> List[FillField]:
    """调用 LLM 为每个字段生成填写值。"""
    from src.llm import client as llm
    from src.llm.prompts import fill_fields_prompt

    # 构造字段 JSON（只传必要信息）
    fields_json = json.dumps([
        {
            "index": i,
            "label": f.label,
            "placeholder": f.placeholder,
            "type": f.field_type,
            "options": f.options,
        }
        for i, f in enumerate(fields)
    ], ensure_ascii=False)

    messages = fill_fields_prompt(resume_text, profile_summary, job_title, jd_text, fields_json)

    # 定义 LLM 返回结构
    class FieldValueItem(BaseModel):
        index: int
        semantic_type: str = ""
        value: Optional[str] = None

    class FieldValueList(BaseModel):
        fields: List[FieldValueItem]

    try:
        result = await llm.chat_structured(messages, FieldValueList, temperature=0.1)
        for item in result.fields:
            if 0 <= item.index < len(fields):
                fields[item.index].semantic_type = item.semantic_type
                fields[item.index].value = item.value
        logger.info("LLM generated values for %d fields", len(result.fields))
    except Exception as e:
        logger.warning("LLM field value generation failed: %s", e)

    return fields


# ============================================================
# 4. 执行填写
# ============================================================

async def fill_fields(page: Page, fields: List[FillField]) -> List[FillField]:
    """执行表单填写，每个字段填写后验证。"""
    for field in fields:
        if field.value is None:
            field.status = FillStatus.SKIPPED
            continue
        if field.field_type == "file":
            field.status = await _fill_file(page, field)
        elif field.field_type == "select":
            field.status = await _fill_select(page, field)
        elif field.field_type == "radio":
            field.status = await _fill_radio(page, field)
        elif field.field_type == "checkbox":
            field.status = await _fill_checkbox(page, field)
        else:
            field.status = await _fill_text(page, field)

    return fields


async def _fill_text(page: Page, field: FillField) -> FillStatus:
    """填写文本框。"""
    try:
        el = page.locator(field.element_selector).first
        await el.wait_for(state="visible", timeout=5000)
        await el.fill(field.value or "")
        # SPA 框架：触发 input/change 事件
        await el.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); }")
        # 验证
        actual = await el.input_value()
        if actual == field.value:
            return FillStatus.FILLED
        else:
            field.error = f"验证失败: 期望 '{field.value}'，实际 '{actual}'"
            return FillStatus.FAILED
    except Exception as e:
        field.error = str(e)
        return FillStatus.FAILED


async def _fill_select(page: Page, field: FillField) -> FillStatus:
    """选择下拉框。"""
    try:
        el = page.locator(field.element_selector).first
        await el.wait_for(state="visible", timeout=5000)
        # value 可能是 option 的文本，需要匹配
        await el.select_option(label=field.value)
        await el.evaluate("el => el.dispatchEvent(new Event('change', {bubbles: true}))")
        return FillStatus.FILLED
    except Exception as e:
        field.error = str(e)
        return FillStatus.FAILED


async def _fill_radio(page: Page, field: FillField) -> FillStatus:
    """选择单选框。"""
    try:
        # 找 value 匹配的 radio
        selector = f"{field.element_selector}[value='{field.value}']"
        el = page.locator(selector).first
        if await el.count() == 0:
            # 尝试通过 label 文本找
            selector = f"{field.element_selector}"
            el = page.locator(selector).first
        await el.check()
        return FillStatus.FILLED
    except Exception as e:
        field.error = str(e)
        return FillStatus.FAILED


async def _fill_checkbox(page: Page, field: FillField) -> FillStatus:
    """勾选复选框。"""
    try:
        values = field.value.split(",") if field.value else []
        for v in values:
            v = v.strip()
            if not v:
                continue
            selector = f"{field.element_selector}[value='{v}']"
            el = page.locator(selector).first
            if await el.count() > 0:
                await el.check()
        return FillStatus.FILLED
    except Exception as e:
        field.error = str(e)
        return FillStatus.FAILED


async def _fill_file(page: Page, field: FillField) -> FillStatus:
    """上传文件。"""
    resume_path = os.getenv("RESUME_PATH", _DEFAULT_RESUME_PDF)
    if not os.path.exists(resume_path):
        field.error = f"简历文件不存在: {resume_path}"
        return FillStatus.FAILED
    try:
        el = page.locator(field.element_selector).first
        await el.set_input_files(resume_path)
        logger.info("Uploaded resume: %s", resume_path)
        return FillStatus.FILLED
    except Exception as e:
        field.error = str(e)
        return FillStatus.FAILED


# ============================================================
# 5. 主节点入口
# ============================================================

async def run(state: AgentState) -> AgentState:
    """LangGraph 节点：自动填写当前岗位的投递表单。"""
    if not state.apply_queue:
        state.add_error("fill_application", "投递队列为空")
        return state

    idx = state.current_job_index
    if idx >= len(state.apply_queue):
        state.add_error("fill_application", f"岗位索引越界: {idx}/{len(state.apply_queue)}")
        return state

    job = state.apply_queue[idx]
    browser = await get_browser()
    page = browser.page

    logger.info("Filling application for: %s", job.posting.title)

    try:
        # 1. 进入申请页
        await enter_application_page(page, job)

        # 2. HITL 检测
        await hitl.check_and_pause(page)

        # 3. 字段发现
        fields = await discover_form_fields(page)
        if not fields:
            state.add_error("fill_application", f"未发现可填写字段: {job.posting.title}")
            return state

        # 4. LLM 生成填写值
        resume_text = state.resume.full_text() if state.resume else ""
        profile_summary = state.profile.to_resume_text() if state.profile else ""
        jd_text = job.jd_for_match()

        fields = await llm_generate_values(fields, resume_text, profile_summary, job.posting.title, jd_text)

        # 5. 执行填写
        fields = await fill_fields(page, fields)

        # 6. 汇总结果
        filled = sum(1 for f in fields if f.status == FillStatus.FILLED)
        failed = [f for f in fields if f.status == FillStatus.FAILED]
        skipped = sum(1 for f in fields if f.status == FillStatus.SKIPPED)

        print(f"\n[填表结果] 岗位: {job.posting.title}")
        print(f"  总字段: {len(fields)} | 成功: {filled} | 失败: {len(failed)} | 跳过: {skipped}")
        if failed:
            print("  失败字段:")
            for f in failed:
                print(f"    - {f.label or f.name}: {f.error}")

        state.current_fill_fields = fields
        state.fill_results[job.posting.detail_url] = fields

        # 7. HITL 等待用户手动提交
        await hitl.pause(page, f"表单已填写完毕（{filled}/{len(fields)} 成功），请检查并手动点击提交")

        # 8. 记录结果（用户提交后）
        logger.info("Application submitted by user: %s", job.posting.title)

    except Exception as e:
        state.add_error("fill_application", f"{job.posting.title}: {e}")
        logger.exception("fill_application error")

    return state
