"""
职位匹配器模块
抓取 JD 文本并评估简历匹配度
"""

import asyncio
import json
import re
from typing import Dict, List
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field
from loguru import logger
from openai import AsyncOpenAI

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from src.models.schemas import ResumeSchema
from src.models.instruction_schemas import TargetInstructionSchema
from src.search.hitl import BlockHandler

# 浏览器内执行：定位页面里的「JD 正文块」。
# 直接取 body 会把导航/筛选/页脚一起塞给 LLM（正文被截断），
# 这里挑「命中 JD 关键词最多、且块本身尽量小」的容器。
_JD_BLOCK_JS = r"""() => {
  const KEYS = ["职位描述","岗位职责","工作职责","任职要求","任职资格","岗位要求",
    "工作要求","职位要求","工作内容","招聘要求","岗位描述","job description",
    "responsibilities","requirements","qualifications","about the role","what you"];
  let best = "", bestScore = 0;
  const els = document.querySelectorAll("div,section,article,main,td,li,form");
  for (let i = 0; i < els.length && i < 3000; i++) {
    const t = (els[i].innerText || "").trim();
    if (t.length < 80 || t.length > 8000) continue;
    const low = t.toLowerCase();
    let hits = 0;
    for (const k of KEYS) if (low.includes(k.toLowerCase())) hits++;
    if (!hits) continue;
    // 命中越多越好；块越小越可能正是 JD 容器
    const score = hits * 1000 - t.length / 100;
    if (score > bestScore) { bestScore = score; best = t; }
  }
  return best;
}"""

# JD 正文起点的关键词（清文本时用来丢掉前面的导航噪声）
_JD_START_KEYS = (
    "职位描述", "岗位职责", "工作职责", "任职要求", "任职资格", "岗位要求",
    "工作内容", "招聘要求", "岗位描述", "job description", "responsibilities",
    "requirements", "qualifications", "about the role",
)


class MatchResultSchema(BaseModel):
    """匹配结果数据模型"""
    score: int = Field(ge=0, le=100, description="匹配分数（0-100）")
    is_match: bool = Field(..., description="是否匹配")
    reasons: List[str] = Field(default_factory=list, description="匹配原因")
    missing_skills: List[str] = Field(default_factory=list, description="缺少的技能")
    matched_skills: List[str] = Field(default_factory=list, description="匹配的技能")
    match_summary: str = Field("", description="匹配总结")


