"""阿里巴巴/阿里云校招站点适配器。

category_url: https://campus-talent.alibaba.com/campus/index
- 阿里校招（campus-talent.alibaba.com）
- 列表为 SPA，岗位卡片滚动加载
- 岗位链接通常形如 /campus/positionDetail?positionId=xxx
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
class AlibabaAdapter(SiteAdapter):
    """阿里巴巴校招适配器（SPA 滚动加载）。"""

    site_name = "alibaba"
    company_name = "阿里巴巴"
    category_url = "https://campus-talent.alibaba.com/campus/index"

    max_pages = 80
    scroll_pause_ms = 1500
    no_new_threshold = 5
    max_jobs_hard_limit = 500

    # 岗位卡片候选 selector（按优先级尝试，命中即用）
    CARD_SELECTORS = [
        "a[href*='positionDetail']",
        "a[href*='positionId']",
        "a[href*='/position/']",
        "[class*='job-card']",
        "[class*='position-item']",
        "[class*='job-item']",
        "[class*='recruit-item']",
    ]

    # 卡片内标题候选 selector
    TITLE_SELECTORS = [
        "[class*='job-title']", "[class*='position-title']",
        "[class*='jobName']", "[class*='positionName']",
        "h3", "h4", "[class*='title']",
    ]

    # 卡片内元信息候选 selector（地点/团队/类别）
    META_SELECTORS = [
        "[class*='job-meta']", "[class*='position-meta']",
        "[class*='job-info']", "[class*='position-info']",
        "[class*='meta']", "[class*='info']",
    ]

    # JD 正文容器候选 selector
    JD_CONTENT_SELECTORS = [
        "[class*='job-detail']", "[class*='position-detail']",
        "[class*='job-content']", "[class*='position-content']",
        "[class*='job-description']", "[class*='jd-content']",
        "[class*='description']", "article", "main",
    ]

    # JD 标题候选 selector
    JD_TITLE_SELECTORS = [
        "h1", "[class*='job-title']", "[class*='position-title']",
        "[class*='jobName']", "[class*='positionName']",
    ]

    # 岗位职责关键词
    RESP_KEYWORDS = ["岗位职责", "工作职责", "工作内容", "岗位描述", "职位描述", "职位职责", "我们希望你做"]
    # 任职要求关键词
    REQ_KEYWORDS = ["任职要求", "岗位要求", "任职资格", "资格要求", "职位要求", "招聘要求", "我们希望你"]

    def __init__(self, config: SiteConfig):
        super().__init__(config)

    # ============================================================
    # 岗位发现（SPA 滚动加载）
    # ============================================================

    async def discover_jobs(self, page: Page) -> List[JobPosting]:
        """滚动加载模式：循环滚动 + 提取直到无新岗位。"""
        logger.info("Alibaba adapter: discovering jobs (scroll mode) from %s", page.url)

        all_jobs: List[JobPosting] = []
        seen_urls: set[str] = set()
        consecutive_no_new = 0

        for step in range(self.max_pages):
            await self._wait_for_cards(page)

            batch = await self._extract_visible_jobs(page, seen_urls)

            if batch:
                all_jobs.extend(batch)
                for job in batch:
                    seen_urls.add(job.detail_url)
                consecutive_no_new = 0
                logger.info("Scroll step %d: +%d new jobs (total %d)",
                            step + 1, len(batch), len(all_jobs))
            else:
                consecutive_no_new += 1
                logger.info("Scroll step %d: no new jobs (consecutive %d)",
                            step + 1, consecutive_no_new)

            if len(all_jobs) >= self.max_jobs_hard_limit:
                logger.info("Reached hard limit %d, stopping", self.max_jobs_hard_limit)
                break

            if consecutive_no_new >= self.no_new_threshold:
                logger.info("%d consecutive no-new steps, stopping", self.no_new_threshold)
                break

            await self._scroll_page(page)

        all_jobs = self._dedup_jobs(all_jobs)
        logger.info("Alibaba adapter: discovered %d jobs after %d scroll steps",
                    len(all_jobs), step + 1)
        return all_jobs

    async def _wait_for_cards(self, page: Page) -> None:
        try:
            for sel in self.CARD_SELECTORS:
                try:
                    await page.wait_for_selector(sel, timeout=3000)
                    break
                except Exception:
                    continue
            await page.wait_for_timeout(600)
        except Exception:
            logger.debug("Wait for cards timeout")

    async def _extract_visible_jobs(self, page: Page, seen_urls: set[str]) -> List[JobPosting]:
        jobs: List[JobPosting] = []
        cards: List[ElementHandle] = []
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
                logger.debug("Failed to extract card: %s", e)
                continue
        return jobs

    async def _extract_from_card(self, card: ElementHandle) -> Optional[JobPosting]:
        href = await card.get_attribute("href")
        if not href:
            inner = await card.query_selector("a[href]")
            if inner:
                href = await inner.get_attribute("href")
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
        for sel in self.TITLE_SELECTORS:
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
                    meta_text = lines[1]
            except Exception:
                pass

        if not meta_text:
            return "", ""

        parts = [p.strip() for p in meta_text.replace("|", "·").split("·") if p.strip()]
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
            location, category_path = await self._extract_jd_meta(page)
            if not location:
                location = posting.location

            full_text = await self._extract_jd_content(page)
            if not full_text or len(full_text) < 20:
                await page.wait_for_timeout(2000)
                full_text = await self._extract_jd_content(page)

            responsibilities, requirements = self._split_jd_text(full_text)

            enhanced = JobPosting(
                title=title,
                company=self.company_name,
                location=location,
                detail_url=posting.detail_url,
                category_path=category_path or posting.category_path,
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
            logger.info("Alibaba JD extracted: %s | jd_len=%d", title, len(full_text))
            return detail
        except Exception as e:
            logger.warning("Alibaba extract_jd_detail failed: %s", e)
            return None

    async def _extract_jd_title(self, page: Page) -> str:
        for sel in self.JD_TITLE_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if text and 2 < len(text) < 100 and text not in ("校园招聘", "职位详情", "岗位详情"):
                        return text
            except Exception:
                continue
        return ""

    async def _extract_jd_meta(self, page: Page) -> tuple[str, str]:
        for sel in self.META_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if text and len(text) < 200:
                        return self._parse_meta_text(text)
            except Exception:
                continue
        try:
            body_text = await page.locator("body").inner_text()
            lines = [l.strip() for l in body_text.split("\n") if l.strip()]
            for line in lines[:30]:
                if any(c in line for c in ["北京", "上海", "深圳", "广州", "杭州", "成都"]) and ("·" in line or "|" in line):
                    return self._parse_meta_text(line)
        except Exception:
            pass
        return "", ""

    def _parse_meta_text(self, text: str) -> tuple[str, str]:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) == 1:
            parts = [p.strip() for p in lines[0].replace("|", "·").split("·") if p.strip()]
            if not parts:
                return lines[0], ""
            return parts[0], " / ".join(parts[1:]) if len(parts) > 1 else ""
        if len(lines) >= 2:
            return lines[0], " / ".join(lines[1:])
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
