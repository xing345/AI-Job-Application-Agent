"""
BrowserJobFinder - 基于真实浏览器的职位发现器

与 JobFinder（Tavily 限定海外 ATS 域名）互补：
1. 用 Tavily 做宽泛的门户发现（不限制域名，覆盖国内招聘平台与公司招聘页）
2. 用 Playwright 真实打开每个候选招聘页（渲染 JS）
3. 从渲染后的 DOM 中确定性地抽取职位详情链接（相对路径自动转绝对路径）
4. 仅当抽取结果过少且页面确有验证码/登录墙时才按 AGENTS.md 暂停，
   交互模式下等用户处理后重试一次

输出统一为职位字典列表：
    {url, title, company, location, description, source: "browser"}
供 SearchPipeline 的后续「抓 JD -> LLM 匹配 -> 排序」阶段消费。
"""

import asyncio
import re
import sys
import os
from typing import Dict, List, Optional
from urllib.parse import urlparse

from loguru import logger
from tavily import TavilyClient

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from src.models.instruction_schemas import TargetInstructionSchema

# 招聘/职位详情页的 URL 特征（国内外常见招聘平台 + 海外 ATS）
JOB_URL_HINTS = [
    # 国内平台
    "zhaopin.com", "bosszhipin.com", "zhipin.com", "liepin.com", "lagou.com",
    "51job.com", "jobs.51job", "zhipin", "/job_", "/jobs/", "/job/", "/zp/",
    "jobdetail", "position_detail", "/position/", "/a/",
    # 海外 ATS / 公司招聘站
    "greenhouse.io", "lever.co", "myworkdayjobs.com", "ashbyhq.com",
    "recruitee.com", "smartrecruiters.com", "/career", "/careers", "/vacanc",
    "/recruit", "/join", "/hiring",
]

# 非职位页面（新闻、博客、帮助等），命中则跳过
NON_JOB_HINTS = [
    "blog", "news", "/about", "privacy", "terms", "legal", "contact",
    "support", "help", "press", "investor", "register", "download",
]

# 真正的验证墙特征（只保留硬信号；"请登录/登录后查看"常出现在正常页面页眉，会误判）
CAPTCHA_HINTS = [
    "验证码", "安全验证", "滑动验证", "人机验证", "网络不给力", "访问验证",
    "行为验证", "captcha", "are you a robot", "security check",
    "verify you are human", "access denied", "unusual traffic",
]

# 职位名里常见的通用词（用于中文岗位名切分匹配）
ROLE_GENERIC_TOKENS = [
    "工程师", "开发", "设计师", "产品", "运营", "经理", "架构师", "分析师",
    "研究员", "实习", "校招", "专家", "负责人", "总监",
]

# 浏览器内执行：抽取全部带 href 的锚点（浏览器自动把相对路径解析为绝对 URL）
_ANCHOR_JS = """els => els.map(e => ({
    text: (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim(),
    href: e.href || ''
})).filter(a => a.href && a.text)"""