class JobMatcherConfig:
    """匹配器配置"""
    def __init__(self, openai_api_key: str = None, base_url: str = None, model: str = None,
                 headless: bool = True, user_data_dir: str = None,
                 persist_login: bool = None, visible_concurrency: int = 2):
        # 未显式传入时从 config.json 的 llm / browser 段读取（环境变量兜底）
        llm_cfg = {}
        browser_cfg = {}
        try:
            config_path = os.path.join(project_root, "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    _cfg = json.load(f)
                llm_cfg = _cfg.get("llm", {}) or {}
                browser_cfg = _cfg.get("browser", {}) or {}
        except Exception:
            pass

        self.openai_api_key = (
            openai_api_key or llm_cfg.get("api_key") or os.getenv("OPENAI_API_KEY") or ""
        )
        self.base_url = base_url or llm_cfg.get("base_url") or os.getenv("OPENAI_BASE_URL") or None
        self.model = model or llm_cfg.get("model") or os.getenv("OPENAI_MODEL") or "gpt-4o"
        # 使用异步客户端: _llm_evaluate 在 async 方法中 await, 不能用同步 OpenAI 客户端
        self.llm_client = (
            AsyncOpenAI(api_key=self.openai_api_key, base_url=self.base_url)
            if self.openai_api_key else None
        )
        self.playwright_timeout = 30000  # 毫秒（原 30 会导致所有 JD 抓取 30ms 超时）
        self.retry_attempts = 3
        # JD 抓取浏览器是否无头；与发现阶段一致用可见浏览器，便于人工过验证
        self.headless = headless
        # 真实 Chrome 指纹，去掉 HeadlessChrome 标识
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        # 登录态复用：与职位发现阶段共用同一个用户目录，
        # 用户在可见窗口里登录一次 Boss/猎聘，抓 JD 时不必再登录一遍
        self.persist_login = bool(
            browser_cfg.get("persist_login", True) if persist_login is None else persist_login
        )
        self.user_data_dir = user_data_dir or browser_cfg.get("user_data_dir") or None
        # 相对路径按项目根解析，保证与 BrowserJobFinder 用同一个目录（相对 cwd 会漂移）
        if self.user_data_dir and not os.path.isabs(self.user_data_dir):
            self.user_data_dir = os.path.join(project_root, self.user_data_dir)
        # 可见浏览器下并发开页上限：5 个标签页轮流抢焦点 = 用户看到的「页面疯狂闪烁」
        self.visible_concurrency = max(1, int(visible_concurrency))
        # HITL：详情页需要登录 / 验证码时停下汇报给用户处理（None 则按 headless 自建）
        self.block_handler = None



class JobMatcher:
    """职位匹配器"""

    def __init__(self, config: JobMatcherConfig):
        self.config = config
        self.logger = logger.bind(module="job_matcher")
        # 统一的 HITL 阻断处理器；串行锁保证并发抓 JD 时只暂停一次
        self.block_handler = config.block_handler or BlockHandler(
            interactive=True, headless=config.headless
        )
        self._block_lock = asyncio.Lock()
        # 真实浏览器指纹（_new_stealth_context 用）
        self.user_agent = config.user_agent

    async def fetch_jd_text(self, url: str) -> str:
        """
        抓取单个页面的 JD 文本（单页调试/小批量用；批量请用 fetch_jd_texts）
        失败返回空串（与批量接口一致，交由调用方用职位标题兜底）

        Args:
            url: 招聘页面 URL

        Returns:
            str: JD 文本内容
        """
        try:
            async with async_playwright() as p:
                context, browser = await self._launch_browser(p)
                try:
                    page = None
                    try:
                        page = await context.new_page()
                        text, blocked = await self._render_job_page(page, url, 2.0)
                        if blocked:
                            self.logger.warning(f"JD 页面被拦截（{blocked}）: {url}")
                        elif text:
                            self.logger.info(f"成功抓取 JD: {url}（{len(text)} 字）")
                        return text
                    finally:
                        if page:
                            try:
                                await page.close()
                            except Exception:
                                pass
                finally:
                    await context.close()
                    if browser is not None:
                        await browser.close()

        except Exception as e:
            self.logger.error(f"抓取 JD 失败: {url}, 错误: {e}")
            return ""

    # 反爬验证页 / 登录墙 / 非岗位页特征；命中说明拿到的不是 JD 正文
    # 「强」特征：命中即可判定被挡
    _BLOCK_HINTS = (
        "cloudflare", "cf-browser-verification", "checking your browser", "人机验证",
        "拖动滑块", "行为验证", "请完成安全验证",
        "访问被拒绝", "access denied", "enable javascript and cookies",
        "网络不给力，请稍后重试",
    )
    # 「弱」特征：这些词在正常 JD 正文里也会出现（例如「验证码风控系统开发工程师」），
    # 必须配合 DOM 上真的有验证控件才判定为拦截页
    _WEAK_BLOCK_HINTS = ("验证码", "安全验证", "安全检查", "滑块")
    # 验证控件的 DOM 特征（只数元素，不点击）
    _BLOCK_CONTROL_SELECTOR = (
        "input[placeholder*='验证码'], input[name*='captcha' i], input[id*='captcha' i], "
        "iframe[src*='captcha' i], [class*='captcha' i], [class*='slider' i]"
    )
    _LOGINWALL_HINTS = ("用户登录", "请登录", "账号密码登录", "扫码登录", "sign in to continue")

    async def _has_block_control(self, page) -> bool:
        """页面上是否真的存在验证控件/密码输入框（DOM 证据，失败按没有算）"""
        if page is None:
            return False
        try:
            n = await page.eval_on_selector_all(
                f"{self._BLOCK_CONTROL_SELECTOR}, input[type='password']",
                "els => els.length",
            )
            return bool(int(n or 0))
        except Exception:
            return False

    async def _is_blocked_page(self, text: str, page=None) -> str:
        """
        识别拦截页：返回 'captcha' / 'login' / ''（正常页）。

        给了 page 时会用 DOM 证据复核弱特征：JD 正文里出现「验证码」三个字
        不该把这一页判成验证墙（否则那条 JD 直接丢掉，只能拿标题兜底打分）。
        """
        low = (text or "").lower()
        if any(h in low for h in self._BLOCK_HINTS):
            return "captcha"
        if any(h in low for h in self._WEAK_BLOCK_HINTS):
            if page is None or await self._has_block_control(page):
                return "captcha"
        # 登录墙：正文极短且以登录提示为主（有 page 时再要求存在密码框/验证控件）
        if len(low) < 800 and any(h in low for h in self._LOGINWALL_HINTS):
            if page is None or await self._has_block_control(page):
                return "login"
        return ""

    async def _new_stealth_context(self, browser):
        """创建带真实浏览器指纹的上下文"""
        context = await browser.new_context(
            user_agent=self.user_agent,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1920, "height": 1080},
        )
        # 隐藏自动化特征 navigator.webdriver
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        return context

    async def _launch_browser(self, p) -> tuple:
        """
        启动抓 JD 用的浏览器，优先复用与「职位发现」同一个用户目录。

        Returns:
            (context, browser_or_None)
            - 持久化启动成功：browser 可能是 None（Playwright 对 persistent context
              的 `context.browser` 返回 None），关闭时只需关 context；
            - 回退匿名上下文：正常返回 (context, browser)。

        为什么必须复用目录：搜索链路原来是「发现用浏览器 A（用户在里面登录了
        Boss）→ A 关闭 → 抓 JD 用浏览器 B（全新会话）」——用户在 A 里的登录等于
        白做，B 又弹一次登录墙，于是用户被迫反复登录、窗口反复闪。共用同一个
        用户目录后登录态落盘，跨阶段、跨轮次都还在。
        """
        args = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        if self.config.persist_login and self.config.user_data_dir:
            try:
                os.makedirs(self.config.user_data_dir, exist_ok=True)
                ctx = await p.chromium.launch_persistent_context(
                    self.config.user_data_dir,
                    headless=self.config.headless,
                    user_agent=self.user_agent,
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    viewport={"width": 1920, "height": 1080},
                    args=args,
                )
                await ctx.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
                self.logger.info(
                    f"JD 抓取浏览器已启动（复用登录态目录 {self.config.user_data_dir}）"
                )
                # 新浏览器实例 = 新会话：清掉「该站已人工处理过」的记录，
                # 否则登录墙会被当成「已通行」静默放行，JD 抓空却没人提醒
                try:
                    self.block_handler.reset()
                except Exception:
                    pass
                return ctx, None
            except Exception as e:
                self.logger.warning(f"持久化浏览器目录不可用（{e}），回退匿名上下文")
        browser = await p.chromium.launch(headless=self.config.headless, args=args)
        try:
            self.block_handler.reset()
        except Exception:
            pass
        return await self._new_stealth_context(browser), browser

    async def _render_job_page(self, page, url: str, settle_seconds: float) -> tuple:
        """
        打开岗位页并等待 SPA 渲染完成。

        Returns:
            (text, blocked)：text 是被拦截/失败时的空串；blocked 是
            'captcha' / 'login' / ''。blocked 作为返回值而不是实例属性，
            因为批量抓取是并发的，挂在 self 上会串台。
        """
        await page.goto(url, wait_until="domcontentloaded",
                        timeout=self.config.playwright_timeout)
        # SPA 详情页靠 XHR 取数：尽量等网络空闲，最多再等 8 秒
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(settle_seconds)
        text = await self._extract_page_text(page)
        blocked = await self._is_blocked_page(text, page)
        # 正文过短多半是 SPA 没渲染完，滚动触发懒加载后再取一次
        if not blocked and len(text) < 200:
            try:
                await page.mouse.wheel(0, 1500)
                await asyncio.sleep(1.5)
                text = await self._extract_page_text(page)
                blocked = await self._is_blocked_page(text, page)
            except Exception:
                pass
        if blocked == "captcha":
            self.logger.warning(f"JD 页面被反爬验证拦截: {url}")
            return "", blocked
        if blocked == "login":
            self.logger.warning(f"JD 页面需要登录才能查看: {url}")
            return "", blocked
        return text, ""

    async def _extract_page_text(self, page) -> str:
        """把已打开的页面内容整理成 JD 文本（优先取 JD 正文块，而不是整页 body）"""
        try:
            title = await page.title()
        except Exception:
            title = ""
        block = ""
        try:
            block = (await page.evaluate(_JD_BLOCK_JS) or "").strip()
        except Exception:
            block = ""
        if len(block) < 80:
            try:
                block = await page.inner_text("body")
            except Exception:
                block = ""
        return self._clean_jd_text(f"{title}\n{block}")[:5000]

    async def fetch_jd_texts(
        self,
        urls: List[str],
        concurrency: int = 5,
        settle_seconds: float = 2.5,
    ) -> Dict[str, str]:
        """
        批量抓取 JD：复用同一个浏览器实例 + 真实指纹上下文。

        - SPA 页面等待 networkidle，正文过短自动滚动重试一次；
        - 被 Cloudflare/登录墙拦截的页面返回空串并记录，由调用方用标题兜底；
        - 失败返回空串（而不是错误提示字符串），交由调用方用职位标题兜底；
        - 可见浏览器下并发被压到 visible_concurrency：原来固定 5 个标签页同时
          开着，窗口会不停切焦点/重载，用户手动登录时看到的就是「网页疯狂闪烁」；
        - HITL 暂停期间所有页面先 `wait_until_resumed()` 停住，并且暂停结束后
          优先复用用户刚登录好的那个页面，不再无条件 goto 重载（重载会把
          用户正在进行的登录打断，也会让页面继续闪）。

        Args:
            urls: 待抓取的职位页 URL
            concurrency: 并发页面数上限
            settle_seconds: 每页等待渲染的时间
        """
        results: Dict[str, str] = {u: "" for u in urls}
        if not urls:
            return results

        eff_concurrency = max(1, int(concurrency))
        if not self.config.headless:
            eff_concurrency = max(1, min(eff_concurrency, self.config.visible_concurrency))
        sem = asyncio.Semaphore(eff_concurrency)
        self.logger.info(
            f"开始抓取 {len(urls)} 个 JD（并发 {eff_concurrency}"
            f"{'，可见浏览器已自动收敛并发以避免页面闪烁' if not self.config.headless else ''}）"
        )

        try:
            async with async_playwright() as p:
                context, browser = await self._launch_browser(p)
                try:

                    async def fetch_one(url: str):
                        async with sem:
                            page = None
                            try:
                                # 有人在浏览器里手动处理登录/验证时，先别开新页
                                await self.block_handler.wait_until_resumed()
                                page = await context.new_page()
                                text, blocked = await self._render_job_page(
                                    page, url, settle_seconds
                                )
                                # 遇登录墙 / 验证码：停下汇报给用户处理，再重试一次
                                if not text and blocked:
                                    async with self._block_lock:
                                        ok = await self.block_handler.handle(
                                            blocked, url,
                                            detail="职位详情页需要登录/出现验证，"
                                                   "请手动处理后继续",
                                        )
                                    if ok:
                                        await self.block_handler.wait_until_resumed()
                                        # 用户可能已经在同一个标签页里登录并跳转，
                                        # 先就地取一次内容；只有这里确实还是拦截页
                                        # 才重新渲染（避免无条件 goto 造成重载风暴）
                                        text, blocked = await self._reuse_page_text(page)
                                        if not text:
                                            try:
                                                text, blocked = await self._render_job_page(
                                                    page, url, settle_seconds + 2
                                                )
                                            except Exception:
                                                text = ""
                                # 兜底：加长等待再渲染一次（只在确实没拿到正文时）
                                if not text and not blocked:
                                    try:
                                        text, blocked = await self._render_job_page(
                                            page, url, settle_seconds + 2
                                        )
                                    except Exception:
                                        text = ""
                                if text:
                                    self.logger.info(f"成功抓取 JD: {url}（{len(text)} 字）")
                                return url, text
                            except Exception as e:
                                self.logger.warning(f"抓取 JD 失败: {url}, 错误: {e}")
                                return url, ""
                            finally:
                                if page:
                                    try:
                                        await page.close()
                                    except Exception:
                                        pass

                    for url, text in await asyncio.gather(
                        *(fetch_one(u) for u in urls)
                    ):
                        results[url] = text
                finally:
                    await context.close()
                    if browser is not None:
                        await browser.close()

        except Exception as e:
            self.logger.error(f"批量抓取 JD 失败: {e}")

        return results

    async def _reuse_page_text(self, page) -> tuple:
        """
        就地读取「用户刚处理过」的那个页面：拿到正文就直接用，不再 goto 重载。

        返回 (text, blocked)，语义与 _render_job_page 一致。
        """
        try:
            await self.block_handler.wait_until_resumed()
            text = await self._extract_page_text(page)
            blocked = await self._is_blocked_page(text, page)
            if text and not blocked and len(text) >= 200:
                return text, ""
            return "", blocked
        except Exception:
            return "", ""

    def _clean_jd_text(self, text: str) -> str:
        """
        清理 JD 文本。

        注意顺序：先按【行】处理再压缩空白。之前是先 `re.sub(r'\\s+',' ')`
        把整个页面压成一行，再去按行找「职位描述」段落——所有按行的过滤逻辑
        全部失效，导航噪声也永远清不掉。
        """
        text = re.sub(r'<[^>]+>', '', text or "")  # 移除 HTML 标签

        # 移除常见的非招聘内容
        skip_patterns = [
            r'\b社交媒体\b', r'\b社交媒体登录\b', r'\b扫码\b', r'\b下载\b',
            r'\b招聘官登录\b', r'\b创建账户\b', r'\b忘记密码\b',
            r'\b相关搜索\b', r'\b你可能还想搜索\b'
        ]
        for pattern in skip_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        lines = [re.sub(r'[ \t\u3000]+', ' ', ln).strip() for ln in text.split('\n')]
        lines = [ln for ln in lines if ln]

        # 命中 JD 关键词时，从第一个关键词所在行开始取，丢掉前面的导航/筛选噪声
        start = next(
            (i for i, ln in enumerate(lines)
             if any(k in ln.lower() for k in _JD_START_KEYS)),
            None,
        )
        if start:
            lines = lines[start:]

        kept = [ln for ln in lines if len(ln) >= 8]
        return "\n".join(kept or lines).strip()

    async def evaluate_match(self, resume: ResumeSchema, jd_text: str) -> MatchResultSchema:
        """
        评估简历与 JD 的匹配度

        Args:
            resume: 简历数据
            jd_text: JD 文本

        Returns:
            MatchResultSchema: 匹配结果
        """
        try:
            if not jd_text or len(jd_text.strip()) < 20:
                return MatchResultSchema(
                    score=0,
                    is_match=False,
                    reasons=["JD 文本无效或太短"],
                    missing_skills=["无法解析 JD"],
                    matched_skills=[],
                    match_summary="无法分析 JD 文本"
                )

            # 构建评估提示
            evaluation_prompt = self._build_evaluation_prompt(resume, jd_text)

            # 使用 LLM 进行评估
            result = await self._llm_evaluate(evaluation_prompt)
            if result is None:
                return MatchResultSchema(
                    score=0,
                    is_match=False,
                    reasons=["LLM 未返回评估结果（调用失败）"],
                    missing_skills=[],
                    matched_skills=[],
                    match_summary="评估失败：LLM 调用异常，请检查 API Key/网络",
                )

            # 解析结果
            return self._parse_evaluation_result(result, resume)

        except Exception as e:
            self.logger.error(f"匹配评估失败: {e}")
            return MatchResultSchema(
                score=0,
                is_match=False,
                reasons=["评估过程中发生错误"],
                missing_skills=["评估失败"],
                matched_skills=[],
                match_summary=f"评估错误: {str(e)}"
            )

    def _build_evaluation_prompt(self, resume: ResumeSchema, jd_text: str) -> str:
        """构建 LLM 评估提示"""
        # 构建简历概要
        resume_summary = f"""
        姓名: {resume.name}
        邮箱: {resume.email}
        电话: {resume.phone or '未提供'}

        个人简介: {resume.summary}

        技能列表: {', '.join(resume.skills)}

        工作经历:
        {self._format_work_experience(resume.work_experience)}

        教育背景:
        {self._format_education(resume.education)}
        """

        prompt = f"""
        请仔细分析以下求职者简历和职位描述，评估匹配度。

        简历信息:
        {resume_summary}

        职位描述:
        {jd_text}

        请按照以下格式返回 JSON 结果:
        {{
            "score": 0-100的匹配分数,
            "is_match": 是否匹配（布尔值）,
            "reasons": ["匹配原因1", "匹配原因2"],
            "matched_skills": ["已匹配的技能1", "已匹配的技能2"],
            "missing_skills": ["缺少的技能1", "缺少的技能2"],
            "match_summary": "匹配总结（100字以内）"
        }}

        评估标准:
        1. 技能匹配度（40%）: 简历技能是否满足职位要求
        2. 工作经验（30%）: 相关工作经验是否充足
        3. 教育背景（20%）: 学历是否符合要求
        4. 其他因素（10%）: 公司文化契合度、地理位置等

        匹配标准:
        - 分数 >= 80: 强烈推荐
        - 分数 >= 60: 基本匹配
        - 分数 >= 40: 勉强匹配
        - 分数 < 40: 不匹配
        """

        return prompt

    async def _llm_evaluate(self, prompt: str) -> str:
        """使用 LLM 进行评估；调用失败返回 None（由调用方给出明确失败原因）"""
        try:
            if not self.config.llm_client:
                self.logger.error("未配置 LLM 客户端（OPENAI_API_KEY/base_url），无法评估")
                return None
            response = await self.config.llm_client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000
            )
            content = response.choices[0].message.content
            if not content or not str(content).strip():
                self.logger.error("LLM 返回空内容")
                return None
            return content
        except Exception as e:
            self.logger.error(f"LLM 调用失败: {e}")
            return None

    def _parse_evaluation_result(self, llm_result: str, resume: ResumeSchema) -> MatchResultSchema:
        """解析 LLM 评估结果"""
        try:
            import json

            if not isinstance(llm_result, str):
                raise ValueError(f"LLM 返回类型异常: {type(llm_result).__name__}")
            # 提取 JSON 部分
            json_start = llm_result.find('{')
            json_end = llm_result.rfind('}') + 1
            if json_start < 0 or json_end <= json_start:
                raise ValueError(f"LLM 未返回 JSON: {llm_result[:80]!r}")
            json_str = llm_result[json_start:json_end]

            result_data = json.loads(json_str)

            return MatchResultSchema(
                score=result_data.get('score', 0),
                is_match=result_data.get('is_match', False),
                reasons=result_data.get('reasons', []),
                matched_skills=result_data.get('matched_skills', []),
                missing_skills=result_data.get('missing_skills', []),
                match_summary=result_data.get('match_summary', '')
            )

        except Exception as e:
            # 如果 JSON 解析失败，返回默认结果
            self.logger.warning(f"LLM 结果解析失败: {e}")
            return MatchResultSchema(
                score=0,
                is_match=False,
                reasons=["LLM 结果解析失败"],
                missing_skills=[],
                matched_skills=[],
                match_summary=f"解析错误: {str(e)}"
            )

    def _format_work_experience(self, work_experience: List) -> str:
        """格式化工作经历"""
        formatted = ""
        for exp in work_experience:
            formatted += f"- {exp.company} - {exp.position} ({exp.start_date} - {exp.end_date or '至今'})\n"
            formatted += f"  描述: {exp.description}\n"
        return formatted

    def _format_education(self, education: List) -> str:
        """格式化教育背景"""
        formatted = ""
        for edu in education:
            formatted += f"- {edu.school} - {edu.major} ({edu.degree.value}) ({edu.start_date} - {edu.end_date})\n"
        return formatted


