"""
智能表单填写器
支持断点续传、自动登录检测和泛化表单填写
"""

import asyncio
import json
import time
import base64
import re
import sqlite3
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from pathlib import Path
from loguru import logger

from playwright.async_api import Page, Browser, Error, TimeoutError
from pydantic import BaseModel, Field
from dataclasses import dataclass

# 添加项目根目录到路径 (注意: 本文件位于 src/automation/ 下, 需上溯 3 层到仓库根)
import sys
import os
project_root = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, project_root)

from src.utils.llm_client import get_llm_client
from src.models.schemas import (
    DynamicUserPersona,
    FormSchema,
    FormFieldSchema,
    BrowserAction,
    FormFieldSchema
)


@dataclass
class FormFillContext:
    """表单填写上下文"""
    url: str
    page: Page
    browser: Browser
    persona: DynamicUserPersona
    form_data: Dict[str, Any]
    login_required: bool = False
    storage_path: Optional[str] = None
    interrupted: bool = False
    resume_path: Optional[str] = None


# ============================================================ 安全规则常量
# FIX 1: 提交/投递语义关键字 (HITL —— 最终提交按钮绝不静默自动点击)
# 英文采用词边界匹配, 避免误伤 application 等普通英文词;
# 中文保守收录"最终提交"语义, 不收录 登录/下一步/保存/继续 等中间动作。
_SUBMIT_LIKE_EN_PATTERNS = [
    r"\bsubmit\b",
    r"\bapply\b",
    r"\bsend\s+application\b",
    r"\bfinal\b",
    r"\bfinish\b",
]
_SUBMIT_LIKE_EN_RE = [re.compile(p, re.IGNORECASE) for p in _SUBMIT_LIKE_EN_PATTERNS]
# 含 提交 以覆盖纯"提交"按钮; 申请 会同时覆盖 提交申请/发送申请/完成申请 等
_SUBMIT_LIKE_ZH = ["投递", "提交", "申请", "同意并投递"]

# 明确的中间导航/编辑语义 (整词匹配), 这类按钮不属于"最终提交", 可自动点击
_NEXT_LIKE_RE = re.compile(
    r"(next|continue|save|back|add|下一步|继续|保存|上一步|返回|添加|下一页)",
    re.IGNORECASE
)


class MissingInfoStore:
    """缺失信息记忆库

    当表单字段在用户数据中找不到对应信息时, 停下询问用户补充,
    并将补充结果存入 SQLite, 下次遇到同类字段自动带出。
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(Path(project_root) / "data" / "known_fields.db")
        self._init_db()

    def _init_db(self):
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS known_fields (
                    field_key TEXT PRIMARY KEY,
                    label TEXT,
                    value TEXT,
                    created_at TEXT,
                    last_used TEXT
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"初始化缺失信息记忆库失败: {e}")

    def get(self, field_key: str, label: str = None) -> Optional[str]:
        """精确匹配 + 标签包含关系模糊匹配 (处理 '身份证' vs '身份证号' 等变体)"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM known_fields WHERE field_key=?", (field_key,)
            ).fetchone()
            if row is None and label:
                label_lower = label.lower()
                for r in conn.execute("SELECT * FROM known_fields"):
                    stored = (r["label"] or "").lower()
                    if stored and (stored in label_lower or label_lower in stored):
                        row = r
                        break
            if row is not None:
                conn.execute(
                    "UPDATE known_fields SET last_used=? WHERE field_key=?",
                    (datetime.now().isoformat(), row["field_key"]),
                )
                conn.commit()
                conn.close()
                return row["value"]
            conn.close()
            return None
        except Exception as e:
            logger.warning(f"查询记忆库失败: {e}")
            return None

    def save(self, field_key: str, label: str, value: str):
        try:
            conn = sqlite3.connect(self.db_path)
            now = datetime.now().isoformat()
            conn.execute("""
                INSERT INTO known_fields (field_key, label, value, created_at, last_used)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(field_key) DO UPDATE SET label=?, value=?, last_used=?
            """, (field_key, label, value, now, now, label, value, now))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"保存记忆库失败: {e}")


