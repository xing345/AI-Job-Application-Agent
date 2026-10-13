"""通用岗位发现器。

不依赖特定网站的 selector，通过以下通用策略识别岗位：
1. URL 模式识别：岗位详情页 URL 通常包含 position/job/recruitment + 数字ID
2. 文本特征过滤：排除导航链接、登录注册等噪声
3. 重复结构检测：岗位列表通常是重复的卡片结构
4. 滚动加载：自动滚动触发懒加载，收集全量岗位

支持任何招聘网站（公司官网校招页、招聘门户等）。
"""
from __future__ import annotations

import logging
import re
from typing import List, Set
from urllib.parse import urljoin, urlparse, parse_qs

from src.browser.hitl import default_handler as hitl
from src.browser.manager import get_browser
from src.browser.navigator import wait_for_load
from src.models.job import JobPosting
from src.search.adapters import get_adapter
from src.search.site_registry import SiteConfig

logger = logging.getLogger(__name__)

# ============================================================
# 岗位详情页 URL 模式（覆盖主流招聘网站）
# ============================================================
JOB_URL_PATTERNS = [
    # 常见路径模式
    r"/position/\d+",
    r"/positions?/\d+",
    r"/job/\d+",
    r"/jobs?/\d+",
    r"/job_detail",
    r"/recruitment/\d+",
    r"/recruit/\d+",
    r"/zhaopin/\d+",
    r"/campus/position/\d+",
    r"/campus/job/\d+",
    r"/social/position/\d+",
    r"/social/job/\d+",
    r"/intern/position/\d+",
    r"/detail/\d+",
    r"/post/\d+",
    r"/posts?/\d+",
    r"/opportunity/\d+",
    r"/careers?/.*\d+",
    r"/talent/\d+",
    # MokaHR / 北森 / 用友等招聘系统
    r"/campus-recruitment/.*#/jobs?/",
    r"/social-recruitment/.*#/jobs?/",
    r"/mokahr\.com/.*jobs?",
    r"/job\.mokahr\.com",
    # 参数模式
    r"[?&](positionId|jobId|postId|recruitId|id)=\d+",
]

# 列表页/导航页 URL 模式（排除）
LIST_URL_PATTERNS = [
    r"/campus/position/?$",
    r"/campus/jobs?/?$",
    r"/campus/?$",
    r"/positions?/?$",
    r"/jobs?/?$",
    r"/recruitment/?$",
    r"/social/?$",
    r"/intern/?$",
    r"/search/?$",
    r"/zhaopin/?$",
]

# 噪声文本（导航/按钮/非岗位标题）
NOISE_TEXTS = {
    "首页", "首页/", "关于我们", "关于", "联系我们", "联系方式", "隐私政策", "用户协议",
    "登录", "注册", "退出", "登出", " sign in", "sign up", "login", "register",
    "更多", "查看更多", "加载更多", "展开更多", "下一页", "上一页", "末页", "第一页",
    "全部", "筛选", "排序", "重置", "清除", "搜索", "查找",
    "校招", "校园招聘", "社招", "社会招聘", "实习", "实习生招聘", "职位", "职位列表",
    "技术", "产品", "设计", "运营", "市场", "职能", "销售", "研发", "算法", "前端", "后端",
    "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "西安", "南京", "重庆",
    "了解更多", "查看详情", "点击查看", "详情", "立即投递", "申请职位", "投递简历",
    "微信", "微博", "抖音", "知乎", "B站", "哔哩哔哩",
    "招聘动态", "产品与技术", "成长与回报", "技术人才项目",
    "ByteIntern", "项目说明", "团队介绍",
    "English", "中文", "语言",
}

# 岗位标题常见关键词（用于正向判断）
JOB_TITLE_KEYWORDS = [
    "工程师", "开发", "设计师", "产品经理", "产品", "运营", "算法", "分析师",
    "架构师", "研究员", "科学家", "实习生", "培训生", "管培生", "专员",
    "经理", "总监", "主管", "顾问", "专家",
    "engineer", "developer", "designer", "manager", "analyst", "intern",
    "architect", "researcher", "scientist", "specialist", "consultant",
]


