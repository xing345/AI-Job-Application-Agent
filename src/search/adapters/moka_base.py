"""Moka 招聘平台基类适配器。

Moka 招聘系统（mokahr.com）页面结构：
- URL 格式：https://app.mokahr.com/campus-recruitment/{company}/{id}#/jobs
- 列表页：hash 路由 SPA，岗位卡片列表
- 卡片结构：标题 + 地点 + 部门 + 职位类型
- 详情页：hash 路由 #/jobs/{jobId} 或 modal
- 分页：滚动加载或"加载更多"

子类只需设置 site_name / company_name / 具体 URL。
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Set

from playwright.async_api import ElementHandle, Page

from src.models.job import JobDetail, JobPosting
from src.search.adapters.base import SiteAdapter
from src.search.site_registry import SiteConfig

logger = logging.getLogger(__name__)


class MokaBaseAdapter(SiteAdapter):
    """Moka 招聘平台基类。

    所有使用 Moka 招聘系统的公司适配器继承此类。
    """

    site_name = ""
    company_name = ""

    max_pages = 80
    scroll_pause_ms = 1500
    no_new_threshold = 6
    max_jobs_hard_limit = 800

    # ============================================================
    # 列表页 selector
    # ============================================================

    CARD_SELECTORS = [
        # Moka 标准岗位卡片（a 标签包裹）
        "a[href*='#/jobs/']",
        "a[href*='/jobs/']",
        "div[class*='job-item']",
        "div[class*='position-item']",
        "div[class*='job-card']",
        "li[class*='job']",
        "li[class*='position']",
        "[class*='recruitment-list'] [class*='item']",
    ]

    TITLE_SELECTORS = [
        "h3", "h4",
        "[class*='job-title']",
        "[class*='position-title']",
        "[class*='title']",
        "[class*='name']",
        "span:first-child",
        "div:first-child",
    ]

    META_SELECTORS = [
        "[class*='job-meta']",
        "[class*='position-meta']",
        "[class*='meta']",
        "[class*='info']",
        "[class*='location']",
        "[class*='department']",
        "div:last-child",
    ]

    LOAD_MORE_SELECTORS = [
        "button:has-text('加载更多')",
        "button:has-text('查看更多')",
        "button[class*='load-more']",
        "[class*='load-more']",
        "a:has-text('加载更多')",
    ]

    # ============================================================
    # JD 详情页 selector
    # ============================================================

    JD_TITLE_SELECTORS = [
        "h1", "h2",
        "[class*='job-title']",
        "[class*='position-title']",
        "[class*='jobName']",
        "[class*='positionName']",
    ]

    JD_CONTENT_SELECTORS = [
        "[class*='job-detail']",
        "[class*='position-detail']",
        "[class*='job-content']",
        "[class*='position-content']",
        "[class*='jd-content']",
        "[class*='description']",
        "[class*='detail-content']",
        "article", "main",
    ]

    JD_META_SELECTORS = [
        "[class*='job-meta']",
        "[class*='position-meta']",
        "[class*='job-info']",
        "[class*='position-info']",
        "[class*='meta-info']",
    ]

    RESP_KEYWORDS = ["岗位职责", "工作职责", "工作内容", "岗位描述", "职位描述", "你将做什么", "职位职责", "岗位责任"]
    REQ_KEYWORDS = ["任职要求", "岗位要求", "任职资格", "资格要求", "我们希望你", "职位要求", "招聘要求", "能力要求"]

    def __init__(self, config: SiteConfig):
        super().__init__(config)

    # ============================================================
    # discover_jobs
    # ============================================================

    async def discover_jobs(self, page: Page) -> List[JobPosting]:
        """从 Moka 招聘列表页发现所有岗位。"""
        logger.info("Moka adapter (%s): discovering jobs from %s", self.site_name, page.url)

        all_jobs: List[JobPosting] = []
        seen_urls: Set[str] = set()
        consecutive_empty = 0

        for page_idx in range(self.max_pages):
            await self._wait_for_cards(page)

            batch = await self._extract_visible_jobs(page, seen_urls)
            if batch:
                all_jobs.extend(batch)
                for job in batch:
                    seen_urls.add(job.detail_url)
                consecutive_empty = 0
                logger.info("Page %d: +%d new jobs (total %d)", page_idx + 1, len(batch), len(all_jobs))
            else:
                consecutive_empty += 1
                logger.info("Page %d: no new jobs (consecutive %d)", page_idx + 1, consecutive_empty)

            if len(all_jobs) >= self.max_jobs_hard_limit:
                break

            if consecutive_empty >= self.no_new_threshold:
                logger.info("%d consecutive empty, stopping", self.no_new_threshold)
                break

            loaded = await self._try_load_more(page)
            if not loaded:
                await self._scroll_page(page)

            await page.wait_for_timeout(self.scroll_pause_ms)

        logger.info("Moka adapter (%s): discovered %d jobs", self.site_name, len(all_jobs))
        return all_jobs

    async def _wait_for_cards(self, page: Page) -> None:
        for sel in self.CARD_SELECTORS[:3]:
            try:
                await page.wait_for_selector(sel, timeout=5000)
                await page.wait_for_timeout(500)
                return
            except Exception:
                continue
        logger.debug("No Moka card selector matched")

    async def _try_load_more(self, page: Page) -> bool:
        for sel in self.LOAD_MORE_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(1500)
                    return True
            except Exception:
                continue
        return False

    async def _extract_visible_jobs(self, page: Page, seen_urls: Set[str]) -> List[JobPosting]:
        jobs: List[JobPosting] = []

        for card_sel in self.CARD_SELECTORS:
            try:
                cards = await page.query_selector_all(card_sel)
                if not cards:
                    continue

                for card in cards:
                    try:
                        job = await self._extract_from_card(card)
                        if job and job.detail_url not in seen_urls:
                            jobs.append(job)
                    except Exception:
                        continue

                if jobs:
                    logger.debug("Extracted %d jobs with: %s", len(jobs), card_sel)
                    break
            except Exception:
                continue

        if not jobs:
            jobs = await self._extract_by_links(page, seen_urls)

        return jobs

    async def _extract_from_card(self, card: ElementHandle) -> Optional[JobPosting]:
        href = await self._get_card_href(card)
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

    async def _get_card_href(self, card: ElementHandle) -> str:
        try:
            tag = await card.evaluate("el => el.tagName.toLowerCase()")
            if tag == "a":
                href = await card.get_attribute("href")
                if href:
                    return href
        except Exception:
            pass

        try:
            link = await card.query_selector("a[href]")
            if link:
                href = await link.get_attribute("href")
                if href:
                    return href
        except Exception:
            pass

        try:
            for attr in ["data-href", "data-url", "data-link", "data-job-id"]:
                val = await card.get_attribute(attr)
                if val:
                    # data-job-id 需要拼接成 hash 路由
                    if attr == "data-job-id":
                        return f"#/jobs/{val}"
                    return val
        except Exception:
            pass

        return ""

    async def _extract_title(self, card: ElementHandle) -> str:
        for sel in self.TITLE_SELECTORS[:-2]:
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
                    meta_text = " · ".join(lines[1:])
            except Exception:
                pass

        if not meta_text:
            return "", ""

        parts = [p.strip() for p in re.split(r"[·|/\\]", meta_text) if p.strip()]
        if not parts:
            parts = [meta_text]

        location = parts[0] if parts else ""
        category_path = " / ".join(parts[1:]) if len(parts) > 1 else ""

        return location, category_path

    async def _extract_by_links(self, page: Page, seen_urls: Set[str]) -> List[JobPosting]:
        """兜底：遍历所有 <a> 提取 Moka 岗位链接。"""
        jobs: List[JobPosting] = []
        try:
            links = await page.query_selector_all("a[href]")
            for link in links:
                try:
                    href = await link.get_attribute("href")
                    if not href:
                        continue
                    # Moka 岗位详情链接：#/jobs/{id} 或 /jobs/{id}
                    if not re.search(r"#?/jobs?/\d+", href) and "mokahr.com" not in href:
                        continue
                    # 排除列表页
                    if re.search(r"#?/jobs?/?$", href):
                        continue

                    text = (await link.inner_text()).strip()
                    title = text.split("\n")[0].strip() if text else ""
                    if not title or len(title) < 2 or len(title) > 100:
                        continue
                    if self._is_noise_title(title):
                        continue

                    job = self._make_job_posting(
                        title=title,
                        detail_url=href,
                        company=self.company_name,
                    )
                    if job and job.detail_url not in seen_urls:
                        jobs.append(job)
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Moka link fallback failed: %s", e)

        return jobs

    # ============================================================
    # extract_jd_detail
    # ============================================================

    async def extract_jd_detail(self, page: Page, posting: JobPosting) -> Optional[JobDetail]:
        """Moka JD 详情页结构化提取。"""
        try:
            await page.wait_for_timeout(1500)

            title = await self._extract_jd_title(page) or posting.title
            location, category_path = await self._extract_jd_meta(page)
            if not location:
                location = posting.location

            full_text = await self._extract_jd_content(page)
            if not full_text or len(full_text) < 20:
                await page.wait_for_timeout(2000)
                full_text = await self._extract_jd_content(page)

            responsibilities, requirements = self._split_jd_text(full_text)

            enhanced_posting = JobPosting(
                title=title,
                company=self.company_name,
                location=location,
                detail_url=posting.detail_url,
                category_path=category_path or posting.category_path,
                site_name=self.config.name,
            )

            return JobDetail(
                posting=enhanced_posting,
                full_jd=full_text,
                responsibilities=responsibilities,
                requirements=requirements,
                location=location,
                apply_url=posting.detail_url,
            )

        except Exception as e:
            logger.warning("Moka extract_jd_detail failed: %s", e)
            return None

    async def _extract_jd_title(self, page: Page) -> str:
        for sel in self.JD_TITLE_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if text and 2 < len(text) < 100:
                        if text not in ("校园招聘", "社招", "职位详情", "岗位详情"):
                            return text
            except Exception:
                continue
        return ""

    async def _extract_jd_meta(self, page: Page) -> tuple[str, str]:
        for sel in self.JD_META_SELECTORS:
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
            cities = ["北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "西安", "南京", "重庆"]
            for line in lines[:30]:
                if any(c in line for c in cities) and ("·" in line or "|" in line or "/" in line):
                    return self._parse_meta_text(line)
        except Exception:
            pass

        return "", ""

    def _parse_meta_text(self, text: str) -> tuple[str, str]:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) == 1:
            parts = [p.strip() for p in re.split(r"[·|/\\]", lines[0]) if p.strip()]
            if not parts:
                return lines[0], ""
            return parts[0], " / ".join(parts[1:]) if len(parts) > 1 else ""
        elif len(lines) >= 2:
            location = lines[0]
            noise = {"职位 ID", "职位ID", "ID：", "ID:", "招聘人数", "发布时间", "职位类型"}
            category_parts = [l for l in lines[1:] if not any(n in l for n in noise)]
            return location, " / ".join(category_parts)
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
