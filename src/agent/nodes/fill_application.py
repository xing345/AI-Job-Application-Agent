"""自动填写投递表单节点。

流程：进入申请页 → 字段发现（Playwright）→ LLM 语义映射+值生成
→ 执行填写+上传简历 → HITL 等待用户手动提交 → 记录结果。
"""
from __future__ import annotations

import asyncio
import json
import difflib
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
from src.models.application import ApplicationStatus
from src.models.job import JobDetail, JobPosting
from src.models.match import FillField, FillStatus

logger = logging.getLogger(__name__)

_DEFAULT_RESUME_PDF = str(Path(__file__).resolve().parent.parent.parent.parent / "data" / "resume.pdf")

# 申请按钮文本关键词
APPLY_BUTTON_TEXTS = ["立即投递", "申请职位", "投递简历", "立即申请", "投简历", "Apply", "apply now", "submit"]

# 法律/隐私/个人意愿相关字段关键词（必须要求用户确认，不得自动填写）
LEGAL_FIELDS_KEYWORDS = [
    "是否同意", "同意条款", "隐私政策", "用户协议", "授权", "声明",
    "竞业限制", "背景调查", "工作许可", "签证", "薪资期望", "期望薪资",
    "是否接受", "承诺", "保证", "确认无误", "真实性",
    "i agree", "i confirm", "authorize", "consent", "terms", "privacy",
    "work authorization", "work permit", "non-compete", "background check",
]

# 提交成功提示关键词
SUBMIT_SUCCESS_KEYWORDS = [
    "提交成功", "申请成功", "投递成功", "已提交", "已申请", "已投递",
    "申请已提交", "简历已投递", "感谢您的申请", "申请完成",
    "submitted", "application submitted", "successfully applied", "thank you for applying",
]


def _is_legal_field(label: str, placeholder: str = "") -> bool:
    """判断字段是否为法律/隐私/个人意愿字段，需要用户确认。"""
    text = (label + " " + placeholder).lower()
    return any(kw.lower() in text for kw in LEGAL_FIELDS_KEYWORDS)


async def _verify_submission(page, url_before: str, title_before: str) -> ApplicationStatus:
    """验证用户是否真的提交了申请。

    检查依据：
    1. URL 是否变化（提交后通常跳转到成功页或列表页）
    2. 页面标题是否变化
    3. 页面是否包含提交成功提示文本

    Returns:
        ApplicationStatus.PAGE_VERIFIED: 确认提交成功
        ApplicationStatus.UNKNOWN: 无法确认，需人工复核
    """
    try:
        url_after = page.url
        title_after = await page.title()
    except Exception:
        return ApplicationStatus.UNKNOWN

    # 1. URL 变化 → 大概率提交成功
    if url_after != url_before:
        logger.info("Submission verified: URL changed %s -> %s", url_before[:60], url_after[:60])
        return ApplicationStatus.PAGE_VERIFIED

    # 2. 标题变化
    if title_after != title_before:
        logger.info("Submission verified: title changed %s -> %s", title_before, title_after)
        return ApplicationStatus.PAGE_VERIFIED

    # 3. 检查成功提示文本
    try:
        body_text = await page.locator("body").inner_text()
        for kw in SUBMIT_SUCCESS_KEYWORDS:
            if kw.lower() in body_text.lower():
                logger.info("Submission verified: found success keyword '%s'", kw)
                return ApplicationStatus.PAGE_VERIFIED
    except Exception:
        pass

    logger.warning("Submission status unknown: URL and title unchanged, no success keyword found")
    return ApplicationStatus.UNKNOWN


# ============================================================
# 1. 进入申请页
# ============================================================