async def discover_jobs(config: SiteConfig) -> List[JobPosting]:
    """从指定站点全量收集岗位。

    策略优先级：
    1. 专用站点适配器（如果已注册）—— 结构化提取，含公司/地点字段
    2. 配置的专用 selector 提取
    3. 通用链接发现 + 滚动加载
    4. 深度探测（兜底）
    """
    browser = await get_browser()
    page = browser.page

    logger.info("Starting job discovery: %s (%s)", config.name, config.category_url)

    jobs: list[JobPosting] = []
    seen_urls: set[str] = set()

    try:
        await page.goto(config.category_url, wait_until="domcontentloaded", timeout=30000)
        # 等待 SPA 加载
        await page.wait_for_timeout(4000)
        await wait_for_load(page, timeout=15000)
        await page.wait_for_timeout(2000)

        # HITL 检测
        await hitl.check_and_pause(page)

        # 策略1：专用站点适配器（优先）
        adapter_cls = get_adapter(config.name)
        if adapter_cls:
            logger.info("使用专用适配器: %s", adapter_cls.__name__)
            adapter = adapter_cls(config)
            jobs = await adapter.discover_jobs(page)
            if jobs:
                logger.info("适配器发现 %d 个岗位", len(jobs))

        # 策略2：专用 selector 提取（如果适配器未找到或无适配器）
        if not jobs and config.job_card_selector and not config.job_card_selector.startswith("a[href*="):
            jobs = await _discover_with_selectors(page, config, seen_urls)

        # 策略3：通用链接发现
        if not jobs:
            logger.info("使用通用链接发现策略...")
            jobs = await _discover_by_links(page, config, seen_urls)

        # 策略4：深度探测（兜底）
        if not jobs:
            logger.info("通用策略未找到，尝试深度探测...")
            jobs = await _deep_probe(page, config, seen_urls)

    except Exception as e:
        logger.exception("Job discovery error: %s", e)

    logger.info("Discovery complete: %d jobs from %s", len(jobs), config.name)
    return jobs


# ============================================================
# 策略一：专用 selector 提取
# ============================================================

async def _discover_with_selectors(page, config: SiteConfig, seen_urls: set) -> List[JobPosting]:
    """用配置的专用 selector 提取岗位（支持滚动加载）。"""
    jobs: list[JobPosting] = []
    no_new_count = 0

    for scroll_idx in range(config.max_pages):
        batch = await _extract_by_selectors(page, config, seen_urls)
        if batch:
            jobs.extend(batch)
            no_new_count = 0
        else:
            no_new_count += 1
            if no_new_count >= 5:
                break

        if len(jobs) >= 500:
            break

        # 滚动加载
        await _scroll_page(page)
        logger.info("Scroll %d: total %d jobs", scroll_idx + 1, len(jobs))

    return jobs


async def _extract_by_selectors(page, config: SiteConfig, seen_urls: set) -> List[JobPosting]:
    """用配置的 selector 提取当前页面的岗位。"""
    jobs: list[JobPosting] = []
    selectors = [s.strip() for s in config.job_card_selector.split(",") if s.strip()]

    for sel in selectors:
        try:
            cards = await page.query_selector_all(sel)
            if not cards:
                continue

            for card in cards:
                try:
                    job = await _extract_from_card(card, config)
                    if job and job.detail_url and job.detail_url not in seen_urls:
                        seen_urls.add(job.detail_url)
                        jobs.append(job)
                except Exception:
                    continue

            if jobs:
                break
        except Exception:
            continue

    return jobs


# ============================================================
# 策略二：通用链接发现（核心）
# ============================================================

async def _discover_by_links(page, config: SiteConfig, seen_urls: set) -> List[JobPosting]:
    """通用链接发现：遍历页面所有 <a>，通过 URL 模式+文本特征识别岗位。

    自动滚动加载，直到没有新岗位。
    """
    jobs: list[JobPosting] = []
    no_new_count = 0
    max_scrolls = config.max_pages

    for scroll_idx in range(max_scrolls):
        batch = await _extract_job_links(page, config, seen_urls)
        if batch:
            jobs.extend(batch)
            no_new_count = 0
        else:
            no_new_count += 1
            if no_new_count >= 8:  # 连续8次无新岗位才停止（虚拟滚动可能需要多次滚动）
                logger.info("连续 %d 次无新岗位，停止滚动", no_new_count)
                break

        if len(jobs) >= 500:
            logger.info("已收集 500 个岗位，停止")
            break

        # 滚动前记录当前链接数量
        try:
            link_count_before = await page.locator("a[href]").count()
        except Exception:
            link_count_before = 0

        await _scroll_page(page)

        # 滚动后额外等待，确保虚拟滚动加载新内容
        await page.wait_for_timeout(2000)

        try:
            link_count_after = await page.locator("a[href]").count()
        except Exception:
            link_count_after = 0

        logger.info("Scroll %d: total %d jobs (new %d), links %d->%d",
                    scroll_idx + 1, len(jobs), len(batch), link_count_before, link_count_after)

    return jobs


