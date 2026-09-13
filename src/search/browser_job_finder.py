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
from src.search.query_expander import query_terms, role_tokens, title_direction_relevance

# 招聘/职位详情页的 URL 特征（国内招聘平台 + 公司自有招聘站）
JOB_URL_HINTS = [
    # 国内平台
    "zhaopin.com", "bosszhipin.com", "zhipin.com", "liepin.com", "lagou.com",
    "51job.com", "jobs.51job", "zhipin", "/job_", "/jobs/", "/job/", "/zp/",
    "jobdetail", "position_detail", "/position/", "/a/",
    # 公司自有招聘站（国内外通用路径，不绑定具体厂商）
    "/career", "/careers", "/vacanc", "/recruit", "/join", "/hiring",
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
    "lagou.com", "kanzhun.com", "maimai.cn", "zhihu.com",
    "baidu.com", "bing.com", "google.", "csdn.net", "jianshu.com", "sspai.com",
    "weibo.com", "bilibili.com", "tianyancha.com", "qcc.com", "qixin.com",
    "163.com", "sohu.com", "sina.com", "qq.com", "mp.weixin", "douyin.com",
    "github.com", "gitee.com", "baike", "wiki", "toutiao.com",
]

# 国内招聘平台（通道1/门户通道的优先级排序用）
CN_JOB_PLATFORMS = [
    "bosszhipin.com", "zhipin.com", "lagou.com", "liepin.com",
    "zhaopin.com", "51job.com",
]

# 应用商店/百科/社媒等非公司官网噪声域名
JUNK_DOMAINS = [
    "play.google.com", "apps.apple.com", "itunes.apple.com", "chrome.google.com",
    "appgallery", "samsungapps.com", "apk", "wikipedia.org", "wikimedia.org",
    "web.archive.org", "youtube.com", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "taobao.com", "jd.com", "amazon.",
    "91wllm", "chaojijianli", "cake.me", "nowcoder.com", "gaoxiaojob",
    "yuanjisong", "reddit.com", "heywhale", "jobui", "segmentfault",
    "juejin.cn", "cnblogs", "offcn", "fenbi", "yingjiesheng",
    "xiaohongshu.com", "douban.com", "tieba.baidu", "cuiqingcai",
    "niuqizp", "niuzhi",
]
# 登录/账号类主机特征（不是招聘页）
LOGIN_HOST_HINTS = ["passport", "login.", "signin", "account.", "id.", "auth."]
# 职位详情链接特征（区别于导航/介绍页）
JOB_DETAIL_RE = re.compile(
    r"(id=|jobid|positionid|postid|/position|/jobdetail|/job/|/jobs/|/detail/|/vacanc)",
    re.I,
)

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

