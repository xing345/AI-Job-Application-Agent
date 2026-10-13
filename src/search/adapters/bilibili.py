"""哔哩哔哩校招站点适配器。

列表页: https://jobs.bilibili.com/campus/positions
模式: SPA 滚动加载
岗位链接格式: /campus/positions/{id} 或 /position/{id}
"""
from __future__ import annotations

import logging
from typing import List, Optional

from playwright.async_api import ElementHandle, Page

from src.models.job import JobDetail, JobPosting
from src.search.adapters.base import SiteAdapter, register_adapter
from src.search.site_registry import SiteConfig

logger = logging.getLogger(__name__)


@register_adapter
class BilibiliAdapter(SiteAdapter):
    """哔哩哔哩校招适配器（SPA 滚动加载）。"""

    site_name = "bilibili"
    company_name = "哔哩哔哩"

    max_pages = 80
    scroll_pause_ms = 1500
    no_new_threshold = 5
    max_jobs_hard_limit = 500

    # 岗位卡片候选 selector
    CARD_SELECTORS = [
        "a[href*='/campus/positions/']",
        "a[href*='/position/']",
        "a[href*='/jobs/']",
        ".position-list .position-item a",
        ".job-list .job-item a",
        "[class*='position-item'] a",
        "[class*='job-item'] a",
    ]

    # 卡片内标题 selector
    TITLE_SELECTORS = [
        ".position-title", ".job-title", ".title",
        "[class*='position-name']", "[class*='job-name']",
        "[class*='title']", "h3", "h2", "div:first-child",
    ]

    # 卡片内元信息 selector
    META_SELECTORS = [
        ".position-meta", ".job-meta", ".info",
        "[class*='meta']", "[class*='info']", "div:last-child",
    ]

    # JD 详情页 selector
    JD_TITLE_SELECTORS = [
        "h1", ".position-title", ".job-title",
        "[class*='position-name']", "[class*='job-title']",
        "[class*='job-name']",
    ]

    JD_CONTENT_SELECTORS = [
        ".position-detail", ".job-detail", ".position-content",
        "[class*='position-detail']", "[class*='job-detail']",
        "[class*='jd-content']", "[class*='description']",
        ".job-desc", "article", "main",
    ]

    RESP_KEYWORDS = ["岗位职责", "工作职责", "工作内容", "岗位描述", "职位描述", "职位职责", "工作内容："]
    REQ_KEYWORDS = ["任职要求", "岗位要求", "任职资格", "资格要求", "我们希望你", "职位要求", "招聘要求", "我们期待"]

    def __init__(self, config: SiteConfig):
        super().__init__(config)

    async def discover_jobs(self, page: Page) -> List[JobPosting]:
        """滚动加载模式。"""
        logger.info("Bilibili adapter: discovering jobs (scroll mode) from %s", page.url)

        all_jobs: List[JobPosting] = []
        seen_urls: set[str] = set()
        no_new_streak = 0

        await self._wait_for_cards(page)

        for round_idx in range(self.max_pages):
            batch = await self._extract_visible_jobs(page, seen_urls)

            if batch:
                all_jobs.extend(batch)
                for job in batch:
                    seen_urls.add(job.detail_url)
                no_new_streak = 0
                logger.info("Scroll round %d: +%d new jobs (total %d)",
                            round_idx + 1, len(batch), len(all_jobs))
            else:
                no_new_streak += 1
                logger.info("Scroll round %d: no new jobs (streak %d)",
                            round_idx + 1, no_new_streak)

            if len(all_jobs) >= self.max_jobs_hard_limit:
                logger.info("Reached hard limit %d, stopping", self.max_jobs_hard_limit)
                break

            if no_new_streak >= self.no_new_threshold:
                logger.info("%d consecutive rounds with no new jobs, stopping",
                            self.no_new_threshold)
                break

            await self._scroll_page(page)

        logger.info("Bilibili adapter: discovered %d jobs after %d rounds",
                    len(all_jobs), round_idx + 1)
        return self._dedup_jobs(all_jobs)

    async def _wait_for_cards(self, page: Page) -> None:
        for sel in self.CARD_SELECTORS:
            try:
                await page.wait_for_selector(sel, timeout=8000)
                await page.wait_for_timeout(800)
                return
            except Exception:
                continue
        logger.debug("Bilibili: no card selector matched after wait")

    async def _extract_visible_jobs(self, page: Page, seen_urls: set[str]) -> List[JobPosting]:
        jobs: List[JobPosting] = []
        cards = []
        for sel in self.CARD_SELECTORS:
            try:
                found = await page.query_selector_all(sel)
                if found:
                    cards = found
                    break
            except Exception:
                continue

        for card in cards:
            try:
                job = await self._extract_from_card(card)
                if job and job.detail_url not in seen_urls:
                    jobs.append(job)
            except Exception as e:
                logger.debug("Bilibili card extract failed: %s", e)
                continue
        return jobs

    async def _extract_from_card(self, card: ElementHandle) -> Optional[JobPosting]:
        href = await card.get_attribute("href")
        if not href:
            return None

        title = await self._extract_title(card)
        if not title or self._is_noise_title(title):
            return None

        location, category_path = await self._extract_meta(card)

        return self._make_job_posting(
            title=title,
            detail_url=href,
            company=self.company_name,
            location=location,
            category_path=category_path,
        )

    async def _extract_title(self, card: ElementHandle) -> str:
        for sel in self.TITLE_SELECTORS[:-1]:
            try:
                el = await card.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text and 1 < len(text) < 100:
                        return text
            except Exception:
                continue
        try:
            full_text = (await card.inner_text()).strip()
            if full_text:
                first_line = full_text.split("\n")[0].strip()
                if first_line and len(first_line) > 1:
                    return first_line
        except Exception:
            pass
        return ""

    async def _extract_meta(self, card: ElementHandle) -> tuple[str, str]:
        meta_text = ""
        for sel in self.META_SELECTORS:
            try:
                el = await card.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text and len(text) < 200:
                        meta_text = text
                        break
            except Exception:
                continue

        if not meta_text:
            try:
                full_text = (await card.inner_text()).strip()
                lines = [l.strip() for l in full_text.split("\n") if l.strip()]
                if len(lines) >= 2:
                    meta_text = lines[-1]
            except Exception:
                pass

        if not meta_text:
            return "", ""

        parts = [p.strip() for p in meta_text.replace("|", "·").replace("｜", "·").split("·") if p.strip()]
        if not parts:
            parts = [meta_text]
        location = parts[0]
        category_path = " / ".join(parts[1:]) if len(parts) > 1 else ""
        return location, category_path

    # ============================================================
    # JD 详情页提取
    # ============================================================

    async def extract_jd_detail(self, page: Page, posting: JobPosting) -> Optional[JobDetail]:
        try:
            title = await self._extract_jd_title(page) or posting.title
            location = posting.location

            full_text = await self._extract_jd_content(page)
            if not full_text or len(full_text) < 20:
                await page.wait_for_timeout(2000)
                full_text = await self._extract_jd_content(page)

            jd_location, _ = await self._extract_jd_meta(page)
            if jd_location:
                location = jd_location

            responsibilities, requirements = self._split_jd_text(full_text)

            enhanced_posting = JobPosting(
                title=title,
                company=self.company_name,
                location=location,
                detail_url=posting.detail_url,
                category_path=posting.category_path,
                site_name=self.config.name,
            )

            detail = JobDetail(
                posting=enhanced_posting,
                full_jd=full_text,
                responsibilities=responsibilities,
                requirements=requirements,
                location=location,
                apply_url=posting.detail_url,
            )
            logger.info("Bilibili JD extracted: %s | jd_len=%d", title, len(full_text))
            return detail
        except Exception as e:
            logger.warning("Bilibili extract_jd_detail failed: %s", e)
            return None

    async def _extract_jd_title(self, page: Page) -> str:
        for sel in self.JD_TITLE_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if text and 2 < len(text) < 100:
                        if text not in ("校园招聘", "社会招聘", "职位详情", "岗位详情"):
                            return text
            except Exception:
                continue
        return ""

    async def _extract_jd_meta(self, page: Page) -> tuple[str, str]:
        meta_selectors = [
            ".position-meta", ".job-meta", "[class*='position-meta']",
            "[class*='position-info']", "[class*='meta']",
        ]
        for sel in meta_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if text and len(text) < 200:
                        parts = [p.strip() for p in text.replace("|", "·").replace("｜", "·").split("·") if p.strip()]
                        if parts:
                            return parts[0], " / ".join(parts[1:]) if len(parts) > 1 else ""
            except Exception:
                continue
        return "", ""

    async def _extract_jd_content(self, page: Page) -> str:
        candidates = []
        for sel in self.JD_CONTENT_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if len(text) > 50:
                        has_kw = any(kw in text for kw in self.RESP_KEYWORDS + self.REQ_KEYWORDS)
                        candidates.append((has_kw, len(text), text, sel))
            except Exception:
                continue

        if candidates:
            with_kw = [c for c in candidates if c[0]]
            if with_kw:
                with_kw.sort(key=lambda x: x[1], reverse=True)
                return with_kw[0][2]
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][2]

        try:
            body = await page.locator("body").inner_text()
            return body.strip()
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
