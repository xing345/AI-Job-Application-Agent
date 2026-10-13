"""JD 详情抓取节点。

只打开通过初筛的岗位（或手动指定的 URL），提取完整 JD。
Playwright 做元素级提取，不调 LLM，不截断。
遇到登录墙/验证码 → HITL 暂停。
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from playwright.async_api import Page

from src.agent.state import AgentState
from src.browser.hitl import default_handler as hitl
from src.browser.manager import get_browser
from src.browser.navigator import wait_for_load
from src.models.job import JobDetail, JobPosting
from src.search.adapters import get_adapter

logger = logging.getLogger(__name__)

# 常见 JD 正文容器 selector（按优先级尝试）
JD_CONTAINER_SELECTORS = [
    ".job-detail", ".job-detail-content", ".position-detail",
    ".job-description", ".jd-container", ".job-content",
    ".position-content", ".recruit-detail", ".job-info",
    ".job_requirement", ".duty", ".responsibility",
    "[class*='job-detail']", "[class*='position-detail']",
    "[class*='jobDesc']", "[class*='job_desc']",
    "[class*='description']", "[class*='content']",
    "article", "main",
]

# 岗位职责/任职要求分段关键词
RESPONSIBILITY_KEYWORDS = ["岗位职责", "工作职责", "工作内容", "岗位描述", "职责描述", "你将做什么", "what you'll do", "responsibilities"]
REQUIREMENT_KEYWORDS = ["任职要求", "岗位要求", "任职资格", "资格要求", "能力要求", "我们希望你", "要求", "requirements", "qualifications"]


async def _extract_page_text(page: Page) -> str:
    """提取页面主要文本内容。"""
    # 先尝试常见 JD 容器
    for sel in JD_CONTAINER_SELECTORS:
        try:
            locator = page.locator(sel).first
            if await locator.count() > 0:
                text = await locator.inner_text()
                text = text.strip()
                if len(text) > 100:  # 内容足够长才认为是 JD 容器
                    logger.info("JD container found: %s (len=%d)", sel, len(text))
                    return text
        except Exception:
            continue

    # 回退：取 body 文本，但去掉导航/页脚等噪声
    try:
        # 尝试取 main 或 article
        for sel in ["main", "article", ".content", "#content"]:
            try:
                locator = page.locator(sel).first
                if await locator.count() > 0:
                    text = (await locator.inner_text()).strip()
                    if len(text) > 100:
                        return text
            except Exception:
                continue
        body = await page.locator("body").inner_text()
        return body.strip()
    except Exception:
        return ""


def _split_jd(full_text: str) -> tuple[str, str]:
    """尝试把 JD 全文拆分为岗位职责和任职要求。"""
    responsibilities = ""
    requirements = ""

    # 找任职要求的位置
    req_pos = -1
    req_kw = ""
    for kw in REQUIREMENT_KEYWORDS:
        idx = full_text.lower().find(kw.lower())
        if idx >= 0 and (req_pos < 0 or idx < req_pos):
            req_pos = idx
            req_kw = kw

    # 找岗位职责的位置
    resp_pos = -1
    for kw in RESPONSIBILITY_KEYWORDS:
        idx = full_text.lower().find(kw.lower())
        if idx >= 0 and (resp_pos < 0 or idx < resp_pos):
            resp_pos = idx

    if req_pos >= 0:
        # 任职要求部分
        requirements = full_text[req_pos:].strip()
        # 岗位职责 = 任职要求之前的部分（从岗位职责关键词开始）
        if resp_pos >= 0 and resp_pos < req_pos:
            responsibilities = full_text[resp_pos:req_pos].strip()
        else:
            responsibilities = full_text[:req_pos].strip()
    elif resp_pos >= 0:
        responsibilities = full_text[resp_pos:].strip()

    return responsibilities, requirements


async def _extract_meta(page: Page) -> dict:
    """提取岗位元信息（标题、薪资、地点等）。"""
    meta = {"title": "", "salary": "", "location": ""}

    # 标题：尝试多种 selector，优先从 JD 容器内提取
    title_selectors = [
        ".position-detail h1", ".position-detail .title",
        ".job-detail h1", ".job-detail .title",
        ".job-info h1", ".job-info .title",
        "h1", ".job-title", ".position-name",
        "[class*='job-title']", "[class*='position-name']",
        "[class*='jobTitle']", "[class*='positionTitle']",
    ]

    try:
        for sel in title_selectors:
            try:
                locator = page.locator(sel).first
                if await locator.count() > 0:
                    t = (await locator.inner_text()).strip()
                    # 过滤导航/通用标题
                    if t and len(t) < 100 and t not in ("校招", "校园招聘", "职位", "岗位", "首页"):
                        meta["title"] = t
                        break
            except Exception:
                continue

        # 如果还是通用标题，尝试从页面文本中提取
        if not meta["title"] or meta["title"] in ("校招", "校园招聘", "职位", "岗位"):
            body_text = await page.locator("body").inner_text()
            # 取前几行中看起来像岗位标题的行
            for line in body_text.split("\n")[:20]:
                line = line.strip()
                if (len(line) > 3 and len(line) < 80
                        and not any(kw in line for kw in ["登录", "注册", "首页", "校招", "筛选", "清除", "招聘项目", "职位类别"])
                        and any(kw in line for kw in ["工程师", "开发", "设计", "产品", "运营", "算法", "实习", "经理", "专员", "分析师", "架构师", "研究员"])):
                    meta["title"] = line
                    break

        if not meta["title"]:
            meta["title"] = (await page.title()).strip()
    except Exception:
        pass

    # 薪资：常见模式
    try:
        body_text = await page.locator("body").inner_text()
        salary_match = re.search(r"(\d+[-~]\d+[Kk千]?|\d+[Kk]?[-~]\d+[Kk]?|面议|\d+万-\d+万)", body_text)
        if salary_match:
            meta["salary"] = salary_match.group(1)
    except Exception:
        pass

    return meta


async def fetch_single_jd(page: Page, url: str, site_name: str = "", job_title: str = "") -> Optional[JobDetail]:
    """抓取单个岗位的完整 JD。

    策略：
    1. 如果站点有专用适配器，优先使用适配器的 extract_jd_detail
    2. 否则使用通用提取逻辑

    Args:
        page: Playwright 页面
        url: 岗位详情页 URL
        site_name: 站点名称
        job_title: 岗位标题（从列表页获取，用于验证和适配器提取）

    Returns:
        JobDetail，失败返回 None
    """
    logger.info("Fetching JD: %s (site=%s)", url, site_name)

    try:
        if "#" in url:
            # hash 路由（如米哈游）连续 goto 仅 fragment 变化时，Vue Router 可能不重新渲染，
            # 导致 JD 串岗。经 about:blank 完全脱离文档后再加载，强制完整渲染。
            await page.goto("about:blank")
            await page.wait_for_timeout(300)
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        logger.warning("Page goto failed: %s -> %s", url, e)
        return None

    # hash 路由页面（URL 包含 #）需要额外等待内容加载
    if "#" in url:
        await page.wait_for_timeout(2500)

    await wait_for_load(page, timeout=10000)

    # HITL 检测
    block_result = await hitl.check_and_pause(page)
    if block_result:
        # 用户处理完后，重新等待加载
        await wait_for_load(page, timeout=10000)
        if "#" in url:
            await page.wait_for_timeout(1500)

    # 构造基础 posting（用于适配器提取）
    base_posting = JobPosting(
        title=job_title or url,
        detail_url=url,
        site_name=site_name,
    )

    # 策略1：专用站点适配器
    adapter_cls = get_adapter(site_name)
    if adapter_cls:
        from src.search.site_registry import get_site_config
        config = get_site_config(site_name)
        if config:
            adapter = adapter_cls(config)
            detail = await adapter.extract_jd_detail(page, base_posting)
            if detail:
                logger.info("JD fetched via adapter %s: %s | jd_len=%d",
                            adapter_cls.__name__, detail.posting.title, len(detail.full_jd))
                return detail
            logger.info("Adapter returned None, falling back to generic extraction")

    # 策略2：通用提取
    # 提取元信息
    meta = await _extract_meta(page)

    # 提取完整 JD 文本
    full_text = await _extract_page_text(page)
    if not full_text or len(full_text) < 20:
        logger.warning("JD text too short: %s (len=%d)", url, len(full_text))
        # 再等一下重试
        await page.wait_for_timeout(2000)
        full_text = await _extract_page_text(page)

    responsibilities, requirements = _split_jd(full_text)

    posting = JobPosting(
        title=meta["title"] or url,
        company="",
        location=meta.get("location", ""),
        detail_url=url,
        site_name=site_name,
    )

    detail = JobDetail(
        posting=posting,
        full_jd=full_text,
        responsibilities=responsibilities,
        requirements=requirements,
        salary=meta.get("salary", ""),
        location=meta.get("location", ""),
        apply_url=url,
    )

    logger.info("JD fetched (generic): %s | title=%s | jd_len=%d", url, meta["title"], len(full_text))
    return detail


async def run(state: AgentState) -> AgentState:
    """LangGraph 节点：抓取 JD 详情。

    优先级：
    1. state.job_urls（手动指定的 URL，跳过发现/初筛）
    2. state.screened_jobs（通过标题初筛的岗位）
    """
    browser = await get_browser()
    page = browser.page

    urls_to_fetch: list[tuple[str, str, str]] = []  # (url, site_name, job_title)

    if state.job_urls:
        for url in state.job_urls:
            urls_to_fetch.append((url, state.site_name or "manual", ""))
    elif state.screened_jobs:
        for job in state.screened_jobs:
            urls_to_fetch.append((job.detail_url, job.site_name, job.title))
    elif state.discovered_jobs:
        # 没有初筛结果时，对所有发现的岗位抓取（MVP 场景）
        for job in state.discovered_jobs:
            urls_to_fetch.append((job.detail_url, job.site_name, job.title))

    if not urls_to_fetch:
        state.add_error("fetch_jd", "没有可抓取的岗位 URL")
        return state

    logger.info("Fetching %d job details...", len(urls_to_fetch))

    details: list[JobDetail] = []
    for url, site_name, job_title in urls_to_fetch:
        try:
            detail = await fetch_single_jd(page, url, site_name, job_title)
            if detail:
                details.append(detail)
            else:
                state.add_error("fetch_jd", f"JD 抓取失败: {url}")
        except Exception as e:
            state.add_error("fetch_jd", f"{url}: {e}")
            logger.exception("fetch_single_jd error: %s", url)

    state.job_details = details
    logger.info("JD fetch complete: %d/%d succeeded", len(details), len(urls_to_fetch))
    return state
