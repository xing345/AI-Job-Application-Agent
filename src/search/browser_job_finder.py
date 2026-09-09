"""
BrowserJobFinder - 基于真实浏览器的职位发现器

提供两条找岗通道：
A. 门户通道 discover()：Tavily 宽泛发现招聘聚合页 -> 浏览器打开 -> DOM 抽取职位链接
B. 公司官网通道 discover_company_careers()：
   1. 发现目标公司（Tavily 发现或用户指定公司名单，排除聚合招聘平台）
   2. 进入公司官网，确定性地定位「招聘/加入我们/Careers/Jobs」页面
      （首页锚点评分 + 常见路径探测 + jobs./career./hr. 子域探测）
   3. 在公司招聘站内按目标岗位抽取职位详情链接（必要时使用站内搜索框）
   4. 仅当抽取结果过少且确有验证码/登录墙时按 AGENTS.md 暂停，
      交互模式等用户处理后重试一次

输出统一为职位字典列表：
    {url, title, company, location, description, source, channel}
供 SearchPipeline 的后续「抓 JD -> LLM 匹配 -> 排序」阶段消费。
"""

import asyncio
import re
import sys
import os
from typing import Dict, List, Optional
from urllib.parse import urlparse, urljoin

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

# 招聘聚合平台/内容站：公司通道发现公司时排除这些域名
AGGREGATOR_DOMAINS = [
    "liepin.com", "zhaopin.com", "bosszhipin.com", "zhipin.com", "51job.com",
    "lagou.com", "kanzhun.com", "maimai.cn", "linkedin.com", "zhihu.com",
    "baidu.com", "bing.com", "google.", "csdn.net", "jianshu.com", "sspai.com",
    "weibo.com", "bilibili.com", "tianyancha.com", "qcc.com", "qixin.com",
    "163.com", "sohu.com", "sina.com", "qq.com", "mp.weixin", "douyin.com",
    "github.com", "gitee.com", "baike", "wiki", "toutiao.com",
]

