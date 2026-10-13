"""中兴新云招聘站点适配器。

category_url: http://www.ztccloud.com.cn/careers.html

说明：
- careers.html 为传统静态/半动态招聘页，采用分页（点击"下一页"）模式。
- 站点结构未经浏览器实测，采用「主 selector + 通用 <a> 标签扫描兜底」策略。
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
class ZtccloudAdapter(SiteAdapter):
    """中兴新云招聘适配器（分页模式）。"""

    site_name = "ztccloud"
    company_name = "中兴新云"
    category_url = "http://www.ztccloud.com.cn/careers.html"

    # 中小厂岗位较少，降低阈值
    max_pages = 30
    scroll_pause_ms = 1200
    no_new_threshold = 3
    max_jobs_hard_limit = 300

    # 候选岗位卡片 selector（按优先级尝试，未经实测）
    CARD_SELECTORS = [
        "a[href*='/careers/']", "a[href*='/job']", "a[href*='/position']",
        "a[href*='/detail']", ".job-item", ".list-item", ".news-list li a",
        "[class*='job-list'] a", "[class*='recruit'] a",
    ]

    # "下一页"按钮候选 selector
    NEXT_PAGE_SELECTORS = [
        "a.next", "li.next a", "a[rel='next']",
        ".pagination .next", ".page-next", "a:has-text('下一页')",
    ]

    # 岗位链接 URL 模式（通用兜底扫描）
    JOB_URL_PATTERNS = [
        re.compile(r"/(careers?|jobs?|position|detail|post|vacancy)/", re.I),
        re.compile(r"[?&](id|jobId|positionId)=\d+", re.I),
    ]
    EXCLUDE_URL_FRAGMENTS = [
        "/home", "/about", "/contact", "/#", "javascript:", "mailto:",
        "careers.html$",
    ]
    TITLE_KEYWORDS = [
        "工程师", "开发", "算法", "研究员", "设计师", "产品", "运营",
        "经理", "主管", "专员", "助理", "架构师", "测试", "运维",
        "HR", "人力", "财务", "市场", "销售", "顾问", "实习", "会计",
    ]

    def __init__(self, config: SiteConfig):
        super().__init__(config)

    # ============================================================
    # 岗位发现（分页模式）
    # ============================================================

    async def discover_jobs(self, page: Page) -> List[JobPosting]:
        """点击"下一页"翻页发现岗位。"""
        logger.info("Ztccloud adapter: discovering jobs (pagination mode) from %s", page.url)

        all_jobs: List[JobPosting] = []
        seen_urls: set[str] = set()
        consecutive_empty = 0

        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1200)

        for page_idx in range(self.max_pages):
            batch = await self._extract_jobs(page, seen_urls)

            if batch:
                all_jobs.extend(batch)
                for job in batch:
                    seen_urls.add(job.detail_url)
                consecutive_empty = 0
                logger.info("Page %d: +%d new jobs (total %d)",
                            page_idx + 1, len(batch), len(all_jobs))
            else:
                consecutive_empty += 1
                logger.info("Page %d: no new jobs (consecutive %d)",
                            page_idx + 1, consecutive_empty)

            if len(all_jobs) >= self.max_jobs_hard_limit:
                logger.info("Reached hard limit %d, stopping", self.max_jobs_hard_limit)
                break
            if consecutive_empty >= self.no_new_threshold:
                logger.info("%d consecutive empty pages, stopping", self.no_new_threshold)
                break

            has_next = await self._go_to_next_page(page)
            if not has_next:
                logger.info("No more pages, stopping")
                break

        logger.info("Ztccloud adapter: discovered %d jobs from %d pages",
                    len(all_jobs), page_idx + 1)
        return self._dedup_jobs(all_jobs)

    async def _go_to_next_page(self, page: Page) -> bool:
        for sel in self.NEXT_PAGE_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.count() == 0:
                    continue
                old_first = await self._first_job_url(page)
                await btn.click()
                await page.wait_for_timeout(1500)
                await page.wait_for_load_state("domcontentloaded")
                try:
                    await page.wait_for_function(
                        """(oldUrl) => {
                            const links = Array.from(document.querySelectorAll('a[href]'))
                                .map(a => a.getAttribute('href') || '');
                            return links.some(h => h && h !== oldUrl && /(careers?|jobs?|position|detail)/i.test(h));
                        }""",
                        arg=old_first,
                        timeout=8000,
                    )
                except Exception:
                    pass
                await page.wait_for_timeout(400)
                return True
            except Exception:
                continue
        return False

    async def _first_job_url(self, page: Page) -> str:
        for sel in self.CARD_SELECTORS:
            try:
                cards = await page.query_selector_all(sel)
                if cards:
                    href = await cards[0].get_attribute("href")
                    if href:
                        return href
            except Exception:
                continue
        return ""

    async def _extract_jobs(self, page: Page, seen_urls: set[str]) -> List[JobPosting]:
        jobs: List[JobPosting] = []
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
        return await self._extract_all_anchors(page, seen_urls)

    async def _extract_all_anchors(self, page: Page, seen_urls: set[str]) -> List[JobPosting]:
        jobs: List[JobPosting] = []
        try:
            anchors = await page.query_selector_all("a[href]")
        except Exception as e:
            logger.warning("Ztccloud: query anchors failed: %s", e)
            return jobs

        for a in anchors:
            try:
                href = await a.get_attribute("href")
                if not href or self._is_excluded_url(href):
                    continue
                text = re.sub(r"\s+", " ", (await a.inner_text()).strip())
                if not text or len(text) < 4 or len(text) > 80:
                    continue
                if self._is_noise_title(text):
                    continue
                if not (self._looks_like_job_url(href) or self._looks_like_job_title(text)):
                    continue
                job = self._make_job_posting(title=text, detail_url=href, company=self.company_name)
                if job and job.detail_url not in seen_urls:
                    jobs.append(job)
            except Exception:
                continue
        return jobs

    async def _extract_from_anchor(self, card: ElementHandle) -> Optional[JobPosting]:
        href = await card.get_attribute("href")
        if not href:
            return None
        text = re.sub(r"\s+", " ", (await card.inner_text()).strip())
        if not text:
            return None
        title = text.split("\n")[0].strip()
        if not title or self._is_noise_title(title):
            return None
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        location = lines[1] if len(lines) >= 2 else ""
        return self._make_job_posting(
            title=title, detail_url=href,
            company=self.company_name, location=location,
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
        "h1", "h2", ".job-title", ".position-title", ".detail-title", ".news-title",
        "[class*='job-title']", "[class*='position-title']", "[class*='detail-title']",
    ]
    JD_CONTENT_SELECTORS = [
        ".job-detail", ".position-detail", ".detail-content", ".news-content", ".job-content",
        "[class*='job-detail']", "[class*='position-detail']", "[class*='detail-content']",
        "[class*='news-content']", "[class*='description']", "article", "main",
    ]
    JD_META_SELECTORS = [
        ".job-meta", ".position-meta", ".job-info", ".detail-info",
        "[class*='job-meta']", "[class*='meta']",
    ]
    RESP_KEYWORDS = ["岗位职责", "工作职责", "工作内容", "岗位描述", "职位描述", "职位职责"]
    REQ_KEYWORDS = ["任职要求", "岗位要求", "任职资格", "资格要求", "职位要求", "招聘要求"]

    async def extract_jd_detail(self, page: Page, posting: JobPosting) -> Optional[JobDetail]:
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
                title=title, company=self.company_name, location=location,
                detail_url=posting.detail_url, category_path=posting.category_path,
                site_name=self.config.name,
            )
            detail = JobDetail(
                posting=enhanced, full_jd=full_text,
                responsibilities=responsibilities, requirements=requirements,
                location=location, apply_url=posting.detail_url,
            )
            logger.info("Ztccloud JD extracted: %s | jd_len=%d", title, len(full_text))
            return detail
        except Exception as e:
            logger.warning("Ztccloud extract_jd_detail failed: %s", e)
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