async def enter_application_page(page: Page, job: JobDetail) -> bool:
    """进入岗位申请页。

    流程：
    1. apply_url 为独立表单页（与详情页不同）→ 直接导航；
    2. 否则先确保打开岗位详情页（当前可能停在 about:blank 或其他页面），
       再在详情页点击"投递/申请"按钮进入表单。
    """
    detail_url = job.posting.detail_url
    apply_url = job.apply_url or detail_url

    async def goto_if_needed(url: str) -> None:
        if page.url != url:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await wait_for_load(page)

    # 1. 独立申请页：直接导航
    if apply_url != detail_url:
        try:
            await goto_if_needed(apply_url)
            return True
        except Exception as e:
            logger.warning("goto apply_url failed: %s", e)
            return False

    # 2. 先确保回到岗位详情页（关键：避免在 about:blank 上操作）
    try:
        await goto_if_needed(detail_url)
    except Exception as e:
        logger.warning("goto detail_url failed: %s", e)
        return False

    # 3. 在详情页找申请按钮并点击（同页跳转进入表单）
    for text in APPLY_BUTTON_TEXTS:
        try:
            btn = page.get_by_text(text, exact=False).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(2000)
                await wait_for_load(page)
                logger.info("Clicked apply button: '%s' -> %s", text, page.url)
                return True
        except Exception:
            continue

    # 尝试常见 selector
    for sel in [".apply-btn", ".btn-apply", "[class*='apply']", "button[type='submit']"]:
        if await safe_click(page, sel):
            await page.wait_for_timeout(2000)
            await wait_for_load(page)
            logger.info("Clicked apply selector: %s -> %s", sel, page.url)
            return True

    logger.warning("No apply entry found on detail page: %s", detail_url)
    return False


# ============================================================
# 1.5 表单预处理：滚动加载 + 展开动态模块
# ============================================================

async def _scroll_form(page: Page) -> None:
    """逐步滚动整个简历表单以触发懒加载，走两遍，最后回到顶部。"""
    for _ in range(2):
        for y in range(0, 16000, 700):
            await page.evaluate(f"window.scrollTo(0,{y})")
            await page.wait_for_timeout(110)
    await page.evaluate("window.scrollTo(0,0)")
    await page.wait_for_timeout(300)


async def _check_no_experience(page: Page, text: str) -> None:
    """勾选'无实习经历/无获奖信息'等复选框（已勾选则跳过）。"""
    try:
        lab = page.locator("label.no_experience", has_text=text)
        if await lab.count() == 0:
            return
        checked = await lab.first.evaluate("el => el.classList.contains('is-checked')")
        if not checked:
            await lab.first.scroll_into_view_if_needed()
            await lab.first.click(timeout=4000)
            await page.wait_for_timeout(300)
    except Exception as e:
        logger.warning("勾选'%s'失败: %s", text, str(e)[:80])


async def prepare_form(page: Page, profile) -> None:
    """表单预处理：滚动加载 + 勾选'无经历' + 按简历展开项目模块，使 DOM 稳定后再发现字段。"""
    await _scroll_form(page)

    # 0 段实习 / 获奖：勾选"无"，避免必填校验
    if not profile or not getattr(profile, "work_experience", None):
        await _check_no_experience(page, "无实习经历")
    if not profile or not getattr(profile, "awards", None):
        await _check_no_experience(page, "无获奖信息")

    # 项目经历：默认 1 组，按简历项目数补足。先确认按钮存在再点，不存在立即跳过。
    n_proj = len(profile.projects) if profile else 0
    try:
        btn = page.get_by_role("button", name="添加项目经历")
        if await btn.count() == 0:
            btn = page.get_by_text("添加项目经历", exact=True)
        if await btn.count() > 0:
            for _ in range(max(0, n_proj - 1)):
                await btn.last.click(timeout=2000)
                await page.wait_for_timeout(300)
        else:
            logger.info("未找到'添加项目经历'按钮，跳过展开")
    except Exception as e:
        logger.info("展开项目模块跳过: %s", str(e)[:60])

    # 展开新模块后再滚动加载
    await _scroll_form(page)
    logger.info("Form prepared (projects=%d)", n_proj)


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
            field = await _extract_select_field(page, sel, i)
            if field:
                fields.append(field)
    except Exception as e:
        logger.warning("select extraction error: %s", e)

    # 处理 textarea
    try:
        textareas = await page.query_selector_all("textarea:not([disabled]):not([type='hidden'])")
        for i, ta in enumerate(textareas):
            field = await _extract_input_field(
                page, ta,
                f"textarea:not([disabled]):not([type='hidden']) >> nth={i}",
                "textarea",
            )
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
            field = await _extract_input_field(
                page, inp,
                f"input:not([disabled]) >> nth={i}",
                itype,
            )
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