# 职位名通用词与分词逻辑统一由 query_expander 提供（ROLE_GENERIC_TOKENS 已从该模块导入）

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
        max_jobs_per_site: int = 20,
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
                    site_jobs = await self._extract_company_jobs(
                        name, career_url, target_info
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
        排除招聘聚合平台/应用商店/百科，只保留公司自有域名。
        返回 [{name, url, career_url?}]，可直达招聘页的排在前面。
        """
        candidates: Dict[str, Dict] = {}

        def add_result(url: str, title: str, preferred_name: str = "", trusted: bool = False):
            kind = self._classify_company_result(url, trusted=trusted)
            if not kind or (not trusted and self._is_junk_title(title)):
                return
            host = urlparse(url).netloc.lower().replace("www.", "")
            if not host or host in candidates:
                return
            name = preferred_name or self._clean_company_name(title) or host
            if trusted:
                # 用户显式 URL 与前面解析出的同名公司主域一致时，继承友好公司名
                for c in candidates.values():
                    if self._registrable_domain(c.get("url", "")) == self._registrable_domain(url):
                        name = c.get("name") or name
                        break
            candidates[host] = {
                "name": name,
                "url": url if kind == "career" else self._homepage_of(url),
                "career_url": url if kind == "career" else None,
                "trusted": trusted,
            }

        if known_companies:
            # 用户指定：公司名 -> 多查询择优（招聘官网优先于首页）；本身是 URL 直接用
            for raw in known_companies:
                raw = (raw or "").strip()
                if not raw:
                    continue
                if raw.startswith("http"):
                    add_result(raw, self._host_of(raw), preferred_name=self._host_of(raw), trusted=True)
                    continue
                resolved = await self._resolve_named_company(raw)
                if resolved:
                    host = urlparse(resolved["url"]).netloc.lower().replace("www.", "")
                    candidates[host] = resolved
        else:
            location = (target_info.location or "").strip()
            # 每个岗位词各出一条查询，扩大同义岗位的公司召回
            queries = [
                f"{term} {location} 招聘 加入我们 官网".strip()
                for term in query_terms(target_info, limit=2)
            ]
            if target_info.keywords:
                queries = [
                    f"{q} {' '.join(str(k) for k in target_info.keywords[:3])}".strip()
                    for q in queries
                ]
            for q in queries:
                for item in await self._tavily_search(
                    q, max_results=10, exclude=AGGREGATOR_DOMAINS + JUNK_DOMAINS
                ):
                    add_result(item.get("url", ""), item.get("title", ""))

        return sorted(candidates.values(), key=lambda c: 0 if c.get("career_url") else 1)

    async def _resolve_named_company(self, name: str) -> Optional[Dict]:
        """公司名 -> 官网/招聘页：以官网主域为准，优先同域招聘页，否则回退官网首页"""
        homes, careers = [], []
        for q in (f"{name} 招聘官网", f"{name} 官网", f"{name} careers"):
            resp = await self._tavily_search(
                q, max_results=6, exclude=AGGREGATOR_DOMAINS + JUNK_DOMAINS
            )
            for item in resp:
                url, title = item.get("url", ""), item.get("title", "")
                kind = self._classify_company_result(url)
                if not kind or name.lower() not in (title + url).lower():
                    continue
                record = {
                    "name": name,
                    "url": url if kind == "career" else self._homepage_of(url),
                    "career_url": url if kind == "career" else None,
                    "kind": kind, "regdom": self._registrable_domain(url),
                }
                (careers if kind == "career" else homes).append(record)

        if homes:
            home = sorted(homes, key=lambda r: 0 if r["kind"] == "home" else 1)[0]
            same = [c for c in careers if c["regdom"] == home["regdom"]]
            if same:
                c = same[0]
                return {"name": name, "url": c["url"], "career_url": c["career_url"]}
            return {"name": name, "url": home["url"], "career_url": None}
        if careers:
            c = careers[0]
            return {"name": name, "url": c["url"], "career_url": c["career_url"]}
        return None

    def _registrable_domain(self, url: str) -> str:
        """取可注册主域（兼容 com.cn 等二级后缀）"""
        host = urlparse(url).netloc.lower().replace("www.", "")
        parts = host.split(".")
        if len(parts) >= 3 and parts[-2] in ("com", "net", "org", "gov", "edu",
                                             "ac", "co"):
            return ".".join(parts[-3:])
        return ".".join(parts[-2:]) if len(parts) >= 2 else host

    def _classify_company_result(self, url: str, trusted: bool = False) -> Optional[str]:
        """分类搜索结果：career=公司招聘页 home=官网首页 subpage=官网子页 None=噪声。trusted=True 表示用户显式输入的 URL，只做格式校验，跳过聚合/垃圾域名等自动发现降噪过滤"""
        if not url:
            return None
        # trusted（用户显式 URL）只做格式校验；其余自动发现结果走降噪黑名单
        if not trusted and (self._is_aggregator(url) or self._is_junk(url)):
            return None
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "/").lower()
        if not host or parsed.scheme not in ("http", "https"):
            return None
        if not trusted and any(h in host for h in LOGIN_HOST_HINTS):
            return None
        if not trusted and host.endswith((".edu.cn", ".ac.cn", ".edu", ".gov.cn", ".gov")):
            return None
        third_party_paths = ("/campus/view", "/xiaozhao/", "/jobfair",
                             "/xuanjiang", "/campus/detail")
        if not trusted and any(p in path for p in third_party_paths):
            return None
        if self._host_has_career_prefix(host) or \
                any(h in path for h in CAREER_URL_HINTS):
            return "career"
        if path in ("/", "") or path.rstrip("/") in ("/zh", "/cn", "/en", "/zh-cn"):
            return "home"
        return "subpage"

    # ================================================================== #
    # 公司官网 -> 招聘页定位
    # ================================================================== #
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
    # 门户候选发现（Tavily 宽泛查询，国内平台优先）
    # ================================================================== #
    def _build_portal_queries(self, target_info: TargetInstructionSchema) -> List[str]:
        """门户通道查询词：只保留中文查询，避免把海外招聘站捞进来"""
        location = (target_info.location or "").strip()
        queries = []
        # 每个岗位词各出一条查询，提高同义岗位的召回
        for term in query_terms(target_info, limit=2):
            zh = f"{term} {location} 招聘".strip()
            if target_info.keywords:
                zh += " " + " ".join(str(k) for k in target_info.keywords[:4])
            queries.append(zh)

        company = (target_info.company or "").strip()
        if company:
            queries.append(f"{company} 招聘 职位 {target_info.role}")
        return queries

    async def _discover_portal_candidates(self, target_info: TargetInstructionSchema) -> List[Dict]:
        """用 Tavily 发现候选招聘门户（不做域名白名单限制，排除应用商店/百科等噪声）"""
        if not self.api_key:
            logger.warning("未配置 TAVILY_API_KEY，无法发现候选门户")
            return []

        candidates: Dict[str, Dict] = {}
        for query in self._build_portal_queries(target_info):
            for item in await self._tavily_search(query, max_results=10):
                url = item.get("url", "")
                if not url or url in candidates or self._looks_non_job(url) or self._is_junk(url):
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

    async def _extract_company_jobs(self, company_name, career_url, target_info):
        """在公司招聘站内：进入职位列表页 -> 站内搜索 -> 锚点/XHR 双通道抽取职位"""
        page = None
        jobs, seen = [], set()
        try:
            page = await self._context.new_page()
            page.set_default_timeout(self.timeout_ms)
            api_jobs, handler = self._make_api_capture()
            page.on("response", handler)
            try:
                await page.goto(career_url, wait_until="domcontentloaded",
                                timeout=self.timeout_ms)
            except Exception as e:
                logger.warning(f"{company_name} 招聘页打开失败 {career_url}: {e}")
                return []
            await self._settle_page(page)

            # 1) 钻取到「社会招聘/全部职位/职位搜索」列表页
            #    当前 URL 本身就是职位列表页（用户直达链接）时不再导航走
            list_href = None if self._looks_like_listing_url(page.url) \
                else await self._find_job_list_href(page)
            if list_href:
                try:
                    await page.goto(list_href, wait_until="domcontentloaded",
                                    timeout=self.timeout_ms)
                    await self._settle_page(page)
                    logger.info(f"{company_name} 进入职位列表页 {page.url}")
                except Exception:
                    pass

            # 1.5) SPA：驱动页面自身「下一页」逐页加载，XHR 监听器会累积抓到每页职位
            await self._paginate_job_list(page)

            role_toks = self._role_tokens(target_info)
            title_kws = self._title_keywords(target_info)

            # 2) 遍历整份职位列表（不在站内搜索框输入精确岗位名），
            #    锚点统一按「方向词族标题相关性」打分排序
            scored = await self._score_anchors(page, role_toks, title_kws)

            # 3) 锚点抽取（过滤导航，只留职位详情）
            if len(scored) < 3 and self._has_captcha_or_wall(await self._safe_inner_text(page)):
                await self._handle_block(page.url, page)
                await self._settle_page(page)
                scored = await self._score_anchors(page, role_toks, title_kws)

            # 方向明确时只保留标题与方向相关的职位；一个相关的都没有才整体兜底
            scored = self._prune_by_title_relevance(scored, title_kws)

            for score, a in scored:
                href = a["href"]
                head = a["text"].split("\n", 1)[0].strip()
                if href in seen or self._is_nav_text(head) or self._looks_non_job(href):
                    continue
                if not self._looks_like_job_detail(head, href, role_toks, title_kws):
                    continue
                seen.add(href)
                jobs.append({
                    "url": href, "title": head[:80], "company": company_name,
                    "location": target_info.location or "",
                    "description": "", "source": "browser",
                })
                if len(jobs) >= self.max_jobs_per_site:
                    break

            # 4) XHR/API 兜底（SPA 职位卡片不是 <a> 时，用接口职位+站点 URL 模板）
            if len(jobs) < self.max_jobs_per_site:
                for item in self._rank_api_jobs(api_jobs, title_kws):
                    href = self._build_company_job_url(page.url, item)
                    text = item.get("title", "")
                    if not href or href in seen or self._is_nav_text(text):
                        continue
                    seen.add(href)
                    jobs.append({
                        "url": href, "title": text[:80], "company": company_name,
                        "location": item.get("city") or target_info.location or "",
                        "description": item.get("description") or "",
                        "source": "browser_api",
                    })
                    if len(jobs) >= self.max_jobs_per_site:
                        break

            logger.info(f"{company_name} 招聘站最终抽取 {len(jobs)} 个职位")
            return jobs
        except Exception as e:
            logger.warning(f"{company_name} 站内抽取失败 {career_url}: {e}")
            return jobs
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    @staticmethod
    def _looks_like_listing_url(url: str) -> bool:
        """当前 URL 本身就是职位列表页（如用户直达的 /campus/positions）时，不再钻取导航走"""
        path = urlparse((url or "").lower()).path
        return any(k in path for k in (
            "/positions", "/position/list", "/joblist", "/job-list", "/jobs",
            "/social", "/campus/position", "/vacanc",
        ))

    async def _paginate_job_list(self, page, max_pages: int = 5) -> int:
        """驱动 SPA 自身的「下一页」控件逐页加载（不碰搜索框），XHR 监听器会累积每页职位"""
        selectors = (
            ".btn-next:not(.is-disabled):not([disabled])",
            "li[title='下一页']:not(.disabled):not(.is-disabled)",
            "button[aria-label*='下一页']:not([disabled])",
            "a:has-text('下一页')", "button:has-text('下一页')",
            "[class*='pagination'] [class*='next']:not([class*='disabled'])",
        )
        clicked = 0
        for _ in range(max(1, max_pages) - 1):
            stepped = False
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() == 0 or not await loc.is_visible():
                        continue
                    cls = ((await loc.get_attribute("class")) or "").lower()
                    if "disabled" in cls:
                        continue
                    await loc.click(timeout=3000)
                    await self._settle_page(page, light=True)
                    clicked += 1
                    stepped = True
                    break
                except Exception:
                    continue
            if not stepped:
                break
        if clicked:
            logger.info(f"SPA 职位列表自动翻页 {clicked} 次: {page.url}")
        return clicked

    async def _find_job_list_href(self, page):
        """在招聘首页找「全部职位/社会招聘/职位搜索」列表页链接"""
        try:
            anchors = await self._collect_anchors(page)
        except Exception:
            return None
        best, best_score = None, 0
        for a in anchors:
            t = (a.get("text") or "").strip()
            href = a.get("href") or ""
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            # 不把 passport/login 等账号主机误当职位列表页（曾把京东带到登录页）
            if self._host_matches_patterns(urlparse(href).netloc.lower(), LOGIN_HOST_HINTS):
                continue
            score = 0
            if any(k in t for k in ["社会招聘", "全部职位", "职位搜索", "搜索职位",
                                    "所有职位", "热门职位", "查看职位"]):
                score += 10
            if any(k in t.lower() for k in ["all jobs", "search jobs", "open positions",
                                            "job opportunities", "early career"]):
                score += 10
            low = href.lower()
            if any(k in low for k in ["/social", "/position", "/search", "/jobs",
                                      "/joblist", "/job-list", "/list"]):
                score += 5
            if "校园" in t or "campus" in low or t in ["首页", "登录"]:
                score -= 8
            if score > best_score:
                best, best_score = href, score
        return best if best_score >= 10 else None

    def _is_nav_text(self, text: str) -> bool:
        t = (text or "").strip().lower().strip("/")
        if len(t) <= 2:
            return True
        nav = ["首页", "登录", "注册", "校园招聘", "社会招聘", "常见问题", "行程", "赛事",
               "计划", "官网", "返回", "更多", "查看更多", "了解更多", "关于我们", "联系我们",
               "home", "login", "register", "about", "contact", "faq", "more", "back"]
        return any(t == n for n in nav)

    def _looks_like_job_detail(self, text: str, href: str, role_toks, title_kws=None) -> bool:
        """判断锚点是否真的是职位详情：URL 像详情页，且文本像职位（职业词/精确 token/方向词族任一命中）"""
        t = (text or "").strip()
        if not JOB_DETAIL_RE.search(href or "") or len(t) < 4:
            return False
        occ = ["工程师", "开发", "设计师", "产品", "运营", "经理", "专员", "架构师",
               "分析师", "研究员", "主管", "总监", "顾问", "专家", "算法",
               "engineer", "developer", "designer", "manager", "specialist",
               "analyst", "intern", "scientist", "architect", "营销",
               "销售", "策划", "公关", "商务", "人力", "财务",
               "法务", "审计", "采购", "客服", "管培"]
        if any(w in t for w in occ):
            return True
        # 方向词族命中（如 AI 方向下的「大模型应用工程师」）也算职位详情
        family_hits, _ = title_direction_relevance(t, title_kws or [])
        if family_hits > 0:
            return True
        if role_toks and any(tok in t.lower() for tok in role_toks):
            return True
        return False

    def _make_api_capture(self):
        """返回 (结果列表, response 事件处理器)，抓取招聘站 XHR 中的职位 JSON"""
        found = []

        async def on_response(response):
            try:
                ct = (response.headers or {}).get("content-type", "")
                if "json" not in ct:
                    return
                u = response.url.lower()
                list_hints = ("getjoblist", "job/posts", "job/list", "position/list",
                              "positionlist", "positions/list", "joblist", "job-list",
                              "job/search", "search/job", "/jobs?", "vacancy/list",
                              "recruit/list", "queryjob", "jobquery", "job/page",
                              "position/query", "position/page", "queryposition",
                              "posts/list", "getpositionlist")
                # 城市/职类字典等「假列表」接口不算职位列表
                dict_hints = ("citylist", "postcodelist", "typelist", "dict/",
                              "gametree", "/category", "jobtype", "ranklist")
                if not any(k in u for k in list_hints):
                    return
                if any(k in u for k in dict_hints):
                    return
                data = await response.json()
                self._walk_jobs_json(data, found)
            except Exception:
                pass

        return found, on_response

    def _walk_jobs_json(self, node, found, depth=0):
        """递归遍历 JSON，提取职位对象（职位名 + 职位ID/链接 + 城市）"""
        if depth > 9 or len(found) >= 60:
            return
        name_keys = ("positionname", "jobname", "postname", "jobtitle", "recruitpost",
                     "position", "name", "title")
        id_keys = ("jobunionid", "positionid", "jobid", "postid", "recruitid", "id")
        city_keys = ("worklocation", "workcity", "cityname", "city",
                     "location", "workplace", "address")
        desc_keys = ("positiondescription", "jobdescription", "description",
                     "responsibility", "responsibilities", "duty", "jdcontent", "remark")
        if isinstance(node, dict):
            name, jid, link = None, None, None
            cities, city_s, desc = [], "", ""
            for k, v in node.items():
                kl = k.lower()
                if isinstance(v, str) and v.strip():
                    if kl in name_keys and len(v.strip()) >= 3:
                        name = v.strip()
                    elif kl in id_keys:
                        jid = v.strip()
                    elif kl in ("positionurl", "pcurl", "detailurl", "joburl",
                                "posturl", "h5url", "url", "link") and v.startswith("http"):
                        link = v
                    elif kl in city_keys and not city_s:
                        city_s = v.strip()
                    elif kl in desc_keys and len(v.strip()) >= 20 and not desc:
                        desc = v.strip()
                elif isinstance(v, (str, int)) and kl in id_keys and str(v).strip():
                    jid = str(v).strip()
                elif isinstance(v, list) and kl in ("citylist", "cities", "workcitylist"):
                    cities = [c.get("name", "") for c in v
                              if isinstance(c, dict) and c.get("name")]
            if name and (jid or link) and self._looks_like_job_name(name):
                if not (link and any(x.get("url") == link for x in found)) and \
                        not (jid and any(x.get("id") == jid for x in found)):
                    found.append({
                        "title": name, "id": jid or "",
                        "url": link or "",
                        "city": "、".join(cities) or city_s,
                        "description": desc,
                    })
            for v in node.values():
                self._walk_jobs_json(v, found, depth + 1)
        elif isinstance(node, list):
            for v in node[:80]:
                self._walk_jobs_json(v, found, depth + 1)

    def _looks_like_job_name(self, name: str) -> bool:
        """排除枚举/分类/城市等非职位名"""
        n = (name or "").strip()
        if len(n) < 4 or len(n) > 40:
            return False
        if n in ("社会招聘", "校园招聘", "应届生", "实习生", "正式", "北京", "上海"):
            return False
        if n.endswith(("类", "招聘", "计划", "专栏")) and len(n) <= 6:
            return False
        occ = ("工程师", "开发", "经理", "专员", "设计师", "运营", "产品", "分析师",
               "研究员", "主管", "总监", "顾问", "专家", "架构师", "算法", "测试",
               "engineer", "developer", "manager", "intern", "designer",
               "specialist", "analyst", "scientist", "lead", "director",
               "营销", "销售", "策划", "公关", "商务", "人力", "行政",
               "财务", "法务", "审计", "采购", "客服", "管培")
        # 任何长度都必须含岗位词，过滤地址/分类/枚举对象
        if not any(w in n.lower() for w in occ):
            return False
        return True

    def _build_company_job_url(self, page_url: str, item: Dict) -> str:
        """根据招聘站主机与接口返回的职位 ID/链接构造详情页 URL"""
        if item.get("url"):
            return item["url"]
        jid = item.get("id")
        if not jid:
            return ""
        host = urlparse(page_url).netloc.lower()
        low_url = (page_url or "").lower()
        if "meituan.com" in host:
            return f"https://zhaopin.meituan.com/web/position/detail?jobUnionId={jid}"
        if "bytedance.com" in host:
            return f"https://jobs.bytedance.com/experienced/position/{jid}/detail"
        if "bilibili.com" in host:
            kind = "campus" if "/campus/" in low_url else "social"
            return f"https://jobs.bilibili.com/{kind}/positions/{jid}/detail"
        return ""

    async def _extract_jobs_from_portal(self, portal: Dict, target_info) -> List[Dict]:
        """打开单个招聘页（聚合门户或公司招聘页），抽取职位详情链接"""
        url = portal["url"]
        page = None
        try:
            page = await self._context.new_page()
            page.set_default_timeout(self.timeout_ms)
            api_jobs, handler = self._make_api_capture()
            page.on("response", handler)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            except Exception as e:
                logger.warning(f"招聘页打开失败 {url}: {e}")
                return []

            await self._settle_page(page)
            # SPA：驱动页面自身分页控件逐页加载（不碰搜索框）
            await self._paginate_job_list(page)

            role_toks = self._role_tokens(target_info)
            title_kws = self._title_keywords(target_info)
            # 遍历整份职位列表，不使用站内搜索框；按方向词族给标题打分排序
            scored = await self._score_anchors(page, role_toks, title_kws)

            if len(scored) < 3 and self._has_captcha_or_wall(await self._safe_inner_text(page)):
                await self._handle_block(url, page)
                await self._settle_page(page)
                scored = await self._score_anchors(page, role_toks, title_kws)

            # 方向明确时只保留标题相关的职位；一个相关的都没有才整体兜底
            scored = self._prune_by_title_relevance(scored, title_kws)

            jobs = []
            seen = set()
            for score, a in scored[: self.max_jobs_per_site * 3]:
                head = a["text"].split("\n", 1)[0].strip()
                if a["href"] in seen or self._looks_non_job(a["href"]):
                    continue
                seen.add(a["href"])
                jobs.append({
                    "url": a["href"],
                    "title": head[:80],
                    "company": self._guess_company(portal.get("title", "")),
                    "location": target_info.location or "",
                    "description": portal.get("snippet", ""),
                    "source": "browser",
                })
                if len(jobs) >= self.max_jobs_per_site:
                    break

            # SPA 兜底：职位卡片不是 <a> 时，用 XHR 接口抓到的职位（按方向相关性排序）
            if len(jobs) < self.max_jobs_per_site:
                portal_company = self._guess_company(portal.get("title", ""))
                for item in self._rank_api_jobs(api_jobs, title_kws):
                    href = item.get("url") or self._build_company_job_url(page.url, item)
                    text = item.get("title", "")
                    if not href or href in seen or self._is_nav_text(text):
                        continue
                    seen.add(href)
                    jobs.append({
                        "url": href, "title": text[:80], "company": portal_company,
                        "location": item.get("city") or target_info.location or "",
                        "description": item.get("description") or portal.get("snippet", ""),
                        "source": "browser_api",
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

    async def _score_anchors(self, page, role_toks: List[str], title_kws: List[str] = None) -> List:
        """抽取锚点并评分排序，返回 [(score, anchor)] 降序；title_kws 为方向词族"""
        anchors = await self._collect_anchors(page)
        scored = []
        for a in anchors:
            score = self._score_anchor(a["text"], a["href"], role_toks, title_kws)
            if score > 0:
                scored.append((score, a))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    async def _try_role_search(self, page, role: str) -> bool:
        """招聘站带搜索框时输入岗位触发站内检索（保留备用；主流程已按需求改为遍历职位列表，不再调用）"""
        if not role:
            return False
        selector = (
            "input[type='search'], input[placeholder*='搜索'], input[placeholder*='岗位'], "
            "input[placeholder*='Search'], input[placeholder*='search'], "
            "input[name*='keyword' i], input[name*='search' i], input[aria-label*='Search' i]"
        )
        try:
            box = await page.query_selector(selector)
            if not box or not await box.is_visible():
                return False
            await box.click(timeout=3000)
            await box.fill(role[:30], timeout=3000)
            await box.press("Enter", timeout=3000)
            await asyncio.sleep(2.5)
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
    def _title_keywords(self, target_info: TargetInstructionSchema) -> List[str]:
        """方向词族（小写）：遍历职位列表时按标题语义判相关的依据"""
        kws = getattr(target_info, "title_keywords", None) or []
        return [str(k).lower() for k in kws if k]

    def _prune_by_title_relevance(self, scored: List, title_kws: List[str]) -> List:
        """方向明确时只保留标题命中方向词族的锚点；一个相关的都没有时整体保留兜底"""
        if not scored or not title_kws:
            return scored
        related = [
            (s, a) for s, a in scored
            if title_direction_relevance(
                (a.get("text") or "").split("\n", 1)[0], title_kws
            )[0] > 0
        ]
        if related:
            logger.info(f"标题方向筛选：{len(scored)} 个职位锚点 -> {len(related)} 个相关")
            return related
        logger.info("标题方向筛选：无标题命中方向词族，保留全部候选兜底")
        return scored

    def _rank_api_jobs(self, api_jobs: List[Dict], title_kws: List[str]) -> List[Dict]:
        """XHR 接口职位：方向相关的排前面；存在相关职位时只返回相关职位"""
        if not api_jobs:
            return []
        if not title_kws:
            return api_jobs
        related, others = [], []
        for it in api_jobs:
            hits, _ = title_direction_relevance(it.get("title", ""), title_kws)
            (related if hits > 0 else others).append((hits, it))
        if not related:
            return api_jobs
        related.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in related]

    def _role_tokens(self, target_info: TargetInstructionSchema) -> List[str]:
        """从目标岗位 + 变体 + 关键词中拆出用于模糊匹配的 token"""
        return role_tokens(
            target_info.role,
            target_info.keywords,
            getattr(target_info, "role_variants", None),
        )

    def _fallback_role_terms(self, target_info: TargetInstructionSchema) -> List[str]:
        """站内搜索框可用的岗位词序列（主岗位名在前，变体在后）"""
        return query_terms(target_info, limit=3) or []

    def _score_anchor(self, text: str, href: str, role_toks: List[str],
                      title_kws: List[str] = None) -> int:
        """给单个锚点评分，>0 才认为是职位链接（只取首行职位名参与评分）

        分层打分：通用职业词只给基础分（任何工程师岗都有），方向词族命中给高分，
        保证目标方向的职位（如 AI 方向下的「大模型应用工程师」）排在无关方向之前。
        """
        head = (text or "").split("\n", 1)[0].strip()
        t = head.lower()
        h = href.lower()
        if len(head) < 2 or len(head) > 120:
            return 0
        if self._looks_non_job(href) or any(x in t for x in ["登录", "注册", "下载", "帮助"]):
            return 0
        occ_words = ["工程师", "开发", "设计师", "产品经理", "运营",
                      "架构师", "分析师", "研究员", "实习", "算法",
                      "engineer", "developer", "designer", "manager",
                      "scientist", "architect", "营销", "销售", "策划",
                      "公关", "商务", "人力", "财务", "法务", "管培"]
        occ_hit = any(tok in t for tok in occ_words)
        family_hits, _ = title_direction_relevance(head, title_kws or [])
        hit_tokens = [tok for tok in (role_toks or []) if tok in t]
        # 标题本身必须像一个职位（职业词/方向词族/精确 token 至少命中一个），
        # 仅 URL 像详情页不算（职能/导航链接也可能用 /position/ 路径）
        if not (occ_hit or family_hits > 0 or hit_tokens):
            return 0
        score = 0
        if any(hint in h for hint in JOB_URL_HINTS):
            score += 3
        if occ_hit:
            score += 3
        # 方向词族命中（标题语义相关）：权重最高，相关方向职位排最前
        score += 6 * family_hits
        score += 2 * len(hit_tokens)
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

    @staticmethod
    def _host_matches_patterns(host: str, patterns) -> bool:
        """主机名命中黑名单：含点模式按主域/子域精确匹配（避免 query/path 误伤），无点模式保留子串匹配"""
        host = (host or "").lower()
        for pat in patterns:
            pat = pat.lower()
            if "." in pat and not pat.endswith("."):
                if host == pat or host.endswith("." + pat):
                    return True
            elif pat in host:
                return True
        return False

    def _is_aggregator(self, url: str) -> bool:
        host = urlparse(url or "").netloc.lower()
        return self._host_matches_patterns(host, AGGREGATOR_DOMAINS)

    def _url_has_career_hint(self, url: str) -> bool:
        p = urlparse((url or "").lower())
        if self._host_has_career_prefix(p.netloc):
            return True
        return any(h in p.path for h in CAREER_URL_HINTS)

    def _host_has_career_prefix(self, host: str) -> bool:
        host = (host or "").lower().replace("www.", "")
        return any(host.startswith(p) for p in CAREER_SUBDOMAIN_PREFIXES)

    def _is_junk(self, url: str) -> bool:
        host = urlparse(url or "").netloc.lower()
        return self._host_matches_patterns(host, JUNK_DOMAINS)

    def _is_junk_title(self, title: str) -> bool:
        t = (title or "")
        junk_words = ["公告", "简章", "宣讲会", "是干什么", "兼职", "是做什么",
                      "面经", "经验贴", "教程", "怎么", "如何", "r/", "latest "]
        return any(w.lower() in t.lower() for w in junk_words)

    def _portal_score(self, url: str, title: str) -> int:
        """门户排序：国内垂直招聘平台优先，其次公司自有招聘站"""
        host = urlparse(url or "").netloc.lower()
        t = (title or "").lower()
        score = 0
        for i, d in enumerate(CN_JOB_PLATFORMS):
            if d in host:
                score += 20 - i
        if self._url_has_career_hint(url):
            score += 8
        if any(w in t for w in ["招聘", "职位", "career", "job"]):
            score += 2
        return score

    def _guess_company(self, portal_title: str) -> str:
        """从门户标题粗略推断公司名（无法确定时返回空串）"""
        return re.split(r"[-_|–—]", (portal_title or "").strip())[0].strip()

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