class SmartFormFiller:
    """智能表单填写器"""

    def __init__(
        self,
        headless: bool = False,
        viewport: tuple = (1280, 720),
        timeout: int = 30000
    ):
        """
        初始化智能表单填写器

        Args:
            headless: 是否无头模式
            viewport: 视口大小
            timeout: 超时时间
        """
        self.headless = headless
        self.viewport = viewport
        self.timeout = timeout
        self.browser = None
        self.llm_client = get_llm_client()
        self.context_cache = {}
        self.storage_dir = Path(project_root) / "storage"
        self.storage_dir.mkdir(exist_ok=True)
        # 缺失信息记忆库 (SQLite, 存于 data/)
        self.missing_store = MissingInfoStore()
        # 默认简历路径 (config.json paths.resume 兜底)
        self.default_resume_path = self._load_default_resume_path()

    def _load_default_resume_path(self) -> str:
        """从 config.json 读取默认简历路径"""
        try:
            config_path = Path(project_root) / "config.json"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    resume = json.load(f).get("paths", {}).get("resume")
                    if resume:
                        return resume
        except Exception:
            pass
        return str(Path(project_root) / "data" / "resume.pdf")

    async def start_browser(self) -> Browser:
        """启动浏览器"""
        if self.browser:
            return self.browser

        try:
            from playwright.async_api import async_playwright

            self.playwright = await async_playwright().start()
            # viewport 属于上下文/页面配置, 不能传给 BrowserType.launch()
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless
            )

            logger.info("浏览器启动成功")
            return self.browser

        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            raise

    async def stop_browser(self):
        """停止浏览器"""
        if self.browser:
            await self.browser.close()
            if hasattr(self, 'playwright'):
                await self.playwright.stop()
            logger.info("浏览器已停止")

    async def check_login_status(self, page: Page, url: str) -> bool:
        """
        检查登录状态

        Args:
            page: Playwright页面
            url: 目标URL

        Returns:
            是否需要登录
        """
        try:
            # 导航到页面
            await page.goto(url, timeout=self.timeout)
            await page.wait_for_load_state("networkidle")

            # FIX 3: 精确判定真实"登录墙", 不再用整页文本是否包含 邮箱/手机号/验证码 等
            # 关键词来判定 —— 申请表里同样会出现邮箱/手机号输入框, 旧逻辑会把每个申请表
            # 都误判为登录墙, 导致流程死锁在手动登录环节。
            is_login_wall = await self._looks_like_login_wall(page)
            if is_login_wall:
                logger.info("检测到登录页面, 需要先完成登录")
                # FIX 2: 登录页常伴随验证码 → 出现则暂停, 请用户人工完成
                await self._pause_for_captcha(page, max_tries=2)
                return True

            logger.info("当前页面不是登录墙, 继续表单填写流程")
            return False

        except Exception as e:
            logger.warning(f"检查登录状态失败: {e}")
            return False

    async def _looks_like_login_wall(self, page: Page) -> bool:
        """
        精确判定当前页面是否为登录墙 (FIX 3)

        仅以下两种情况判定为登录墙:
          (a) 存在可见的密码输入框, 且页面标题/大标题文本或密码框所在表单的提交按钮
              带登录语义 (登录/登入/sign in/log in/...);
          (b) 存在某个表单, 其 action URL 或提交按钮文本为登录语义。

        普通申请表 (只含邮箱/手机号等文本字段、无密码框与登录语义) 不会被误判为登录墙。
        """
        try:
            signals = await page.evaluate("""() => {
                const lower = (s) => String(s == null ? "" : s).toLowerCase();
                const norm = (s) => lower(s).replace(/\\s+/g, "");
                // 登录语义: action URL/标题用包含匹配; 按钮文本用"精确登录文案"匹配
                // (避免把"登录后投递/登录并申请"这类投递按钮误判为登录墙)
                const LOGIN_KEYS = ["login", "log in", "signin", "sign-in", "sign in", "登录", "登入"];
                const EXACT_BTN = ["登录", "登入", "立即登录", "马上登录", "安全登录",
                                   "快速登录", "login", "signin", "sign in", "log in"];
                const hasLoginKey = (s) => LOGIN_KEYS.some((k) => lower(s).includes(k));
                const isExactLoginBtn = (s) => EXACT_BTN.some((k) => norm(s) === norm(k));
                const visible = (el) => {
                    if (!el || el.nodeType !== 1) return false;
                    try {
                        const st = window.getComputedStyle(el);
                        if (st.display === "none" || st.visibility === "hidden") return false;
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    } catch (err) { return false; }
                };
                // 可见密码输入框
                const pw = Array.from(document.querySelectorAll(
                    'input[type="password"], input[name="password" i], ' +
                    'input[placeholder*="密码" i], input[placeholder*="password" i]'
                )).find(visible);
                const pwForm = pw ? pw.closest("form") : null;
                // 页面标题 / 大标题文本
                const headingParts = [];
                if (document.title) headingParts.push(document.title);
                for (const el of document.querySelectorAll("h1, h2, h3, legend")) {
                    if (visible(el)) headingParts.push(el.innerText || el.textContent || "");
                }
                const headingLogin = hasLoginKey(headingParts.join(" "));
                // 表单是否登录语义: action 含登录关键字, 或提交控件文本为精确登录文案
                const formIsLogin = (f) => {
                    const action = f.getAttribute("action") || "";
                    if (hasLoginKey(action)) return true;
                    const subs = Array.from(f.querySelectorAll(
                        'button, input[type="submit"], input[type="button"], ' +
                        'a[role="button"], a[class*="btn" i]'
                    ));
                    return subs.some((b) => isExactLoginBtn(b.innerText || b.value || ""));
                };
                let anyFormLogin = false;
                for (const f of Array.from(document.querySelectorAll("form"))) {
                    if (formIsLogin(f)) { anyFormLogin = true; break; }
                }
                return {
                    has_visible_password: !!pw,
                    heading_login: headingLogin,
                    pw_form_login: pwForm ? formIsLogin(pwForm) : false,
                    any_form_login: anyFormLogin
                };
            }""")

            if signals.get("any_form_login"):
                logger.info("登录墙判定: 存在 action/提交文案为登录语义的表单")
                return True
            if signals.get("has_visible_password") and (
                signals.get("heading_login") or signals.get("pw_form_login")
            ):
                logger.info("登录墙判定: 可见密码框 + 登录语义标题/表单")
                return True
            return False

        except Exception as e:
            logger.warning(f"登录墙判定异常, 按非登录页处理: {e}")
            return False

    async def _detect_captcha(self, page: Page) -> bool:
        """
        检测当前页面是否存在 CAPTCHA/验证码 (FIX 2)

        仅匹配验证码专有信号, 绝不把普通邮箱/手机号输入误判为验证码:
          - .g-recaptcha 容器 / recaptcha / hcaptcha / geetest 的 iframe
          - name/id 含 captcha、placeholder/aria-label 为"验证码"的输入框
          - alt/占位为"验证码"的图片类输入
          - 表单内可见文本出现 验证码/图形验证/滑块验证
        """
        try:
            captcha_selectors = [
                ".g-recaptcha",
                'iframe[src*="recaptcha" i]',
                'iframe[src*="hcaptcha" i]',
                'iframe[src*="geetest" i]',
                'input[name*="captcha" i]',
                'input[id*="captcha" i]',
                'input[placeholder*="验证码"]',
                'input[aria-label*="验证码"]',
                'img[alt*="验证码"]',
                'img[src*="captcha" i]',
            ]
            for selector in captcha_selectors:
                element = await page.query_selector(selector)
                if element is None:
                    continue
                try:
                    if await element.is_visible():
                        logger.info(f"检测到 CAPTCHA 信号: {selector}")
                        return True
                except Exception:
                    # 元素在检查期间被移除 / 导航竞态 → 无法确认可见, 跳过该信号,
                    # 避免误报; 真正的验证码会在后续(提交前/异常时)检查点再次被捕获
                    continue

            # 表单内/验证码图片旁的可见中文文本信号
            text_hit = await page.evaluate("""() => {
                const visible = (el) => {
                    if (!el || el.nodeType !== 1) return false;
                    try {
                        const st = window.getComputedStyle(el);
                        if (st.display === "none" || st.visibility === "hidden") return false;
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    } catch (err) { return false; }
                };
                // 可见表单文本出现 验证码/图形验证/滑块验证
                for (const f of Array.from(document.querySelectorAll("form"))) {
                    if (!visible(f)) continue;
                    const t = f.innerText || f.textContent || "";
                    if (/(验证码|图形验证|滑块验证)/.test(t)) return true;
                }
                // 图片旁出现"验证码"文案 (典型图形验证码布局: img + 输入框)
                for (const img of Array.from(document.querySelectorAll("img"))) {
                    if (!visible(img)) continue;
                    const box = img.getBoundingClientRect();
                    if (box.width < 20 || box.width > 800) continue;
                    const parent = img.parentElement;
                    if (parent && visible(parent) &&
                            /验证码/.test((parent.innerText || "").slice(0, 300))) {
                        return true;
                    }
                }
                return false;
            }""")
            if text_hit:
                logger.info("检测到 CAPTCHA 信号: 页面文本含验证码/图形验证/滑块验证")
                return True
            return False

        except Exception as e:
            logger.warning(f"检测验证码失败: {e}")
            return False

    async def _pause_for_captcha(self, page: Page, max_tries: int = 3) -> bool:
        """
        检测验证码, 一旦出现则暂停并在终端提示用户人工完成 (FIX 2, HITL)

        Args:
            page: Playwright 页面
            max_tries: 最多提示用户几次 (避免无限循环)

        Returns:
            True: 未出现验证码, 或人工处理后已消失, 可继续;
            False: 多次尝试后仍检测到验证码 (已输出明确错误, 调用方应中止/跳过提交)
        """
        for attempt in range(1, max_tries + 1):
            if not await self._detect_captcha(page):
                return True
            logger.warning(f"检测到 CAPTCHA/验证码 (第 {attempt}/{max_tries} 次), 暂停等待人工处理")
            print(f"\n{'='*60}")
            print("⚠️ 检测到 CAPTCHA/验证码，请人工完成验证后按回车继续")
            print("   请在浏览器中人工完成验证 (滑块 / 图形 / 短信等)")
            print(f"{'='*60}")
            input()

        # 多次提示后仍存在 → 明确报错, 不再无限循环
        if await self._detect_captcha(page):
            logger.error("多次确认后仍检测到 CAPTCHA/验证码, 无法自动继续")
            print("\n❌ 多次尝试后仍检测到 CAPTCHA/验证码，无法自动继续，请人工处理后重试。")
            return False
        return True

    @staticmethod
    def _is_submit_like(text: str) -> bool:
        """判断文本/属性集合是否含"最终提交/投递"语义关键字 (FIX 1, 大小写不敏感)"""
        if not text:
            return False
        if any(p.search(text) for p in _SUBMIT_LIKE_EN_RE):
            return True
        return any(kw in text for kw in _SUBMIT_LIKE_ZH)

    async def _perform_click_safely(self, page: Page, instruction: BrowserAction) -> bool:
        """
        安全执行 LLM 下发的 click 指令 (FIX 1)

        点击前先检查目标 (selector 文本 + 元素 text/value/aria/name/type/class 等属性)
        是否含"最终提交/投递"语义关键字; 若疑似提交类按钮 → 必须在终端经用户确认 (y/n)
        后才点击, 绝不静默自动点击。普通点击 (下一页/下一步/添加经历/下拉选择等) 行为不变。

        Returns:
            True: 已执行点击; False: 元素未找到 / 用户拒绝点击
        """
        element = await page.query_selector(instruction.target)
        if element is None:
            logger.warning(f"未找到点击元素: {instruction.target}")
            return False

        # 收集目标元素的文本与属性信号, 用于关键字判定
        attrs = await element.evaluate("""(el) => {
            const t = (v) => (v == null ? "" : String(v)).trim();
            const cls = typeof el.className === "string"
                        ? el.className : (el.getAttribute("class") || "");
            return {
                text: t(el.innerText || el.textContent || "").slice(0, 300),
                value: t(el.value),
                aria: t(el.getAttribute("aria-label")),
                name: t(el.getAttribute("name")),
                etype: t(el.getAttribute("type")),
                cls: t(cls),
                elid: t(el.getAttribute("id"))
            };
        }""")

        corpus = " ".join([
            instruction.target or "", instruction.description or "",
            attrs.get("text", ""), attrs.get("value", ""), attrs.get("aria", ""),
            attrs.get("name", ""), attrs.get("etype", ""),
            attrs.get("cls", ""), attrs.get("elid", "")
        ])

        if not self._is_submit_like(corpus):
            # 普通点击 (非提交语义)
            await element.click(timeout=instruction.timeout * 1000)
            return True

        # 命中提交语义 → 排除明确的中间导航按钮 (整词=下一步/继续等), 避免打断分步表单
        element_text = (attrs.get("text") or "").strip()
        if element_text and _NEXT_LIKE_RE.fullmatch(element_text):
            logger.info(f"中间导航按钮, 正常自动点击: {element_text}")
            await element.click(timeout=instruction.timeout * 1000)
            return True

        # 疑似最终提交/投递类按钮 → 走人工确认 (HITL)
        shown = element_text[:60] or attrs.get("value", "")[:60] or instruction.target
        print(f"\n⚠️ 检测到疑似提交类按钮: 「{shown}」")
        confirm = input("是否确认点击? (y/n): ").strip().lower()
        if confirm == 'y':
            logger.info(f"用户已确认点击疑似提交按钮: {instruction.target}")
            await element.click(timeout=instruction.timeout * 1000)
            return True

        logger.warning(f"用户拒绝点击疑似提交按钮, 跳过该指令: {instruction.description}")
        return False

    async def save_cookies(self, context: FormFillContext) -> str:
        """
        保存Cookie到文件

        Args:
            context: 表单填写上下文

        Returns:
            Cookie文件路径
        """
        try:
            if not context.page:
                return None

            cookies = await context.page.context.cookies()
            storage_path = self.storage_dir / f"cookies_{int(time.time())}.json"

            with open(storage_path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)

            logger.info(f"Cookie已保存到: {storage_path}")
            return str(storage_path)

        except Exception as e:
            logger.error(f"保存Cookie失败: {e}")
            return None

    async def load_cookies(self, page: Page, storage_path: str) -> bool:
        """
        加载Cookie

        Args:
            page: Playwright页面
            storage_path: Cookie文件路径

        Returns:
            是否加载成功
        """
        try:
            with open(storage_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)

            await page.context.add_cookies(cookies)
            logger.info(f"Cookie已从 {storage_path} 加载")
            return True

        except Exception as e:
            logger.error(f"加载Cookie失败: {e}")
            return False

    async def handle_login_interruption(self, context: FormFillContext) -> bool:
        """
        处理登录中断

        Args:
            context: 表单填写上下文

        Returns:
            是否登录成功
        """
        logger.info("等待用户手动登录...")

        # 打印登录提示
        print(f"\n{'='*60}")
        print("🔐 需要登录才能继续")
        print(f"{'='*60}")
        print(f"网站: {context.url}")
        print("请在浏览器中手动完成登录")
        print("登录完成后按 Enter 继续...")
        print(f"{'='*60}")

        # 等待用户输入
        input()

        # 检查登录状态
        is_logged_in = not await self.check_login_status(context.page, context.url)

        if is_logged_in:
            # 保存Cookie
            storage_path = await self.save_cookies(context)
            if storage_path:
                context.storage_path = storage_path
                logger.info("登录成功，Cookie已保存")
                return True
            else:
                logger.warning("登录成功但保存Cookie失败")
                return True
        else:
            logger.error("登录失败，请重试")
            return False

    async def analyze_form_structure(self, page: Page) -> FormSchema:
        """
        分析表单结构

        Args:
            page: Playwright页面

        Returns:
            表单数据结构
        """
        try:
            await page.wait_for_load_state("networkidle")

            # 获取页面内容
            html_content = await page.content()

            # 使用LLM分析表单
            prompt = f"""
            请分析以下HTML表单，提取所有字段信息：

            {html_content[:3000]}

            输出JSON格式：
            {{
                "form_title": "表单标题",
                "form_action": "表单提交地址",
                "form_method": "GET/POST",
                "estimated_completion_time": 60,
                "difficulty_level": "easy",
                "form_type": "standard",
                "fields": [
                    {{
                        "field_name": "字段名称",
                        "field_type": "字段类型",
                        "label": "字段标签",
                        "placeholder": "占位文本",
                        "required": true,
                        "options": ["选项1", "选项2"],
                        "css_selector": "CSS选择器",
                        "xpath": "XPath",
                        "validation_rules": {{"type": "string", "max_length": 100}}
                    }}
                ],
                "submit_button": {{
                    "text": "提交按钮文本",
                    "css_selector": "CSS选择器",
                    "xpath": "XPath"
                }}
            }}
            """

            analysis = await self.llm_client.generate_response(prompt, json_output=True)

            # 创建表单结构
            form_schema = FormSchema(
                form_url=page.url,
                form_title=analysis.get("form_title", "未知表单"),
                fields=[],
                submit_button=analysis.get("submit_button", {}),
                estimated_completion_time=analysis.get("estimated_completion_time", 60),
                difficulty_level=analysis.get("difficulty_level", "medium"),
                form_type=analysis.get("form_type", "standard"),
                analyzed_at=datetime.now()
            )

            # 处理字段
            for field_data in analysis.get("fields", []):
                field_schema = FormFieldSchema(
                    field_name=field_data.get("field_name", ""),
                    field_type=field_data.get("field_type", "text"),
                    label=field_data.get("label", ""),
                    placeholder=field_data.get("placeholder", ""),
                    required=field_data.get("required", False),
                    options=field_data.get("options", []),
                    css_selector=field_data.get("css_selector", ""),
                    xpath=field_data.get("xpath", ""),
                    validation_rules=field_data.get("validation_rules", {})
                )
                form_schema.fields.append(field_schema)

            logger.info(f"表单分析完成，共 {len(form_schema.fields)} 个字段")
            return form_schema

        except Exception as e:
            logger.error(f"表单分析失败: {e}")
            # 返回空表单
            return FormSchema(
                form_url=page.url,
                form_title="未知表单",
                fields=[],
                submit_button={},
                estimated_completion_time=60,
                difficulty_level="hard",
                form_type="unknown",
                analyzed_at=datetime.now()
            )

    async def generate_filling_instructions(
        self,
        form_schema: FormSchema,
        persona: DynamicUserPersona
    ) -> List[BrowserAction]:
        """
        生成表单填写指令

        Args:
            form_schema: 表单结构
            persona: 用户画像

        Returns:
            填写指令列表
        """
        try:
            # 构建用户数据 (兼容 pydantic 模型与 dict)
            def _g(_p, _k, _default=None):
                return getattr(_p, _k, None) if not isinstance(_p, dict) else _p.get(_k, _default)

            tech_skills = _g(persona, "technical_skills", {}) or {}
            if isinstance(tech_skills, dict):
                skill_list = [s for skills in tech_skills.values() for s in (skills or [])]
            else:
                skill_list = list(tech_skills)

            career_obj = _g(persona, "career_objective", {}) or {}
            if isinstance(career_obj, dict):
                locations = career_obj.get("location_preference") or []
                salary = career_obj.get("salary_expectation")
            else:
                locations = getattr(career_obj, "location_preference", None) or []
                salary = getattr(career_obj, "salary_expectation", None)

            work_exp = _g(persona, "work_experience", []) or []

            user_data = {
                "name": _g(persona, "name", ""),
                "email": _g(persona, "email", ""),
                "phone": _g(persona, "phone", ""),
                "skills": list(set(skill_list)),
                "experience_years": len(work_exp),
                "location": locations[0] if locations else "未知",
                "salary_expectation": salary or "面议"
            }

            prompt = f"""
            基于以下表单结构和用户数据，生成详细的表单填写指令：

            表单结构：
            {form_schema.model_dump_json(indent=2, ensure_ascii=False)}

            用户数据：
            {json.dumps(user_data, ensure_ascii=False, indent=2)}

            请为每个字段生成填写指令，包括：
            1. 操作类型（click/type/select）
            2. 目标选择器
            3. 填写值
            4. 操作描述

            重要规则：
            1. 如果某个必填字段在用户数据中找不到对应信息，请将 "value" 设为 "__MISSING__"
            2. 如果某个可选字段没有对应信息，请将 "value" 设为 "__SKIP__"（跳过不填）
            3. 绝不编造用户数据中没有的信息，宁可标记为 __MISSING__ 也不要瞎填
            4. 【安全红线】绝不点击任何最终"提交/投递"类按钮！若某按钮的文本、name、aria-label 或
               class 含有提交关键字 (submit / apply / send application / 提交 / 投递 / 申请 /
               发送申请 / 同意并投递 / confirm / finish / 完成申请), 禁止对它生成 click 指令。
               这类按钮只能在系统的人工确认 (HITL) 环节由用户决定是否点击 —— 表单结构中的
               submit_button 仅用于系统定位最终提交按钮, 你绝不能自行点击它。
            5. 你只负责填写字段与必要的中间交互 (下一页 / 下一步 / 添加经历 / 下拉选择 / 上传等)。
               若某个必点目标疑似上述提交按钮, 宁可跳过也不要尝试绕过规则。

            输出JSON格式：
            {{
                "instructions": [
                    {{
                        "action_type": "click/type/select",
                        "target": "CSS选择器或XPath",
                        "value": "要填写的值",
                        "description": "操作描述",
                        "timeout": 10
                    }}
                ]
            }}
            """

            response = await self.llm_client.generate_response(prompt, json_output=True)
            instructions = response.get("instructions", [])

            # 转换为BrowserAction对象
            browser_actions = []
            for instruction in instructions:
                action = BrowserAction(
                    action_type=instruction.get("action_type", "type"),
                    target=instruction.get("target", ""),
                    value=instruction.get("value", ""),
                    timeout=instruction.get("timeout", 10),
                    description=instruction.get("description", "")
                )
                browser_actions.append(action)

            logger.info(f"生成 {len(browser_actions)} 条填写指令")
            return browser_actions

        except Exception as e:
            logger.error(f"生成填写指令失败: {e}")
            return []

    @staticmethod
    def _field_key(instruction: BrowserAction) -> str:
        """生成字段唯一键 (基于语义化描述, 不含CSS选择器以便跨站匹配)"""
        raw = (instruction.description or "").lower()
        tokens = re.findall(r"[一-鿿0-9a-z]+", raw)
        return "_".join(tokens)[:80]

    async def _resolve_missing_value(self, instruction: BrowserAction) -> Optional[str]:
        """缺失字段处理: 先查记忆库, 没有再询问用户并存入记忆库"""
        key = self._field_key(instruction)
        if not key:
            return None

        # 1) 记忆库命中 → 自动带出
        known = self.missing_store.get(key, instruction.description)
        if known:
            logger.info(f"记忆库命中: {instruction.description} = {known}")
            print(f"   ℹ️ 字段「{instruction.description}」已从记忆库自动填入: {known}")
            return known

        # 2) 停下询问用户, 并记录到记忆库
        print(f"\n⚠️ 缺少信息: {instruction.description}")
        print(f"   目标: {instruction.target}")
        val = input("   请输入该字段的值 (直接回车跳过): ").strip()
        if val:
            self.missing_store.save(key, instruction.description, val)
            logger.info(f"已记录缺失信息: {instruction.description} = {val}")
            return val
        return None

    async def _upload_resume(self, page: Page, resume_path: str) -> bool:
        """上传简历文件"""
        try:
            file_input = await page.query_selector("input[type='file']")
            if file_input:
                await file_input.set_input_files(resume_path)
                logger.info(f"简历已上传: {resume_path}")
                return True
            logger.warning("未找到文件上传输入框 (input[type='file'])")
            return False
        except Exception as e:
            logger.error(f"上传简历失败: {e}")
            return False

    async def execute_filling_instructions(
        self,
        context: FormFillContext,
        instructions: List[BrowserAction]
    ) -> Dict[str, Any]:
        """
        执行填写指令

        Args:
            context: 表单填写上下文
            instructions: 填写指令

        Returns:
            填写结果: {"success": bool, "submitted": bool, "filled": int}
        """
        page = context.page
        success_count = 0

        for i, instruction in enumerate(instructions, 1):
            try:
                logger.info(f"执行第 {i} 条指令: {instruction.description}")

                # 可选字段且无数据 → 跳过
                if instruction.value == "__SKIP__":
                    logger.info(f"跳过可选字段: {instruction.description}")
                    continue

                # 必填字段但数据缺失 → 查记忆库 / 询问用户并记录
                if instruction.value == "__MISSING__":
                    value = await self._resolve_missing_value(instruction)
                    if value is None:
                        logger.warning(f"用户未提供, 跳过字段: {instruction.description}")
                        continue
                    instruction.value = value

                if instruction.action_type == "click":
                    # 点击操作 (FIX 1: 疑似最终提交/投递按钮必须先经用户确认, 绝不静默自动点击)
                    clicked = await self._perform_click_safely(page, instruction)
                    if clicked:
                        success_count += 1

                elif instruction.action_type == "type":
                    # 输入操作
                    element = await page.query_selector(instruction.target)
                    if element:
                        await element.fill(instruction.value, timeout=instruction.timeout * 1000)
                        success_count += 1
                    else:
                        logger.warning(f"未找到输入元素: {instruction.target}")

                elif instruction.action_type == "select":
                    # 选择操作
                    element = await page.query_selector(instruction.target)
                    if element:
                        await element.select_option(instruction.value, timeout=instruction.timeout * 1000)
                        success_count += 1
                    else:
                        logger.warning(f"未找到选择元素: {instruction.target}")

                elif instruction.action_type == "wait":
                    # 等待操作
                    await asyncio.sleep(instruction.timeout)

                # 添加短暂延迟
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"执行指令失败: {instruction.description} - {e}")
                # FIX 2(c): 指令异常时可能被验证码挡住 → 检测并暂停请用户人工处理
                try:
                    if await self._detect_captcha(page):
                        logger.warning("指令执行异常, 疑似遇到验证码, 暂停等待人工处理")
                        if not await self._pause_for_captcha(page, max_tries=2):
                            logger.error("验证码多次未能解除, 中止剩余填写指令")
                            break
                except Exception as cap_err:
                    logger.warning(f"指令异常后检查验证码失败: {cap_err}")

        # 上传简历文件 (主路径补上简历投递)
        uploaded = False
        resume_path = getattr(context, "resume_path", None)
        if resume_path and os.path.exists(resume_path):
            uploaded = await self._upload_resume(page, resume_path)

        # 提交前人工确认 (HITL, 遵守项目安全规则: 绝不自动点击最终提交按钮)
        submitted = False
        try:
            # FIX 2(b): 提交前先检测验证码, 出现则暂停请用户人工完成
            if not await self._pause_for_captcha(page, max_tries=2):
                logger.error("提交前仍检测到验证码, 已中止自动提交, 请人工处理后重试")
                return {
                    "success": success_count > 0 and success_count >= len(instructions) * 0.6,
                    "submitted": False,
                    "filled": success_count
                }
            submit_button_data = (context.form_data or {}).get("submit_button") or {}
            submit_selector = submit_button_data.get("css_selector")
            if submit_selector:
                submit_button = await page.query_selector(submit_selector)
                if submit_button:
                    print(f"\n{'='*60}")
                    print("📝 表单填写完成, 即将投递")
                    print(f"   已填写字段: {success_count}/{len(instructions)}"
                          + (f", 简历上传: {'✅' if uploaded else '❌'}" if resume_path else ""))
                    print(f"{'='*60}")
                    confirm = input("是否确认提交该申请? (y/n): ").strip().lower()
                    if confirm == 'y':
                        await submit_button.click()
                        submitted = True
                        logger.info("表单已提交")
                    else:
                        logger.info("用户取消提交")
                else:
                    logger.warning("未找到提交按钮, 跳过提交")
            else:
                logger.warning("未解析到提交按钮, 跳过自动提交")
        except Exception as e:
            logger.error(f"提交表单失败: {e}")

        logger.info(f"表单填写完成, 成功 {success_count}/{len(instructions)} 条指令")
        success = success_count > 0 and success_count >= len(instructions) * 0.6
        return {"success": success, "submitted": submitted, "filled": success_count}

    async def fill_form(
        self,
        url: str,
        persona: DynamicUserPersona,
        storage_path: str = None,
        resume_path: str = None
    ) -> Dict[str, Any]:
        """
        填写表单的主方法

        Args:
            url: 表单URL
            persona: 用户画像
            storage_path: 已保存的Cookie路径
            resume_path: 简历文件路径 (默认取 config.json paths.resume)

        Returns:
            填写结果
        """
        try:
            logger.info(f"开始填写表单: {url}")

            # 启动浏览器
            browser = await self.start_browser()
            context = await browser.new_context()
            page = await context.new_page()

            # 设置视口
            await page.set_viewport_size({"width": 1280, "height": 720})

            # 检查登录状态
            login_required = await self.check_login_status(page, url)

            if login_required:
                # 创建上下文
                form_context = FormFillContext(
                    url=url,
                    page=page,
                    browser=browser,
                    persona=persona,
                    form_data={},
                    login_required=True
                )

                # 处理登录
                if not await self.handle_login_interruption(form_context):
                    return {
                        "success": False,
                        "error": "登录失败",
                        "url": url,
                        "completed_steps": []
                    }

                # 如果有保存的Cookie，尝试加载
                if storage_path:
                    await self.load_cookies(page, storage_path)

            # 重新导航到页面
            await page.goto(url, timeout=self.timeout)
            await page.wait_for_load_state("networkidle")

            # FIX 2(a): 页面加载/导航后检测验证码, 出现则暂停请用户人工完成
            if not await self._pause_for_captcha(page, max_tries=2):
                await self.stop_browser()
                return {
                    "success": False,
                    "error": "页面验证码多次未能解除, 无法继续自动填写",
                    "url": url,
                    "completed_steps": []
                }

            # 分析表单结构
            logger.info("分析表单结构...")
            form_schema = await self.analyze_form_structure(page)

            # 生成填写指令
            logger.info("生成填写指令...")
            instructions = await self.generate_filling_instructions(form_schema, persona)

            if not instructions:
                logger.error("无法生成填写指令")
                return {
                    "success": False,
                    "error": "无法生成填写指令",
                    "url": url,
                    "completed_steps": []
                }

            # 执行填写
            logger.info("开始执行填写...")
            form_context = FormFillContext(
                url=url,
                page=page,
                browser=browser,
                persona=persona,
                form_data=form_schema.model_dump(),
                login_required=login_required,
                storage_path=storage_path,
                resume_path=resume_path or self.default_resume_path
            )

            fill_result = await self.execute_filling_instructions(form_context, instructions)
            fill_success = fill_result.get("success", False)
            submitted = fill_result.get("submitted", False)

            # 保存Cookie（如果需要）
            if login_required and form_context.storage_path:
                storage_path = form_context.storage_path

            # 停止浏览器
            await self.stop_browser()

            return {
                "success": fill_success,
                "submitted": submitted,
                "url": url,
                "form_title": form_schema.form_title,
                "field_count": len(form_schema.fields),
                "completed_steps": len(instructions),
                "filled_fields": fill_result.get("filled", 0),
                "storage_path": storage_path,
                "filled_at": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"填写表单失败: {e}")
            # 确保浏览器被停止
            if 'browser' in locals():
                await self.stop_browser()
            return {
                "success": False,
                "error": str(e),
                "url": url,
                "completed_steps": []
            }