async def _extract_input_field(page: Page, element: ElementHandle, default_id: str, ftype: str) -> Optional[FillField]:
    """提取单个 input/textarea 字段信息。"""
    name = (await element.get_attribute("name")) or ""
    placeholder = (await element.get_attribute("placeholder")) or ""
    elem_id = (await element.get_attribute("id")) or ""
    readonly = await element.get_attribute("readonly")

    label = await _get_element_label(page, element, elem_id)

    # 只读文本输入框 = 自定义弹窗控件（点击后弹选项/日期面板）
    if ftype in ("text", "") and readonly is not None:
        if "日期" in placeholder or "日期" in label:
            ftype = "datepicker"
        else:
            ftype = "combobox"

    # 构造 selector（优先用 name，其次 id）
    if name:
        tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
        selector = f"{tag_name}[name='{name}']"
    elif elem_id:
        selector = f"#{elem_id}"
    else:
        selector = default_id

    # combobox：采集隐藏面板中的选项文本，供 LLM 精确选择
    options: list[str] = []
    if ftype == "combobox":
        try:
            options = await element.evaluate(
                """el => {
                    const c = el.closest('.el-select');
                    if (!c) return [];
                    return Array.from(c.querySelectorAll('.el-select-dropdown__item'))
                        .map(i => i.textContent.trim()).filter(Boolean);
                }"""
            )
        except Exception:
            options = []

    return FillField(
        label=label,
        placeholder=placeholder,
        name=name,
        field_type=ftype,
        element_selector=selector,
        options=options,
    )


async def _extract_select_field(page: Page, element: ElementHandle, index: int) -> Optional[FillField]:
    """提取 select 字段信息。"""
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

# 需要知识库支撑的字段关键词
KB_FIELD_KEYWORDS = [
    "项目经历", "项目经验", "项目描述", "项目介绍", "项目职责",
    "个人优势", "自我评价", "个人评价", "个人简介", "自我介绍",
    "open question", "openquestion", "开放问题", "为什么", "期望",
    "工作经历", "实习经历", "实习描述", "工作职责",
    "作品", "Portfolio", "作品集",
]


async def _gather_kb_context(fields: List[FillField], job_title: str, jd_text: str) -> str:
    """对需要知识库支撑的字段做语义检索，返回拼接的上下文片段。"""
    from src.kb_client import search_knowledge

    kb_queries: list[str] = []
    for f in fields:
        label = (f.label or f.placeholder or "").lower()
        if any(kw.lower() in label for kw in KB_FIELD_KEYWORDS):
            # query = 字段label + 岗位title + JD摘要
            jd_snippet = jd_text[:200] if jd_text else ""
            q = f"{f.label} {job_title} {jd_snippet}".strip()
            kb_queries.append(q)

    if not kb_queries:
        return ""

    # 合并去重查询，取 top-k 片段
    all_fragments: list[str] = []
    seen = set()
    for q in kb_queries[:3]:  # 最多查3次，避免过多调用
        fragments = await search_knowledge(q, top_k=2)
        for frag in fragments:
            key = frag[:100]
            if key not in seen:
                seen.add(key)
                all_fragments.append(frag)

    if not all_fragments:
        return ""

    kb_context = "\n\n--- 知识库相关片段（请结合这些真实经历/项目信息填写）---\n"
    kb_context += "\n\n".join(all_fragments[:5])
    kb_context += "\n--- 知识库片段结束 ---\n"
    return kb_context


