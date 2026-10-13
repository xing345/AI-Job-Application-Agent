"""百川智能招聘站点适配器。

category_url: https://careers.baichuan-inc.com/origin-program

说明：
- 百川智能为中小型 AI 公司，岗位数量有限，采用滚动加载模式。
- 站点结构未经浏览器实测，采用「主 selector + 通用 <a> 标签扫描兜底」策略：
  1. 优先用常见岗位卡片 selector 提取；
  2. 失败/无结果时遍历所有 <a> 标签，按 URL 模式 + 标题启发式过滤出岗位链接。
- 所有 selector 需后续在真实浏览器中验证校准。
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from playwright.async_api import ElementHandle, Page

from src.models.job import JobDetail, JobPosting
from src.search.adapters.base import SiteAdapter, register_adapter
from src.search.site_registry import SiteConfig

logger = logging.getLogger(__name__)


@register_adapter
class BaichuanAdapter(SiteAdapter):
    """百川智能招聘适配器（滚动加载模式）。"""

    site_name = "baichuan"
    company_name = "百川智能"
    category_url = "https://careers.baichuan-inc.com/origin-program"

    # 中小厂岗位较少，降低阈值
    max_pages = 30
    scroll_pause_ms = 1500
    no_new_threshold = 4
    max_jobs_hard_limit = 300

    # 候选岗位卡片 selector（按优先级尝试，未经实测）
    CARD_SELECTORS = [
        "a[href*='/position']", "a[href*='/job']", "a[href*='/detail']",
        "a[href*='/recruit']", ".job-item", ".position-item",
        "[class*='job-card']", "[class*='position-item']",
    ]

    # 岗位链接 URL 模式（通用兜底扫描时使用）
    JOB_URL_PATTERNS = [
        re.compile(r"/(position|job|detail|recruit|post|vacancy)/", re.I),
        re.compile(r"[?&](id|jobId|positionId)=\d+", re.I),
    ]
    # 明确排除的导航/噪声 URL 片段
    EXCLUDE_URL_FRAGMENTS = [
        "/home", "/about", "/contact", "/campus", "/jobs$", "/#",
        "javascript:", "mailto:", "weixin.qq.com",
    ]

    # 标题启发式关键词（用于通用兜底时判断文本是否像岗位名）
    TITLE_KEYWORDS = [
        "工程师", "开发", "算法", "研究员", "设计师", "产品", "运营",
        "经理", "主管", "专员", "助理", "架构师", "测试", "运维",
        "HR", "人力", "财务", "市场", "销售", "顾问", "实习",
    ]

    def __init__(self, config: SiteConfig):
        super().__init__(config)

    # ============================================================
    # 岗位发现（滚动加载模式）
    # ============================================================

    async def discover_jobs(self, page: Page) -> List[JobPosting]:
        """滚动加载发现岗位。"""
        logger.info("Baichuan adapter: discovering jobs (scroll mode) from %s", page.url)

        all_jobs: List[JobPosting] = []
        seen_urls: set[str] = set()
        no_new_count = 0

        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1500)

        for round_idx in range(self.max_pages):
            batch = await self._extract_jobs(page, seen_urls)

            if batch:
                all_jobs.extend(batch)
                for job in batch:
                    seen_urls.add(job.detail_url)
                no_new_count = 0
                logger.info("Round %d: +%d new jobs (total %d)",
                            round_idx + 1, len(batch), len(all_jobs))
            else:
                no_new_count += 1
                logger.info("Round %d: no new jobs (consecutive %d)",
                            round_idx + 1, no_new_count)

            if len(all_jobs) >= self.max_jobs_hard_limit:
                logger.info("Reached hard limit %d, stopping", self.max_jobs_hard_limit)
                break

            if no_new_count >= self.no_new_threshold:
                logger.info("%d consecutive rounds with no new jobs, stopping",
                            self.no_new_threshold)
                break

            # 滚动触发懒加载
            await self._scroll_page(page)

        logger.info("Baichuan adapter: discovered %d jobs after %d rounds",
                    len(all_jobs), round_idx + 1)
        return self._dedup_jobs(all_jobs)

    async def _extract_jobs(self, page: Page, seen_urls: set[str]) -> List[JobPosting]:
        """提取当前可见区域的岗位：先尝试卡片 selector，失败则通用扫描 <a>。"""
        jobs: List[JobPosting] = []

        # 1. 优先尝试候选卡片 selector
        for sel in self.CARD_SELECTORS:
            try:
                cards = await page.query_selector_all(sel)
            except Exception:
                cards = []
            if not cards:
                continue
            for card in cards:
                job = await self._extract_from_anchor(card)
                if job and job.detail_url not in seen_urls:
                    jobs.append(job)
            if jobs:
                return jobs

        # 2. 兜底：通用扫描所有带 href 的 <a>
        jobs = await self._extract_all_anchors(page, seen_urls)
        return jobs

    async def _extract_all_anchors(self, page: Page, seen_urls: set[str]) -> List[JobPosting]:
        """通用兜底：遍历所有 <a href>，按 URL 模式 + 标题启发式过滤。"""
        jobs: List[JobPosting] = []
        try:
            anchors = await page.query_selector_all("a[href]")
        except Exception as e:
            logger.warning("Baichuan: query anchors failed: %s", e)
            return jobs

        for a in anchors:
            try:
                href = await a.get_attribute("href")
                if not href:
                    continue
                if self._is_excluded_url(href):
                    continue

                text = (await a.inner_text()).strip()
                text = re.sub(r"\s+", " ", text)
                if not text or len(text) < 4 or len(text) > 80:
                    continue
                if self._is_noise_title(text):
                    continue

                # 必须命中岗位 URL 模式，或标题像岗位名
                if not (self._looks_like_job_url(href) or self._looks_like_job_title(text)):
                    continue

                job = self._make_job_posting(
                    title=text,
                    detail_url=href,
                    company=self.company_name,
                )
                if job and job.detail_url not in seen_urls:
                    jobs.append(job)
            except Exception:
                continue

        return jobs

    async def _extract_from_anchor(self, card: ElementHandle) -> Optional[JobPosting]:
        """从单个 <a> 卡片元素提取岗位。"""
        href = await card.get_attribute("href")
        if not href:
            return None
        text = (await card.inner_text()).strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            return None

        # 标题取第一行
        title = text.split("\n")[0].strip()
        if not title or self._is_noise_title(title):
            return None

        # 元信息（地点等）取后续行
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        location = lines[1] if len(lines) >= 2 else ""

        return self._make_job_posting(
            title=title,
            detail_url=href,
            company=self.company_name,
            location=location,
        )

    def _is_excluded_url(self, href: str) -> bool:
        low = href.lower()
        if low.startswith(("javascript:", "mailto:", "#")):
            return True
        return any(frag in low for frag in self.EXCLUDE_URL_FRAGMENTS)

    def _looks_like_job_url(self, href: str) -> bool:
        return any(pat.search(href) for pat in self.JOB_URL_PATTERNS)

    def _looks_like_job_title(self, text: str) -> bool:
        return any(kw in text for kw in self.TITLE_KEYWORDS)

    # ============================================================
    # JD 详情页提取
    # ============================================================

    JD_TITLE_SELECTORS = [
        "h1", "h2", ".job-title", ".position-title",
        "[class*='job-title']", "[class*='position-title']",
        "[class*='detail-title']", "[class*='jobName']",
    ]
    JD_CONTENT_SELECTORS = [
        ".job-detail", ".position-detail", ".job-content", ".position-content",
        "[class*='job-detail']", "[class*='position-detail']",
        "[class*='jd-content']", "[class*='description']",
        "article", "main",
    ]
    JD_META_SELECTORS = [
        ".job-meta", ".position-meta", ".job-info", ".position-info",
        "[class*='job-meta']", "[class*='position-meta']", "[class*='meta']",
    ]
    RESP_KEYWORDS = ["岗位职责", "工作职责", "工作内容", "岗位描述", "职位描述", "职位职责", "你将做什么"]
    REQ_KEYWORDS = ["任职要求", "岗位要求", "任职资格", "资格要求", "我们希望你", "职位要求", "招聘要求"]

    async def extract_jd_detail(self, page: Page, posting: JobPosting) -> Optional[JobDetail]:
        """JD 详情页结构化提取。"""
        try:
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(800)

            title = await self._extract_jd_title(page) or posting.title
            location = await self._extract_jd_meta(page) or posting.location
            full_text = await self._extract_jd_content(page)

            if not full_text or len(full_text) < 20:
                await page.wait_for_timeout(1500)
                full_text = await self._extract_jd_content(page)

            responsibilities, requirements = self._split_jd_text(full_text)

            enhanced = JobPosting(
                title=title,
                company=self.company_name,
                location=location,
                detail_url=posting.detail_url,
                category_path=posting.category_path,
                site_name=self.config.name,
            )
            detail = JobDetail(
                posting=enhanced,
                full_jd=full_text,
                responsibilities=responsibilities,
                requirements=requirements,
                location=location,
                apply_url=posting.detail_url,
            )
            logger.info("Baichuan JD extracted: %s | jd_len=%d", title, len(full_text))
            return detail
        except Exception as e:
            logger.warning("Baichuan extract_jd_detail failed: %s", e)
            return None

    async def _extract_jd_title(self, page: Page) -> str:
        for sel in self.JD_TITLE_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if text and 2 < len(text) < 100 and text not in ("校园招聘", "社会招聘", "职位详情"):
                        return text
            except Exception:
                continue
        return ""

    async def _extract_jd_meta(self, page: Page) -> str:
        for sel in self.JD_META_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if text and len(text) < 200:
                        # 取第一行作为地点
                        return text.split("\n")[0].strip()
            except Exception:
                continue
        return ""

    async def _extract_jd_content(self, page: Page) -> str:
        candidates = []
        for sel in self.JD_CONTENT_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if len(text) > 50:
                        has_kw = any(kw in text for kw in self.RESP_KEYWORDS + self.REQ_KEYWORDS)
                        candidates.append((has_kw, len(text), text))
            except Exception:
                continue
        if candidates:
            with_kw = [c for c in candidates if c[0]]
            pool = with_kw if with_kw else candidates
            pool.sort(key=lambda x: x[1], reverse=True)
            return pool[0][2]
        try:
            return (await page.locator("body").inner_text()).strip()
        except Exception:
            return ""

    def _split_jd_text(self, full_text: str) -> tuple[str, str]:
        responsibilities = ""
        requirements = ""

        req_pos = -1
        for kw in self.REQ_KEYWORDS:
            idx = full_text.find(kw)
            if idx >= 0 and (req_pos < 0 or idx < req_pos):
                req_pos = idx

        resp_pos = -1
        for kw in self.RESP_KEYWORDS:
            idx = full_text.find(kw)
            if idx >= 0 and (resp_pos < 0 or idx < resp_pos):
                resp_pos = idx

        if req_pos >= 0:
            requirements = full_text[req_pos:].strip()
            if resp_pos >= 0 and resp_pos < req_pos:
                responsibilities = full_text[resp_pos:req_pos].strip()
            else:
                responsibilities = full_text[:req_pos].strip()
        elif resp_pos >= 0:
            responsibilities = full_text[resp_pos:].strip()

        return responsibilities, requirements