# 公司官网上「招聘入口」的文案/路径特征
CAREER_TEXT_HINTS = [
    "招聘", "加入我们", "人才招聘", "社会招聘", "校园招聘", "招贤纳士",
    "人力资源", "careers", "career", "jobs", "join us", "join-us", "joinus",
    "work with us", "hiring", "talent", "vacancies", "employment", "people",
]
CAREER_URL_HINTS = [
    "/career", "/jobs", "/join", "/recruit", "/zhaopin", "/hr", "/talent",
    "/hiring", "/vacanc", "/campus", "/xiaozhao", "/social",
]
# 招聘页常见直接路径
CAREER_PROBE_PATHS = [
    "/careers", "/career", "/jobs", "/joinus", "/join-us", "/join",
    "/about/careers", "/about/jobs", "/zh/careers", "/cn/careers",
    "/recruit", "/social", "/zhaopin",
]
# 招聘页常见子域前缀
CAREER_SUBDOMAIN_PREFIXES = [
    "jobs.", "job.", "career.", "careers.", "hr.", "campus.", "hire.",
    "xiaozhao.", "zhaopin.", "talent.",
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
    """真实浏览器职位发现器（门户通道 + 公司官网通道）"""

    def __init__(
        self,
        tavily_api_key: str,
        headless: bool = True,
        timeout_ms: int = 30000,
        max_sites: int = 6,
        max_jobs_per_site: int = 10,
        max_companies: int = 5,
        interactive: bool = True,
        page_settle_ms: int = 2000,
    ):
        """
        Args:
            tavily_api_key: Tavily API Key（用于门户/公司发现）
            headless: 是否无头浏览器（交互观察/人工过验证码时建议 False）
            timeout_ms: 页面操作超时（毫秒）
            max_sites: 门户通道单次最多打开几个聚合招聘站
            max_jobs_per_site: 每个站点最多抽取多少个职位链接
            max_companies: 公司通道单次最多进入几家公司招聘官网
            interactive: 交互模式（遇到真实验证墙时在终端暂停等用户处理）
            page_settle_ms: 页面渲染等待时间（毫秒）
        """
        self.api_key = tavily_api_key or ""
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.max_sites = max_sites
        self.max_jobs_per_site = max_jobs_per_site
        self.max_companies = max_companies
        self.interactive = interactive
        self.page_settle_ms = page_settle_ms

        self._client: Optional[TavilyClient] = None
        self._playwright = None
        self._browser = None
        self._context = None

    # ================================================================== #
    # 通道 A：招聘聚合门户
    # ================================================================== #
    async def discover(self, target_info: TargetInstructionSchema) -> List[Dict]:
        """
        门户通道：根据目标岗位指令，用真实浏览器从招聘聚合站发现职位链接。

        Returns:
            职位字典列表 [{url, title, company, location, description, source}]
        """
        candidates = await self._discover_portal_candidates(target_info)
        if not candidates:
            logger.warning("门户通道：Tavily 未发现任何候选招聘门户")
            return []

        logger.info(f"门户通道：发现 {len(candidates)} 个候选门户，开始用浏览器逐个打开")
        jobs: List[Dict] = []
        seen_urls = set()
        total_cap = self.max_sites * self.max_jobs_per_site

        try:
            await self._start_browser()
            for portal in candidates[: self.max_sites]:
                site_jobs = await self._extract_jobs_from_portal(portal, target_info)
                for job in site_jobs:
                    job["channel"] = "job_portal"
                    if job["url"] in seen_urls:
                        continue
                    seen_urls.add(job["url"])
                    jobs.append(job)
                if len(jobs) >= total_cap:
                    logger.info(f"已达门户通道上限 {total_cap}，停止打开更多门户")
                    break
                await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"门户通道过程异常: {e}")
        finally:
            await self._stop_browser()

        logger.info(f"门户通道完成，共抽取 {len(jobs)} 个职位链接")
        return jobs

    # ================================================================== #
    # 通道 B：公司自有招聘官网
    # ================================================================== #
    async def discover_company_careers(
        self,
        target_info: TargetInstructionSchema,
        known_companies: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        公司官网通道：发现公司 -> 进入官网定位招聘页 -> 站内抽取目标岗位。

        Args:
            target_info: 目标岗位指令
            known_companies: 用户指定的公司名/官网 URL 列表；为空时按岗位自动发现

        Returns:
            职位字典列表
        """
        companies = await self._discover_company_candidates(target_info, known_companies)
        if not companies:
            logger.warning("公司通道：未发现可进入的公司官网")
            return []

        logger.info(f"公司通道：候选公司 {len(companies)} 家，开始进入各自招聘官网")
        jobs: List[Dict] = []
        seen_urls = set()

        try:
            await self._start_browser()
            for company in companies[: self.max_companies]:
                name = company["name"]
                try:
                    career_url = company.get("career_url")
                    if not career_url:
                        career_url = await self._locate_career_page(company["url"])
                    if not career_url:
                        logger.info(f"公司通道：{name} 未找到招聘页，跳过")
                        continue

                    logger.info(f"公司通道：进入 {name} 招聘页 {career_url}")
                    site_jobs = await self._extract_jobs_from_portal(
                        {"url": career_url, "title": name, "snippet": ""},
                        target_info,
                    )
                    for job in site_jobs:
                        job["company"] = name
                        job["channel"] = "company_site"
                        if job["url"] in seen_urls:
                            continue
                        seen_urls.add(job["url"])
                        jobs.append(job)
                    logger.info(f"公司通道：{name} 抽取到 {len(site_jobs)} 个职位")
                except Exception as e:
                    logger.warning(f"公司通道：处理 {name} 失败: {e}")
                    continue
                finally:
                    await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"公司通道过程异常: {e}")
        finally:
            await self._stop_browser()

        logger.info(f"公司通道完成，共抽取 {len(jobs)} 个职位链接")
        return jobs

    async def _discover_company_candidates(
        self,
        target_info: TargetInstructionSchema,
        known_companies: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        发现公司候选：优先用户指定名单（名称自动找官网），否则按岗位 Tavily 发现。
        排除招聘聚合平台，只保留公司自有域名。返回 [{name, url, career_url?}]
        """
        candidates: Dict[str, Dict] = {}

        def add_result(url: str, title: str, force_homepage: bool = False):
            if not url or self._is_aggregator(url):
                return
            host = urlparse(url).netloc.lower().replace("www.", "")
            if not host or host in candidates:
                return
            name = self._clean_company_name(title) or host
            is_career = (not force_homepage) and self._url_has_career_hint(url)
            candidates[host] = {
                "name": name,
                "url": url if is_career else self._homepage_of(url),
                "career_url": url if is_career else None,
            }

        if known_companies:
            # 用户指定：名称 -> Tavily 找官网；本身是 URL 则直接用
            for raw in known_companies:
                raw = (raw or "").strip()
                if not raw:
                    continue
                if raw.startswith("http"):
                    add_result(raw, self._host_of(raw), force_homepage=False)
                    continue
                resp = await self._tavily_search(
                    f"{raw} 官网", max_results=5, exclude=AGGREGATOR_DOMAINS
                )
                for item in resp:
                    if raw.lower() in (item.get("title", "") + item.get("url", "")).lower() \
                            or not self._is_aggregator(item.get("url", "")):
                        add_result(item.get("url", ""), item.get("title", raw))
                        break
        else:
            role = (target_info.role or "").strip()
            location = (target_info.location or "").strip()
            queries = [
                f"{role} {location} 招聘 加入我们 官网".strip(),
                f"{role} careers jobs official company",
            ]
            if target_info.keywords:
                queries[0] += " " + " ".join(target_info.keywords[:3])
            for q in queries:
                for item in await self._tavily_search(
                    q, max_results=10, exclude=AGGREGATOR_DOMAINS
                ):
                    add_result(item.get("url", ""), item.get("title", ""))

        return sorted(candidates.values(), key=lambda c: 0 if c.get("career_url") else 1)

    async def _locate_career_page(self, homepage: str) -> Optional[str]:
        """在公司官网上定位招聘页：先读首页锚点，再探测常见路径/子域"""
        page = None
        try:
            page = await self._context.new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                await page.goto(homepage, wait_until="domcontentloaded", timeout=self.timeout_ms)
            except Exception as e:
                logger.warning(f"公司官网打开失败 {homepage}: {e}")
                return None
            await self._settle_page(page, light=True)

            # 策略 1：首页锚点里找「招聘/加入我们/Careers」
            anchors = await self._collect_anchors(page)
            best = self._best_career_anchor(anchors)
            if best:
                return best

            # 策略 2：常见路径 + 招聘子域直接探测
            return await self._probe_career_urls(homepage, page)
        except Exception as e:
            logger.warning(f"定位招聘页失败 {homepage}: {e}")
            return None
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    def _best_career_anchor(self, anchors: List[Dict]) -> Optional[str]:
        """从首页锚点评出最可能的招聘入口（确定性，不依赖 LLM）"""
        best_href, best_score = None, 0
        for a in anchors:
            text = (a.get("text") or "").lower()
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("javascript:", "mailto:", "#", "tel:")):
                continue
            if len(text) > 20:
                continue
            score = 0
            for hint in CAREER_TEXT_HINTS:
                if hint in text:
                    score += 10
                    break
            low_href = href.lower()
            for hint in CAREER_URL_HINTS:
                if hint in low_href:
                    score += 6
                    break
            # 明确不是招聘的入口降权
            if any(x in low_href for x in ["/news", "/blog", "/product", "/about-us"]):
                score -= 5
            if score > best_score:
                best_score, best_href = score, href
        return best_href if best_score >= 10 else None

    async def _probe_career_urls(self, homepage: str, page) -> Optional[str]:
        """探测常见招聘路径与招聘子域，返回第一个内容像招聘页的 URL"""
        parsed = urlparse(homepage)
        host = parsed.netloc.lower().replace("www.", "")
        if not host:
            return None
        scheme = parsed.scheme or "https"

        candidates: List[str] = []
        base = f"{scheme}://{parsed.netloc}"
        for path in CAREER_PROBE_PATHS:
            candidates.append(urljoin(base + "/", path.lstrip("/")))
        for prefix in CAREER_SUBDOMAIN_PREFIXES:
            candidates.append(f"{scheme}://{prefix}{host}")

        for url in candidates[:18]:
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=10000)
                if resp and resp.status >= 400:
                    continue
                await asyncio.sleep(0.8)
                anchors = await self._collect_anchors(page)
                text = await self._safe_inner_text(page)
                jobish = sum(
                    1 for a in anchors
                    if self._score_anchor(a.get("text", ""), a.get("href", ""), []) >= 3
                )
                career_words = ["职位", "岗位", "招聘", "career", "job", "apply", "vacancy"]
                word_hit = sum(1 for w in career_words if w in text.lower()[:4000])
                if jobish >= 3 or word_hit >= 3:
                    return page.url
            except Exception:
                continue
        return None

    # ================================================================== #
    # 门户候选发现（Tavily 宽泛查询，不做域名白名单限制）
    # ================================================================== #
    def _build_portal_queries(self, target_info: TargetInstructionSchema) -> List[str]:
        role = (target_info.role or "").strip()
        location = (target_info.location or "").strip()
        queries = []

        zh = f"{role} {location} 招聘".strip()
        if target_info.keywords:
            zh += " " + " ".join(target_info.keywords[:4])
        queries.append(zh)

        en = f"{role} jobs careers hiring"
        if location:
            en += f" {location}"
        queries.append(en)

        company = (target_info.company or "").strip()
        if company:
            queries.append(f"{company} 招聘 职位 {role}")
        return queries

    async def _discover_portal_candidates(self, target_info: TargetInstructionSchema) -> List[Dict]:
        """用 Tavily 发现候选招聘门户（不做域名白名单限制）"""
        if not self.api_key:
            logger.warning("未配置 TAVILY_API_KEY，无法发现候选门户")
            return []

        candidates: Dict[str, Dict] = {}
        for query in self._build_portal_queries(target_info):
            for item in await self._tavily_search(query, max_results=10):
                url = item.get("url", "")
                if not url or url in candidates or self._looks_non_job(url):
                    continue
                title = item.get("title", "") or ""
                snippet = item.get("content", "") or item.get("snippet", "") or ""
                if self._looks_job_portal(url, title, snippet):
                    candidates[url] = {
                        "url": url,
                        "title": title,
                        "snippet": snippet[:300],
                    }

        return sorted(
            candidates.values(),
            key=lambda c: self._portal_score(c["url"], c["title"]),
            reverse=True,
        )

    async def _tavily_search(self, query: str, max_results: int = 10,
                             exclude: Optional[List[str]] = None) -> List[Dict]:
        """Tavily 搜索（同步客户端放到线程，失败返回空列表）"""
        if not self.api_key:
            return []
        kwargs = dict(
            query=query,
            search_depth="basic",
            max_results=max_results,
            include_answer=False,
            include_raw_content=False,
        )
        if exclude:
            kwargs["exclude_domains"] = exclude
        try:
            resp = await asyncio.to_thread(self._get_client().search, **kwargs)
            return (resp or {}).get("results", []) or []
        except Exception as e:
            logger.warning(f"Tavily 搜索失败 (query={query}): {e}")
            return []

    def _get_client(self) -> TavilyClient:
        if self._client is None:
            self._client = TavilyClient(api_key=self.api_key)
        return self._client

    # ================================================================== #
    # 浏览器生命周期与页面抽取
    # ================================================================== #
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
        """打开单个招聘页（聚合门户或公司招聘页），抽取职位详情链接"""
        url = portal["url"]
        page = None
        try:
            page = await self._context.new_page()
            page.set_default_timeout(self.timeout_ms)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            except Exception as e:
                logger.warning(f"招聘页打开失败 {url}: {e}")
                return []

            await self._settle_page(page)

            role_tokens = self._role_tokens(target_info)
            scored = await self._score_anchors(page, role_tokens)

            # 职位过少：先尝试站内搜索框输入岗位，再判断验证墙
            if len(scored) < 3 and await self._try_role_search(page, target_info.role):
                await self._settle_page(page)
                scored = await self._score_anchors(page, role_tokens)

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
                    "company": self._guess_company(portal.get("title", ""), a["href"]),
                    "location": target_info.location or "",
                    "description": portal.get("snippet", ""),
                    "source": "browser",
                })
                if len(jobs) >= self.max_jobs_per_site:
                    break

            logger.info(f"页面 {url} 抽取到 {len(jobs)} 个职位链接")
            return jobs

        except Exception as e:
            logger.warning(f"职位抽取失败 {url}: {e}")
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

    async def _try_role_search(self, page, role: str) -> bool:
        """招聘站带搜索框时，输入目标岗位触发站内检索"""
        if not role:
            return False
        selector = (
            "input[type='search'], input[placeholder*='搜索'], input[placeholder*='岗位'], "
            "input[placeholder*='Search'], input[placeholder*='search'], "
            "input[name*='keyword' i], input[name*='search' i], input[aria-label*='Search' i]"
        )
        try:
            box = await page.query_selector(selector)
            if not box:
                return False
            await box.fill(role[:30])
            await box.press("Enter")
            await asyncio.sleep(2.0)
            logger.info(f"已在站内搜索框输入岗位: {role}")
            return True
        except Exception:
            return False

    async def _settle_page(self, page, light: bool = False):
        """等待页面渲染完成并滚动加载"""
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(1.0 if light else self.page_settle_ms / 1000)
        if light:
            return
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

    # ================================================================== #
    # 评分 / 匹配 / 文本工具
    # ================================================================== #
    def _role_tokens(self, target_info: TargetInstructionSchema) -> List[str]:
        """从目标岗位 + 关键词中拆出用于匹配的 token"""
        raw = target_info.role or ""
        tokens = set()
        for m in re.findall(r"[A-Za-z][A-Za-z+#.\-]{1,}", raw):
            if len(m) >= 2:
                tokens.add(m.lower())
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
        if any(hint in h for hint in JOB_URL_HINTS):
            score += 3
        if any(tok in t for tok in ["工程师", "开发", "设计师", "产品经理", "运营",
                                    "架构师", "分析师", "研究员", "实习", "engineer",
                                    "developer", "designer", "manager"]):
            score += 3
        hit_tokens = [tok for tok in role_tokens if tok in t]
        score += 2 * len(hit_tokens)
        if score == 0:
            return 0
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
        u = (url or "").lower()
        return any(hint in u for hint in NON_JOB_HINTS)

    def _is_aggregator(self, url: str) -> bool:
        u = (url or "").lower()
        return any(d in u for d in AGGREGATOR_DOMAINS)

    def _url_has_career_hint(self, url: str) -> bool:
        u = (url or "").lower()
        return any(h in u for h in CAREER_URL_HINTS)

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

    def _clean_company_name(self, title: str) -> str:
        """从搜索结果标题提取公司名（去掉官网/招聘等后缀噪声）"""
        name = (title or "").strip()
        name = re.split(r"[-_|–—,，|]", name)[0].strip()
        for noise in ["官网", "官方网站", "首页", "招聘", "百度百科", "百科"]:
            name = name.replace(noise, "")
        return name.strip()

    def _homepage_of(self, url: str) -> str:
        """把任意深层 URL 收敛为站点根 URL"""
        p = urlparse(url)
        if not p.scheme or not p.netloc:
            return url
        return f"{p.scheme}://{p.netloc}/"

    def _host_of(self, url: str) -> str:
        return urlparse(url).netloc.replace("www.", "")

    def _has_captcha_or_wall(self, body_text: str) -> bool:
        b = (body_text or "").lower()
        return any(hint.lower() in b for hint in CAPTCHA_HINTS)