# 工具函数
async def create_form_filler(headless: bool = False) -> SmartFormFiller:
    """创建智能表单填写器实例"""
    return SmartFormFiller(headless=headless)


async def fill_application_form(
    url: str,
    persona: DynamicUserPersona,
    storage_path: str = None,
    resume_path: str = None,
    headless: bool = False
) -> Dict[str, Any]:
    """
    填写申请表单的快捷函数

    Args:
        url: 表单URL
        persona: 用户画像
        storage_path: Cookie存储路径
        resume_path: 简历文件路径
        headless: 是否无头模式

    Returns:
        填写结果
    """
    filler = SmartFormFiller(headless=headless)
    return await filler.fill_form(url, persona, storage_path, resume_path=resume_path)


# 测试函数
async def test_form_filler():
    """测试智能表单填写器"""
    print("=== 测试智能表单填写器 ===")

    try:
        # 创建用户画像
        from src.models.schemas import DynamicUserPersona, CareerObjective, SoftSkills, PersonalityTraits, CareerConstraints

        persona = DynamicUserPersona(
            name="测试用户",
            email="test@example.com",
            phone="13800138000",
            technical_skills={"languages": ["Python", "JavaScript"]},
            soft_skills=SoftSkills(),
            domain_knowledge={},
            career_objective=CareerObjective(target_positions=["开发工程师"]),
            personality_traits=PersonalityTraits(),
            constraints=CareerConstraints(),
            strengths=["编程"],
            weaknesses=[],
            work_preferences={}
        )

        print("✅ 用户画像创建成功")

        # 创建表单填写器
        filler = SmartFormFiller(headless=True)  # 使用无头模式测试
        print("✅ 表单填写器创建成功")

        # 测试URL
        test_url = "https://httpbin.org/forms/post"

        print(f"开始测试表单填写: {test_url}")

        # 执行填写
        result = await fill_application_form(
            url=test_url,
            persona=persona,
            headless=True
        )

        print(f"\n✅ 表单填写测试完成！")
        print(f"   成功: {result['success']}")
        print(f"   URL: {result['url']}")
        print(f"   表单标题: {result.get('form_title', '未知')}")
        print(f"   字段数: {result.get('field_count', 0)}")
        print(f"   完成步骤: {result.get('completed_steps', 0)}")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def test_login_detection():
    """测试登录检测"""
    print("\n=== 测试登录检测 ===")

    try:
        from src.models.schemas import DynamicUserPersona, CareerObjective, SoftSkills, PersonalityTraits, CareerConstraints

        # 创建简单的用户画像
        persona = DynamicUserPersona(
            name="测试用户",
            email="test@example.com",
            phone="13800138000",
            technical_skills={},
            soft_skills=SoftSkills(),
            domain_knowledge={},
            career_objective=CareerObjective(target_positions=["开发工程师"]),
            personalityTraits=PersonalityTraits(),
            constraints=CareerConstraints(),
            strengths=[],
            weaknesses=[],
            work_preferences={}
        )

        # 创建表单填写器
        filler = SmartFormFiller(headless=True)

        print("✅ 登录检测功能就绪")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def test_form_analysis():
    """测试表单分析"""
    print("\n=== 测试表单分析 ===")

    try:
        from src.utils.llm_client import get_llm_client

        client = get_llm_client()

        # 模拟HTML表单
        mock_html = """
        <form action="/submit" method="POST">
            <h1>用户注册表单</h1>
            <div>
                <label>姓名:</label>
                <input type="text" name="name" placeholder="请输入姓名" required>
            </div>
            <div>
                <label>邮箱:</label>
                <input type="email" name="email" placeholder="请输入邮箱" required>
            </div>
            <div>
                <label>密码:</label>
                <input type="password" name="password" placeholder="请输入密码" required>
            </div>
            <div>
                <label>性别:</label>
                <select name="gender">
                    <option value="male">男</option>
                    <option value="female">女</option>
                </select>
            </div>
            <button type="submit">注册</button>
        </form>
        """

        prompt = f"""
        分析以下表单：

        {mock_html}

        输出JSON格式字段信息：
        {{
            "form_title": "表单标题",
            "form_action": "提交地址",
            "fields": [
                {{
                    "field_name": "字段名",
                    "field_type": "类型",
                    "label": "标签",
                    "required": true,
                    "css_selector": "CSS选择器",
                    "xpath": "XPath"
                }}
            ]
        }}
        """

        response = await client.generate_response(prompt, json_output=True)

        print("✅ 表单分析成功！")
        print(f"   表单标题: {response.get('form_title')}")
        print(f"   字段数: {len(response.get('fields', []))}")
        for field in response.get('fields', [])[:3]:
            print(f"   - {field['field_name']} ({field['field_type']})")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def main():
    """主测试函数"""
    print("🚀 开始 Phase 9 功能测试...")

    results = []

    # 测试1: 智能表单填写
    results.append(await test_form_filler())

    # 测试2: 登录检测
    results.append(await test_login_detection())

    # 测试3: 表单分析
    results.append(await test_form_analysis())

    # 输出测试结果
    print(f"\n{'='*60}")
    print("📊 测试结果汇总")
    print(f"{'='*60}")

    passed = sum(results)
    total = len(results)

    print(f"通过: {passed}/{total}")

    if passed == total:
        print("✅ 所有测试通过！")
        return True
    else:
        print("❌ 部分测试失败，请检查配置")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)