class BrowserJobFinder:
    """真实浏览器职位发现器"""

    def __init__(
        self,
        tavily_api_key: str,
        headless: bool = True,
        timeout_ms: int = 30000,
        max_sites: int = 6,
        max_jobs_per_site: int = 10,
        interactive: bool = True,
        page_settle_ms: int = 2000,
    ):
        """
        Args:
            tavily_api_key: Tavily API Key（用于门户发现）
            headless: 是否无头浏览器（交互观察/人工过验证码时建议 False）
            timeout_ms: 页面操作超时（毫秒）
            max_sites: 单次最多打开几个候选招聘站
            max_jobs_per_site: 每个站点最多抽取多少个职位链接
            interactive: 交互模式（遇到真实验证墙时在终端暂停等用户处理）
            page_settle_ms: 页面渲染等待时间（毫秒）
        """
        self.api_key = tavily_api_key or ""
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.max_sites = max_sites
        self.max_jobs_per_site = max_jobs_per_site
        self.interactive = interactive
        self.page_settle_ms = page_settle_ms

        self._client: Optional[TavilyClient] = None
        self._playwright = None
        self._browser = None
        self._context = None

    # ------------------------------------------------------------------ #
    # 对外主入口
    # ------------------------------------------------------------------ #
    async def discover(self, target_info: TargetInstructionSchema) -> List[Dict]:
        """
        根据目标岗位指令，用真实浏览器发现职位详情链接。

        Returns:
            职位字典列表 [{url, title, company, location, description, source}]
        """
        candidates = await self._discover_portal_candidates(target_info)
        if not candidates:
            logger.warning("浏览器找岗：Tavily 未发现任何候选招聘门户")
            return []

        logger.info(f"浏览器找岗：发现 {len(candidates)} 个候选门户，开始用浏览器逐个打开")
        jobs: List[Dict] = []
        seen_urls = set()
        total_cap = self.max_sites * self.max_jobs_per_site

        try:
            await self._start_browser()
            for portal in candidates[: self.max_sites]:
                site_jobs = await self._extract_jobs_from_portal(portal, target_info)
                for job in site_jobs:
                    if job["url"] in seen_urls:
                        continue
                    seen_urls.add(job["url"])
                    jobs.append(job)
                if len(jobs) >= total_cap:
                    logger.info(f"已达单次上限 {total_cap}，停止打开更多门户")
                    break
                # 礼貌延迟，降低被封概率
                await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"浏览器找岗过程异常: {e}")
        finally:
            await self._stop_browser()

        logger.info(f"浏览器找岗完成，共抽取 {len(jobs)} 个职位链接")
        return jobs

    # ------------------------------------------------------------------ #
    # 阶段 1：Tavily 宽泛发现候选招聘门户
    # ------------------------------------------------------------------ #
    def _build_portal_queries(self, target_info: TargetInstructionSchema) -> List[str]:
        role = (target_info.role or "").strip()
        location = (target_info.location or "").strip()
        queries = []

        # 中文招聘查询（覆盖国内平台与公司招聘页）
        zh = f"{role} {location} 招聘".strip()
        if target_info.keywords:
            zh += " " + " ".join(target_info.keywords[:4])
        queries.append(zh)

        # 英文/外企招聘查询
        en = f"{role} jobs careers hiring"
        if location:
            en += f" {location}"
        queries.append(en)

        # 指定了公司时补一条公司维度的查询
        company = (target_info.company or "").strip()
        if company:
            queries.append(f"{company} 招聘 职位 {role}")
        return queries

    async def _discover_portal_candidates(self, target_info: TargetInstructionSchema) -> List[Dict]:
        """用 Tavily 发现候选招聘门户（不做域名白名单限制）"""
        if not self.api_key:
            logger.warning("未配置 TAVILY_API_KEY，浏览器找岗无法发现候选门户")
            return []

        candidates: Dict[str, Dict] = {}
        for query in self._build_portal_queries(target_info):
            try:
                resp = await asyncio.to_thread(
                    self._get_client().search,
                    query=query,
                    search_depth="basic",
                    max_results=10,
                    include_answer=False,
                    include_raw_content=False,
                )
            except Exception as e:
                logger.warning(f"Tavily 门户发现失败 (query={query}): {e}")
                continue

            for item in (resp or {}).get("results", []):
                url = item.get("url", "")
                if not url or url in candidates:
                    continue
                if self._looks_non_job(url):
                    continue
                title = item.get("title", "") or ""
                snippet = item.get("content", "") or item.get("snippet", "") or ""
                # 门户相关性：URL 命中招聘特征，或标题/摘要含招聘词
                if self._looks_job_portal(url, title, snippet):
                    candidates[url] = {
                        "url": url,
                        "title": title,
                        "snippet": snippet[:300],
                    }

        ordered = sorted(
            candidates.values(),
            key=lambda c: self._portal_score(c["url"], c["title"]),
            reverse=True,
        )
        return ordered

    def _get_client(self) -> TavilyClient:
        if self._client is None:
            self._client = TavilyClient(api_key=self.api_key)
        return self._client

    # ------------------------------------------------------------------ #
    # 阶段 2：浏览器打开门户，DOM 确定性抽取职位链接
    # ------------------------------------------------------------------ #
    async def _start_browser(self):
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            viewport={"width": 1366, "height": 800},
            locale="zh-CN",
        )
        logger.info(f"职位发现浏览器已启动 (headless={self.headless})")

    async def _stop_browser(self):
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"关闭职位发现浏览器时出错: {e}")
        finally:
            self._context = None
            self._browser = None
            self._playwright = None

    async def _collect_anchors(self, page) -> List[Dict]:
        """抽取页面上全部锚点（绝对 URL + 可见文本）"""
        try:
            return await page.eval_on_selector_all("a[href]", _ANCHOR_JS)
        except Exception as e:
            logger.warning(f"锚点抽取失败: {e}")
            return []

    async def _extract_jobs_from_portal(self, portal: Dict, target_info) -> List[Dict]:
        """打开单个招聘门户，抽取职位详情链接"""
        url = portal["url"]
        page = None
        try:
            page = await self._context.new_page()
            page.set_default_timeout(self.timeout_ms)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            except Exception as e:
                logger.warning(f"门户打开失败 {url}: {e}")
                return []

            # 等待 JS 渲染并滚动触发懒加载
            await self._settle_page(page)

            role_tokens = self._role_tokens(target_info)
            scored = await self._score_anchors(page, role_tokens)

            # 结果过少且页面确有验证墙时，人工介入后重试一次
            if len(scored) < 3 and self._has_captcha_or_wall(await self._safe_inner_text(page)):
                await self._handle_block(url, page)
                await self._settle_page(page)
                scored = await self._score_anchors(page, role_tokens)

            jobs = []
            seen = set()
            for score, a in scored[: self.max_jobs_per_site * 3]:
                if a["href"] in seen or self._looks_non_job(a["href"]):
                    continue
                seen.add(a["href"])
                jobs.append({
                    "url": a["href"],
                    "title": a["text"][:80],
                    "company": self._guess_company(portal["title"], a["href"]),
                    "location": target_info.location or "",
                    "description": portal.get("snippet", ""),
                    "source": "browser",
                })
                if len(jobs) >= self.max_jobs_per_site:
                    break

            logger.info(f"门户 {url} 抽取到 {len(jobs)} 个职位链接")
            return jobs

        except Exception as e:
            logger.warning(f"门户职位抽取失败 {url}: {e}")
            return []
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    async def _score_anchors(self, page, role_tokens: List[str]) -> List:
        """抽取锚点并评分排序，返回 [(score, anchor)] 降序"""
        anchors = await self._collect_anchors(page)
        scored = []
        for a in anchors:
            score = self._score_anchor(a["text"], a["href"], role_tokens)
            if score > 0:
                scored.append((score, a))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    async def _settle_page(self, page):
        """等待页面渲染完成并滚动加载"""
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(self.page_settle_ms / 1000)
        # 滚动两屏，触发懒加载职位列表
        for _ in range(2):
            try:
                await page.mouse.wheel(0, 1200)
                await asyncio.sleep(0.6)
            except Exception:
                break

    async def _safe_inner_text(self, page) -> str:
        try:
            return await page.inner_text("body")
        except Exception:
            return ""

    async def _handle_block(self, url: str, page):
        """遇到真实验证墙：按 AGENTS.md 暂停，交互模式等用户人工处理"""
        msg = f"⚠️ {url} 出现验证码/登录墙"
        if self.headless:
            logger.warning(f"{msg}（无头模式无法人工介入，跳过该站）")
            return
        if not self.interactive:
            logger.warning(f"{msg}（非交互模式，跳过该站）")
            return
        print(f"\n{msg}，请在弹出的浏览器窗口中完成验证/登录，然后回到终端按回车继续...")
        try:
            await asyncio.to_thread(input, "处理完成后按回车继续 > ")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 评分 / 匹配工具
    # ------------------------------------------------------------------ #
    def _role_tokens(self, target_info: TargetInstructionSchema) -> List[str]:
        """从目标岗位 + 关键词中拆出用于匹配的 token"""
        raw = target_info.role or ""
        tokens = set()
        # 英文单词 / AI Agent 这类短语
        for m in re.findall(r"[A-Za-z][A-Za-z+#.\-]{1,}", raw):
            if len(m) >= 2:
                tokens.add(m.lower())
        # 中文按 2-gram 切分，并保留通用岗位词
        zh = re.sub(r"[A-Za-z\s]+", " ", raw)
        for word in ROLE_GENERIC_TOKENS:
            if word in zh:
                tokens.add(word)
        for i in range(len(zh) - 1):
            gram = zh[i:i + 2].strip()
            if len(gram) == 2 and not re.search(r"[\s，,、/（）()]", gram):
                tokens.add(gram)
        for kw in (target_info.keywords or [])[:8]:
            for m in re.findall(r"[A-Za-z][A-Za-z+#.\-]{1,}", kw):
                tokens.add(m.lower())
        return [t for t in tokens if t]

    def _score_anchor(self, text: str, href: str, role_tokens: List[str]) -> int:
        """给单个锚点评分，>0 才认为是职位链接"""
        t = text.lower()
        h = href.lower()
        if len(text) < 2 or len(text) > 80:
            return 0
        score = 0
        # URL 像职位详情页
        if any(hint in h for hint in JOB_URL_HINTS):
            score += 3
        # 文本像职位名（含通用岗位词）
        if any(tok in t for tok in ["工程师", "开发", "设计师", "产品经理", "运营",
                                    "架构师", "分析师", "研究员", "实习", "engineer",
                                    "developer", "designer", "manager"]):
            score += 3
        # 命中目标岗位 token
        hit_tokens = [tok for tok in role_tokens if tok in t]
        score += 2 * len(hit_tokens)
        if score == 0:
            return 0
        # 排除项
        if self._looks_non_job(href) or any(x in t for x in ["登录", "注册", "下载", "帮助"]):
            return 0
        return score

    def _looks_job_portal(self, url: str, title: str, snippet: str) -> bool:
        blob = f"{url} {title} {snippet}".lower()
        if self._looks_non_job(url):
            return False
        portal_words = [
            "招聘", "职位", "岗位", "招人", "校招", "社招", "人才",
            "career", "job", "hire", "hiring", "vacancy", "position", "talent",
        ]
        return any(w in blob for w in portal_words)

    def _looks_non_job(self, url: str) -> bool:
        u = url.lower()
        return any(hint in u for hint in NON_JOB_HINTS)

    def _portal_score(self, url: str, title: str) -> int:
        """门户排序：垂直招聘平台/ATS 优先"""
        u = (url or "").lower()
        t = (title or "").lower()
        score = 0
        priority_domains = [
            "zhaopin.com", "liepin.com", "lagou.com", "51job.com", "zhipin.com",
            "greenhouse.io", "lever.co", "myworkdayjobs.com", "ashbyhq.com",
            "recruitee.com", "smartrecruiters.com", "linkedin.com",
        ]
        for i, d in enumerate(priority_domains):
            if d in u:
                score += 20 - i
        if any(w in t for w in ["招聘", "职位", "career", "job"]):
            score += 2
        return score

    def _guess_company(self, portal_title: str, href: str) -> str:
        """从门户标题粗略推断公司名（无法确定时返回空串）"""
        title = (portal_title or "").strip()
        title = re.split(r"[-_|–—]", title)[0].strip()
        host = urlparse(href).netloc
        platform_hosts = ["zhaopin.com", "liepin.com", "lagou.com", "51job.com",
                          "zhipin.com", "linkedin.com", "greenhouse.io", "lever.co",
                          "myworkdayjobs.com", "ashbyhq.com", "recruitee.com"]
        if any(p in host for p in platform_hosts):
            return title
        return title

    def _has_captcha_or_wall(self, body_text: str) -> bool:
        b = (body_text or "").lower()
        return any(hint.lower() in b for hint in CAPTCHA_HINTS)