async def _extract_job_links(page, config: SiteConfig, seen_urls: set) -> List[JobPosting]:
    """从当前页面提取所有岗位链接。"""
    jobs: list[JobPosting] = []

    try:
        links = await page.query_selector_all("a[href]")
        logger.debug("Page has %d links", len(links))

        for link in links:
            try:
                href = await link.get_attribute("href")
                if not href:
                    continue

                full_url = urljoin(config.base_url, href)

                # URL 模式判断
                if not _is_job_detail_url(full_url, config):
                    continue

                # 文本提取与清洗
                raw_text = (await link.inner_text()).strip()
                title = _clean_job_title(raw_text)

                # 文本过滤
                if not _is_valid_job_title(title):
                    continue

                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    jobs.append(JobPosting(
                        title=title,
                        company="",
                        location="",
                        detail_url=full_url,
                        site_name=config.name,
                    ))
            except Exception:
                continue

        if jobs:
            logger.info("Extracted %d job links from current view", len(jobs))

    except Exception as e:
        logger.warning("Link extraction error: %s", e)

    return jobs


# ============================================================
# 策略三：深度探测（兜底）
# ============================================================

async def _deep_probe(page, config: SiteConfig, seen_urls: set) -> List[JobPosting]:
    """深度探测：查找页面上所有可能的岗位入口。

    当通用链接策略失败时，尝试：
    1. 查找 iframe 中的内容
    2. 查找 shadow DOM
    3. 查找 data-* 属性中的链接
    """
    jobs: list[JobPosting] = []

    try:
        # 尝试从页面 JS 中提取岗位数据（很多 SPA 把数据存在 window 变量中）
        job_data = await page.evaluate("""() => {
            const results = [];
            // 查找常见的全局数据变量
            const keys = Object.keys(window).filter(k => 
                /job|position|recruit|post|career/i.test(k)
            );
            for (const key of keys) {
                try {
                    const val = window[key];
                    if (Array.isArray(val)) {
                        for (const item of val) {
                            if (item && (item.id || item.jobId || item.positionId)) {
                                results.push(item);
                            }
                        }
                    }
                } catch(e) {}
            }
            return results;
        }""")

        if job_data:
            logger.info("从页面 JS 变量中发现 %d 条岗位数据", len(job_data))
            # 这里可以进一步解析，但不同网站数据结构不同，暂时只记录

        # 查找所有包含数字 ID 的元素（可能是岗位卡片）
        cards_with_id = await page.query_selector_all("[data-id], [data-job-id], [data-position-id]")
        if cards_with_id:
            logger.info("发现 %d 个带 data-id 的元素", len(cards_with_id))

    except Exception as e:
        logger.debug("Deep probe error: %s", e)

    return jobs


# ============================================================
# 工具函数
# ============================================================

async def _scroll_page(page) -> None:
    """滚动页面触发懒加载（支持虚拟滚动）。

    策略：
    1. 先尝试滚动整个页面
    2. 再尝试滚动可滚动的容器元素
    3. 使用 PageDown 键作为兜底
    """
    try:
        # 方式1：滚动整个页面（分两次）
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)

        # 方式2：滚动可滚动容器（虚拟滚动列表常见）
        await page.evaluate("""() => {
            // 查找所有可滚动的容器
            const containers = document.querySelectorAll('*');
            for (const el of containers) {
                const style = window.getComputedStyle(el);
                if ((style.overflowY === 'auto' || style.overflowY === 'scroll') 
                    && el.scrollHeight > el.clientHeight + 100) {
                    el.scrollTop = el.scrollHeight;
                }
            }
        }""")
        await page.wait_for_timeout(1000)

        # 方式3：PageDown 键（兜底）
        await page.keyboard.press("PageDown")
        await page.wait_for_timeout(1000)
        await page.keyboard.press("PageDown")
        await page.wait_for_timeout(1500)

        await wait_for_load(page, timeout=8000)
    except Exception:
        pass