async def llm_generate_values(
    fields: List[FillField],
    resume_text: str,
    profile_summary: str,
    job_title: str,
    jd_text: str,
    run_id: str = "",
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

    # 知识库检索：为项目经历/个人优势等字段拉取相关片段
    kb_context = await _gather_kb_context(fields, job_title, jd_text)
    if kb_context:
        profile_summary = profile_summary + "\n" + kb_context

    messages = fill_fields_prompt(resume_text, profile_summary, job_title, jd_text, fields_json)

    # 定义 LLM 返回结构
    class FieldValueItem(BaseModel):
        index: int
        semantic_type: str = ""
        value: Optional[str] = None

    class FieldValueList(BaseModel):
        fields: List[FieldValueItem]

    try:
        result = await llm.chat_structured(messages, FieldValueList, temperature=0.1, run_id=run_id)
        for item in result.fields:
            if 0 <= item.index < len(fields):
                fields[item.index].semantic_type = item.semantic_type
                fields[item.index].value = item.value
        logger.info("LLM generated values for %d fields", len(result.fields))
    except Exception as e:
        logger.warning("LLM field value generation failed: %s", e)

    return fields


async def apply_memory_to_fields(fields: List[FillField]) -> List[FillField]:
    """记忆库回填：对 LLM 给空的字段，按语义/标签从 known_fields 命中的自动带值。"""
    from src.storage import state_db
    hit_count = 0
    for f in fields:
        if f.value is not None:
            continue
        try:
            hit = await state_db.find_known_field(
                label=f.label or f.placeholder, semantic_type=f.semantic_type)
        except Exception:
            hit = None
        if hit:
            f.value = hit["value"]
            if not f.semantic_type:
                f.semantic_type = hit["field_key"]
            hit_count += 1
    if hit_count:
        logger.info("Memory store backfilled %d fields", hit_count)
    return fields


def _field_key_for(f: FillField) -> str:
    """为字段生成语义记忆主键：优先 LLM 语义类型，否则用可见标签。"""
    return f.semantic_type or (f.label or f.placeholder).strip() or "unknown"


async def ask_missing_fields(page: Page, fields: List[FillField]) -> List[FillField]:
    """对仍为 null 的字段 HITL 询问用户；用户手动在浏览器填后，读取值并存入记忆库。"""
    from src.storage import state_db
    missing = [f for f in fields if f.value is None]
    if not missing:
        return fields

    print("\n" + "=" * 60)
    print(f"  表单中有 {len(missing)} 个字段需要你补充信息：")
    for i, f in enumerate(missing, 1):
        req = "必填" if f.label and "*" in f.label else "选填"
        print(f"   {i}. [{(f.label or f.placeholder)[:36]}]（{f.field_type}，{req}）")
    print("-" * 60)
    print("  请在浏览器里手动填写上述字段；填完后回到终端按回车继续。")
    print("  （本次填写的值会被记住，下次任何站点遇到同类字段自动带上）")
    print("=" * 60, flush=True)

    await asyncio.to_thread(input, "按回车继续 > ")

    remembered = 0
    for f in missing:
        try:
            loc = page.locator(f.element_selector).first
            if await loc.count() == 0 or not await loc.is_visible():
                continue
            val = await loc.input_value()
            if not val:
                val = (await loc.inner_text()).strip()
            if val:
                f.value = val
                await state_db.upsert_known_field(
                    _field_key_for(f), f.label or f.placeholder, val)
                remembered += 1
        except Exception:
            pass
    if remembered:
        logger.info("Remembered %d user-provided fields to memory store", remembered)
    return fields


# ============================================================
# 4. 执行填写
# ============================================================

async def _dismiss_modal(page: Page) -> Optional[str]:
    """检测并关闭填写中途弹出的模态对话框（如误触的短信验证码框）。

    优先点'取消/关闭'；返回已关闭弹窗标题，无弹窗返回 None。
    """
    try:
        info = await page.evaluate(
            """() => {
                const wraps = Array.from(document.querySelectorAll(
                    '.el-dialog__wrapper, .el-message-box__wrapper, .el-drawer__wrapper'));
                const open = wraps.filter(w =>
                    w.style.display !== 'none' && getComputedStyle(w).display !== 'none');
                if (!open.length) return null;
                const w = open[0];
                const title = ((w.querySelector('.el-dialog__title, .el-message-box__title')
                    || {textContent: ''}).textContent || w.textContent.slice(0, 20)).trim();
                const btns = Array.from(w.querySelectorAll('button'));
                let btn = btns.find(b => b.textContent.trim() === '取消')
                    || btns.find(b => b.textContent.includes('取消'))
                    || w.querySelector('.el-dialog__headerbtn')
                    || btns.find(b => b.textContent.trim() === '关闭');
                if (btn) { btn.click(); return title; }
                return title;
            }"""
        )
        if info:
            logger.info("Dismissed modal dialog: %s", info)
        return info
    except Exception:
        return None


async def fill_fields(page: Page, fields: List[FillField]) -> List[FillField]:
    """执行表单填写，每个字段填写后验证。

    法律/隐私/个人意愿字段标记为 NEEDS_USER_INPUT，不自动填写。
    """
    for field in fields:
        # 先关闭可能弹出的模态框（如误触的验证码），避免遮挡
        await _dismiss_modal(page)

        # 法律/隐私字段不自动填写，要求用户确认
        if _is_legal_field(field.label, field.placeholder):
            field.status = FillStatus.NEEDS_USER_INPUT
            field.error = "法律/隐私字段，请手动确认"
            continue

        if field.value is None:
            field.status = FillStatus.SKIPPED
            continue

        # file 上传不依赖可见性，直接处理
        if field.field_type == "file":
            field.status = await _fill_file(page, field)
            continue

        # datepicker 交人工
        if field.field_type == "datepicker":
            field.status = FillStatus.NEEDS_USER_INPUT
            field.error = "日期选择，请手动选择起止时间"
            continue

        # 统一滚动到元素并快速判断可见性，避免对隐藏字段长超时
        loc = page.locator(field.element_selector)
        try:
            await loc.first.scroll_into_view_if_needed(timeout=3000)
            await page.wait_for_timeout(150)
            if not await loc.first.is_visible():
                field.status = FillStatus.SKIPPED
                field.error = "字段当前不可见（折叠/隐藏），请手动处理"
                continue
        except Exception:
            field.status = FillStatus.SKIPPED
            field.error = "定位不到字段，请手动处理"
            continue

        # combobox 前关闭可能残留的下拉，避免遮挡
        if field.field_type == "combobox":
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(150)

        if field.field_type == "combobox":
            field.status = await _fill_combobox(page, field)
        elif field.field_type == "select":
            field.status = await _fill_select(page, field)
        elif field.field_type == "radio":
            field.status = await _fill_radio(page, field)
        elif field.field_type == "checkbox":
            field.status = await _fill_checkbox(page, field)
        else:
            field.status = await _fill_text(page, field)

    return fields


async def _fill_combobox(page: Page, field: FillField) -> FillStatus:
    """填写 Element UI 自定义下拉：定位所属 el-select 容器，展开后在容器内匹配选项点击。"""
    target = (field.value or "").strip()
    try:
        inp = page.locator(field.element_selector).first
        await inp.scroll_into_view_if_needed()
        handle = await inp.element_handle()

        # 记录所属 el-select 容器（closest 向上查找，避免 locator ancestor 作用域问题）
        has_container = await page.evaluate(
            """el => {
                const c = el.closest('.el-select');
                if (!c) return false;
                window.__sel = c;
                return true;
            }""",
            handle,
        )
        if not has_container:
            field.error = "找不到 el-select 容器"
            return FillStatus.FAILED

        # 已选值与目标一致则跳过
        cur = (await inp.input_value()).strip()
        if cur and (cur == target or target in cur or cur in target):
            return FillStatus.FILLED

        await inp.click(timeout=4000)
        await page.wait_for_timeout(700)

        # 展开时下拉面板被 append 到 body：找当前可见的那个 dropdown
        visible = await page.evaluate(
            """() => {
                const dds = Array.from(document.querySelectorAll('.el-select-dropdown'));
                for (const dd of dds) {
                    const items = Array.from(dd.querySelectorAll('.el-select-dropdown__item'));
                    const vis = items.filter(it => (it.offsetParent || it.getClientRects().length));
                    if (vis.length) {
                        window.__opendd = dd;
                        return items
                            .map((it, i) => ({
                                i,
                                t: it.textContent.trim(),
                                vis: !!(it.offsetParent || it.getClientRects().length),
                            }))
                            .filter(o => o.t && o.vis);
                    }
                }
                return [];
            }"""
        )

        pick_idx = -1
        chosen = ""
        for o in visible:
            if o["t"] == target or target in o["t"] or o["t"] in target:
                pick_idx, chosen = o["i"], o["t"]
                break
        if pick_idx < 0:
            best, fz = -1, -1.0
            for o in visible:
                s = difflib.SequenceMatcher(None, target, o["t"]).ratio()
                if s > fz:
                    fz, best, chosen = s, o["i"], o["t"]
            if fz >= 0.55:
                pick_idx = best

        if pick_idx < 0:
            await page.keyboard.press("Escape")
            field.error = f"下拉中无匹配'{target}'的选项（可见: {[o['t'] for o in visible][:10]}）"
            return FillStatus.FAILED

        # 在展开面板内点击选项（触发 Vue @click）
        await page.evaluate(
            """i => window.__opendd.querySelectorAll('.el-select-dropdown__item')[i].click()""",
            pick_idx,
        )
        await page.wait_for_timeout(400)
        logger.info("Combobox selected: '%s' -> '%s'", (field.label or target)[:20], chosen)
        return FillStatus.FILLED
    except Exception as e:
        field.error = str(e)
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return FillStatus.FAILED


async def _fill_text(page: Page, field: FillField) -> FillStatus:
    """填写文本框。"""
    try:
        el = page.locator(field.element_selector).first
        await el.wait_for(state="visible", timeout=5000)
        await el.fill(field.value or "")
        # 验证（Playwright fill 会自动触发 input/change 事件）
        actual = await el.input_value()
        if actual == field.value:
            return FillStatus.FILLED
        # textarea 常有字数上限，超长被截断：实际内容是期望的前缀即视为成功
        if field.field_type == "textarea" and actual and (field.value or "").startswith(actual) \
                and len(actual) >= 15:
            field.error = f"内容被字段长度限制截断（{len(actual)} 字），请检查"
            return FillStatus.FILLED
        field.error = f"验证失败: 期望 '{(field.value or '')[:30]}'，实际 '{actual[:30]}'"
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
        return FillStatus.FILLED
    except Exception as e:
        field.error = str(e)
        return FillStatus.FAILED


async def _fill_radio(page: Page, field: FillField) -> FillStatus:
    """选择单选框。先检查当前状态，已选中则不重复点击。"""
    try:
        # 找 value 匹配的 radio
        selector = f"{field.element_selector}[value='{field.value}']"
        el = page.locator(selector).first
        if await el.count() == 0:
            # 尝试通过 label 文本找
            selector = f"{field.element_selector}"
            el = page.locator(selector).first

        # 先检查是否已选中，避免重复点击反转
        if await el.is_checked():
            logger.debug("Radio already checked: %s=%s", field.name, field.value)
            return FillStatus.FILLED

        await el.check()
        return FillStatus.FILLED
    except Exception as e:
        field.error = str(e)
        return FillStatus.FAILED


async def _fill_checkbox(page: Page, field: FillField) -> FillStatus:
    """勾选复选框。先检查当前状态，只勾选未选中的，避免反转。"""
    try:
        values = field.value.split(",") if field.value else []
        for v in values:
            v = v.strip()
            if not v:
                continue
            selector = f"{field.element_selector}[value='{v}']"
            el = page.locator(selector).first
            if await el.count() > 0:
                # 只勾选未选中的
                if not await el.is_checked():
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
        # 1-2. 进入申请页 + HITL 检测；若遇登录/验证，处理后重新进入（最多2轮，
        # 覆盖"扫码登录后跳回详情页、需再次点击投递"的情况）
        for attempt in range(2):
            if state.apply_url:
                # 直达模式：prepare_direct_apply 已打开该链接。等 SPA 渲染后判断。
                await page.wait_for_timeout(3000)
                # 检测主文档 + iframe 内是否有可填元素（含 contenteditable / 自定义组件）
                has_form = await page.evaluate("""() => {
                    const probe = (doc) => !!doc.querySelector(
                        'input, textarea, select, [contenteditable=""], [class*=select], [class*=Select], [class*=field], [class*=Field]');
                    if (probe(document)) return true;
                    for (const f of document.querySelectorAll('iframe')) {
                        try { if (f.contentDocument && probe(f.contentDocument)) return true; } catch(e) {}
                    }
                    return false;
                }""")
                # 用户给的链接本身就是 apply/resume 表单页时，即使没探测到原生 input 也继续
                looks_like_form = any(k in page.url for k in ["/apply", "/resume", "/form"])
                entered = bool(has_form) or looks_like_form or await enter_application_page(page, job)
            else:
                entered = await enter_application_page(page, job)
            if not entered:
                state.add_error("fill_application", f"无法进入岗位申请页: {job.posting.title}")
                return state
            block = await hitl.check_and_pause(page)
            if not block:
                break
            logger.info("申请流程遇阻已处理，重新进入申请页（第 %d 轮）", attempt + 1)
        else:
            state.add_error("fill_application", f"登录后仍无法进入申请表单: {job.posting.title}")
            return state

        # 3. 表单预处理（滚动加载 / 展开动态模块），再字段发现
        await prepare_form(page, state.profile)
        fields = await discover_form_fields(page)
        if not fields:
            state.add_error("fill_application", f"未发现可填写字段: {job.posting.title}")
            return state

        # 4. LLM 生成填写值
        resume_text = state.resume.full_text() if state.resume else ""
        profile_summary = state.profile.to_resume_text() if state.profile else ""
        jd_text = job.jd_for_match()

        fields = await llm_generate_values(fields, resume_text, profile_summary, job.posting.title, jd_text, state.run_id)

        # 4.5 记忆库回填（跨站复用用户补充过的字段）
        fields = await apply_memory_to_fields(fields)
        # 4.6 仍缺的字段 HITL 询问用户，并记住本次补充
        fields = await ask_missing_fields(page, fields)

        # 5. 执行填写
        fields = await fill_fields(page, fields)

        # 6. 汇总结果
        filled = sum(1 for f in fields if f.status == FillStatus.FILLED)
        failed = [f for f in fields if f.status == FillStatus.FAILED]
        skipped = sum(1 for f in fields if f.status == FillStatus.SKIPPED)
        needs_user = sum(1 for f in fields if f.status == FillStatus.NEEDS_USER_INPUT)

        print(f"\n[填表结果] 岗位: {job.posting.title}")
        print(f"  总字段: {len(fields)} | 成功: {filled} | 失败: {len(failed)} | 跳过: {skipped} | 需人工确认: {needs_user}")
        if failed:
            print("  失败字段:")
            for f in failed:
                print(f"    - {f.label or f.name}: {f.error}")
        if needs_user:
            print("  ⚠️  以下字段需人工确认（未自动填写）:")
            for f in fields:
                if f.status == FillStatus.NEEDS_USER_INPUT:
                    print(f"    - {f.label or f.name}")

        state.current_fill_fields = fields
        state.fill_results[job.posting.detail_url] = fields

        # 7. 表单填写完成 → 设置状态
        state.current_application_status = ApplicationStatus.FORM_FILLED
        logger.info("Form filled: %s | filled=%d failed=%d needs_user=%d run_id=%s",
                    job.posting.title, filled, len(failed), needs_user, state.run_id)

        # 8. 记录暂停前的页面状态，用于提交验证
        try:
            url_before = page.url
            title_before = await page.title()
        except Exception:
            url_before = ""
            title_before = ""

        # 9. HITL 等待用户手动提交 → 设置状态
        state.current_application_status = ApplicationStatus.WAITING_FOR_SUBMIT
        block_result = await hitl.pause(
            page,
            f"表单已填写完毕（{filled}/{len(fields)} 成功，{needs_user} 个需人工确认），请检查并手动点击提交"
        )

        # 10. 用户输入 continue → 设置状态
        state.current_application_status = ApplicationStatus.USER_CONFIRMED_SUBMIT
        logger.info("User confirmed continue: %s | url_before=%s run_id=%s",
                    job.posting.title, url_before[:60], state.run_id)

        # 11. 验证页面是否真的提交成功
        verified_status = await _verify_submission(page, url_before, title_before)
        state.current_application_status = verified_status

        if verified_status == ApplicationStatus.PAGE_VERIFIED:
            print(f"\n[提交验证] 页面已跳转/变化，确认提交成功")
        else:
            print(f"\n[提交验证] ⚠️  页面未变化，无法确认是否提交成功，请手动检查")
            state.add_error("fill_application", f"{job.posting.title}: 提交状态未知，需人工复核")

    except Exception as e:
        state.add_error("fill_application", f"{job.posting.title}: {e}")
        logger.exception("fill_application error")
        state.current_application_status = ApplicationStatus.FAILED

    return state


# ============================================================
# 直达填表：--apply-url 直接打开链接并填表
# ============================================================

async def prepare_direct_apply(state: AgentState) -> AgentState:
    """打开用户给的投递链接，做登录墙/验证码 HITL 检测，构造单岗位队列。

    跳过岗位发现、初筛、JD 抓取、匹配、确认——进去就填表。
    若给的是岗位详情页，后续 fill_application 会自动点"投递"按钮进表单。
    """
    url = state.apply_url
    if not url:
        return state

    browser = await get_browser()
    page = browser.page
    logger.info("Direct apply: opening %s", url)
    print(f"\n[直达填表] 打开链接: {url}")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        state.add_error("direct_apply", f"打开链接失败: {e}")
        return state

    # 登录墙/验证码 → HITL 暂停等用户处理
    await hitl.check_and_pause(page)

    try:
        title = (await page.title())[:80] or "直接投递岗位"
    except Exception:
        title = "直接投递岗位"

    posting = JobPosting(detail_url=url, title=title)
    job = JobDetail(posting=posting, apply_url=url)
    state.apply_queue = [job]
    state.current_job_index = 0
    logger.info("Direct apply ready: %s", title)
    return state