async def test_job_matcher():
    """测试函数"""
    config = JobMatcherConfig()
    matcher = JobMatcher(config)

    # 创建测试简历
    from src.models.schemas import ResumeSchema, WorkExperience, Education, ProjectExperience

    resume = ResumeSchema(
        name="张三",
        email="zhangsan@example.com",
        phone="13800138000",
        summary="3年前端开发经验，熟练使用React和TypeScript",
        skills=["React", "TypeScript", "JavaScript", "CSS", "HTML"],
        work_experience=[
            WorkExperience(
                company="ABC科技有限公司",
                position="前端工程师",
                start_date="2021-01",
                end_date="2023-12",
                description="负责公司核心产品的前端开发"
            )
        ],
        education=[
            Education(
                school="北京大学",
                major="计算机科学与技术",
                degree="本科",
                start_date="2017-09",
                end_date="2021-06"
            )
        ],
        projects=[
            ProjectExperience(
                name="电商平台重构",
                description="使用React重构公司电商平台",
                technologies=["React", "Node.js", "MongoDB"],
                role="技术负责人",
                duration="6个月"
            )
        ]
    )

    # 测试 JD 抓取
    test_url = "https://boards.greenhouse.io/autotest/jobs/123456"
    print(f"正在抓取 JD: {test_url}")
    jd_text = await matcher.fetch_jd_text(test_url)
    print(f"JD 文本长度: {len(jd_text)} 字符")

    # 测试匹配评估
    if jd_text and len(jd_text) > 100:
        print("\n开始匹配评估...")
        result = await matcher.evaluate_match(resume, jd_text)

        print(f"\n匹配结果:")
        print(f"匹配分数: {result.score}/100")
        print(f"是否匹配: {result.is_match}")
        print(f"匹配总结: {result.match_summary}")

        if result.matched_skills:
            print(f"\n已匹配的技能:")
            for skill in result.matched_skills:
                print(f"  - {skill}")

        if result.missing_skills:
            print(f"\n缺少的技能:")
            for skill in result.missing_skills:
                print(f"  - {skill}")


if __name__ == "__main__":
    asyncio.run(test_job_matcher())