def _is_job_detail_url(url: str, config: SiteConfig) -> bool:
    """判断 URL 是否指向岗位详情页（通用模式）。"""
    parsed = urlparse(url)
    base_parsed = urlparse(config.base_url)

    # 域名检查：必须是本站点或子域名
    if parsed.netloc and base_parsed.netloc:
        if parsed.netloc != base_parsed.netloc and not parsed.netloc.endswith("." + base_parsed.netloc):
            # 允许常见招聘平台域名
            allowed_domains = ["mokahr.com", "nowcoder.com", "zhaopin.com", "liepin.com", "51job.com"]
            if not any(parsed.netloc.endswith(d) for d in allowed_domains):
                return False

    # 排除列表页
    path = parsed.path.rstrip("/")
    for pattern in LIST_URL_PATTERNS:
        if re.match(pattern, path, re.IGNORECASE):
            # 列表页必须带具体 ID 参数才算详情页
            if not re.search(r"[?&](id|jobId|positionId|postId)=\d+", url):
                return False

    # 匹配岗位详情页模式
    for pattern in JOB_URL_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return True

    # 兜底：路径中同时包含岗位关键词和 6 位以上数字（详情页 ID）
    # 收紧：不能只因为有数字就认为是岗位页，必须有岗位相关关键词
    job_keywords = r"(position|job|recruit|recruitment|detail|post|opportunity|career|zhaopin|gangwei)"
    if re.search(job_keywords, url, re.IGNORECASE) and re.search(r"/\d{6,}", url):
        if not re.search(r"/(page|p)/\d+", url, re.IGNORECASE):
            return True

    return False


def _is_valid_job_title(title: str) -> bool:
    """判断文本是否为有效的岗位标题。"""
    if not title:
        return False

    # 长度检查
    if len(title) < 2 or len(title) > 100:
        return False

    # 纯噪声词
    if title.strip().lower() in {t.lower() for t in NOISE_TEXTS}:
        return False

    # 包含噪声词（精确匹配开头）
    title_lower = title.strip().lower()
    for noise in NOISE_TEXTS:
        if title_lower == noise.lower():
            return False

    # 纯数字/符号
    if re.match(r'^[\d\s\W]+$', title):
        return False

    # 纯 URL
    if title.startswith("http"):
        return False

    # 正向判断：包含岗位关键词，或者看起来像职位名称
    has_keyword = any(kw.lower() in title_lower for kw in JOB_TITLE_KEYWORDS)
    if has_keyword:
        return True

    # 没有关键词但长度合理，可能是小语种或特殊岗位名，保守通过
    # 但排除明显的短语（少于4个字且不含关键词）
    if len(title) >= 4 and not any(c in title for c in "，。！？、；："):
        return True

    return False


def _clean_job_title(raw_title: str) -> str:
    """从岗位链接文本中提取纯标题。

    很多网站的链接文本是多行的：
    第一行是标题，后面是地点、类型、职位ID等。
    """
    if not raw_title:
        return ""

    # 取第一行
    lines = raw_title.split("\n")
    title = lines[0].strip()

    # 去掉常见后缀
    title = re.sub(r"职位\s*ID\s*[：:].*$", "", title).strip()
    title = re.sub(r"\s*-\s*团队介绍.*$", "", title).strip()
    title = re.sub(r"\s*-\s*查看更多.*$", "", title).strip()

    # 去掉首尾的特殊符号
    title = title.strip(" -—|·•")

    return title


async def _extract_from_card(card, config: SiteConfig) -> JobPosting | None:
    """从岗位卡片提取信息（支持 card 本身是 <a> 的情况）。"""
    card_tag = await card.evaluate("el => el.tagName.toLowerCase()")
    card_is_link = card_tag == "a"

    # 标题
    title = ""
    if config.job_title_selector:
        for sel in config.job_title_selector.split(","):
            sel = sel.strip()
            if not sel:
                continue
            try:
                el = await card.query_selector(sel)
                if el:
                    title = (await el.inner_text()).strip()
                    if title:
                        break
            except Exception:
                continue
    elif card_is_link:
        title = (await card.inner_text()).strip()

    title = _clean_job_title(title)
    if not title or len(title) > 200:
        return None

    # 链接
    detail_url = ""
    if config.job_link_selector:
        for sel in config.job_link_selector.split(","):
            sel = sel.strip()
            if not sel:
                continue
            try:
                el = await card.query_selector(sel)
                if el:
                    href = await el.get_attribute("href")
                    if href:
                        detail_url = urljoin(config.base_url, href)
                        break
            except Exception:
                continue
    elif card_is_link:
        href = await card.get_attribute("href")
        if href:
            detail_url = urljoin(config.base_url, href)

    if not detail_url:
        return None

    return JobPosting(
        title=title,
        company="",
        location="",
        detail_url=detail_url,
        site_name=config.name,
    )
