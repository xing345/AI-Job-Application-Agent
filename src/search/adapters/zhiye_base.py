"""智联 zhiye 招聘平台基类适配器。

智联招聘企业版（zhiye.com）页面结构：
- URL 格式：https://{company}.zhiye.com/jobs 或 /campus/jobs
- 列表页：传统分页或滚动加载
- 卡片结构：标题 + 地点 + 薪资 + 发布时间
- 详情页：/jobs/{id} 或 /job/{id}
- 分页：页码导航（page 参数）或"下一页"按钮

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


class ZhiyeBaseAdapter(SiteAdapter):
    """智联 zhiye 招聘平台基类。

    所有使用智联 zhiye 系统的公司适配器继承此类。
    """

    site_name = ""
    company_name = ""

    max_pages = 60
    scroll_pause_ms = 1500
    no_new_threshold = 5
    max_jobs_hard_limit = 600

    # ============================================================
    # 列表页 selector
    # ============================================================

    CARD_SELECTORS = [
        # zhiye 标准岗位列表项
        "div[class*='job-item']",
        "div[class*='position-item']",
        "li[class*='job']",
        "li[class*='position']",
        "a[class*='job-item']",
        "a[href*='/job/']",
        "a[href*='/jobs/']",
        "a[href*='/position/']",
        "[class*='job-list'] [class*='item']",
        "[class*='position-list'] [class*='item']",
    ]

    TITLE_SELECTORS = [
        "h3", "h4",
        "[class*='job-title']",
        "[class*='position-title']",
        "[class*='title']",
        "[class*='name']",
        "a",
        "span:first-child",
        "div:first-child",
    ]

    META_SELECTORS = [
        "[class*='job-meta']",
        "[class*='position-meta']",
        "[class*='meta']",
        "[class*='info']",
        "[class*='location']",
        "[class*='salary']",
        "div:last-child",
    ]

    # 分页控件
    NEXT_PAGE_SELECTORS = [
        "a:has-text('下一页')",
        "button:has-text('下一页')",
        "[class*='next']:not([class*='disabled'])",
        "li[class*='next']:not([class*='disabled']) a",
        "a[class*='next-page']",
    ]

    CURRENT_PAGE_SELECTOR = "[class*='active'], [class*='current'], li[class*='selected']"

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
        "[class*='job-description']",
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
    # discover_jobs：支持分页和滚动两种模式
    # ============================================================

    async def discover_jobs(self, page: Page) -> List[JobPosting]:
        """从 zhiye 列表页发现所有岗位。

        先尝试分页模式（点击"下一页"），如果没有分页控件则回退到滚动模式。
        """
        logger.info("Zhiye adapter (%s): discovering jobs from %s", self.site_name, page.url)

        # 检测是否有分页控件
        has_pagination = await self._has_pagination(page)

        if has_pagination:
            logger.info("Using pagination mode")
            return await self._discover_pagination(page)
        else:
            logger.info("Using scroll mode")
            return await self._discover_scroll(page)

    async def _has_pagination(self, page: Page) -> bool:
        """检测页面是否有分页控件。"""
        for sel in self.NEXT_PAGE_SELECTORS:
            try:
                count = await page.locator(sel).count()
                if count > 0:
                    return True
            except Exception:
                continue
        # 检查是否有页码列表
        try:
            pagination = await page.query_selector("[class*='pagination'], [class*='pager']")
            if pagination:
                return True
        except Exception:
            pass
        return False

    async def _discover_pagination(self, page: Page) -> List[JobPosting]:
        """分页模式：逐页提取 + 点击下一页。"""
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

            if len(all_jobs) >= self.max_jobs_hard_limit:
                break

            if consecutive_empty >= 3:
                logger.info("3 consecutive empty pages, stopping")
                break

            has_next = await self._go_to_next_page(page)
            if not has_next:
                logger.info("No more pages, stopping")
                break

        logger.info("Zhiye pagination (%s): discovered %d jobs", self.site_name, len(all_jobs))
        return all_jobs

    async def _discover_scroll(self, page: Page) -> List[JobPosting]:
        """滚动模式：循环滚动 + 提取。"""
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
                logger.info("Scroll %d: +%d new jobs (total %d)", page_idx + 1, len(batch), len(all_jobs))
            else:
                consecutive_empty += 1

            if len(all_jobs) >= self.max_jobs_hard_limit:
                break

            if consecutive_empty >= self.no_new_threshold:
                break

            await self._scroll_page(page)
            await page.wait_for_timeout(self.scroll_pause_ms)

        logger.info("Zhiye scroll (%s): discovered %d jobs", self.site_name, len(all_jobs))
        return all_jobs

    async def _wait_for_cards(self, page: Page) -> None:
        for sel in self.CARD_SELECTORS[:3]:
            try:
                await page.wait_for_selector(sel, timeout=5000)
                await page.wait_for_timeout(500)
                return
            except Exception:
                continue

    async def _go_to_next_page(self, page: Page) -> bool:
        """点击"下一页"，返回是否成功。"""
        for sel in self.NEXT_PAGE_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.count() == 0:
                    continue
                if not await btn.is_visible():
                    continue

                # 记录当前页第一个卡片 URL
                old_first_url = ""
                old_cards = await page.query_selector_all(self.CARD_SELECTORS[0])
                if old_cards:
                    old_first_url = await old_cards[0].get_attribute("href") or ""

                await btn.click()
                await page.wait_for_timeout(1500)

                # 等待页面变化
                try:
                    await page.wait_for_function(
                        """(oldUrl) => {
                            const cards = document.querySelectorAll("a[href*='/job/'], a[href*='/jobs/'], div[class*='job-item']");
                            if (cards.length === 0) return false;
                            const firstHref = cards[0].getAttribute('href') || '';
                            return firstHref !== oldUrl;
                        }""",
                        arg=old_first_url,
                        timeout=8000,
                    )
                except Exception:
                    pass

                await page.wait_for_timeout(500)
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
            for attr in ["data-href", "data-url", "data-link"]:
                val = await card.get_attribute(attr)
                if val:
                    return val
        except Exception:
            pass

        return ""

    async def _extract_title(self, card: ElementHandle) -> str:
        for sel in self.TITLE_SELECTORS[:-3]:
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
        """兜底：遍历所有 <a> 提取岗位链接。"""
        jobs: List[JobPosting] = []
        try:
            links = await page.query_selector_all("a[href]")
            for link in links:
                try:
                    href = await link.get_attribute("href")
                    if not href:
                        continue
                    # zhiye 岗位链接：/job/{id}, /jobs/{id}, /position/{id}
                    if not re.search(r"/(job|jobs|position|post)s?/\d+", href):
                        continue
                    if re.search(r"/(job|jobs|position)s?/?$", href):
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
            logger.debug("Zhiye link fallback failed: %s", e)

        return jobs

    # ============================================================
    # extract_jd_detail
    # ============================================================

    async def extract_jd_detail(self, page: Page, posting: JobPosting) -> Optional[JobDetail]:
        """zhiye JD 详情页结构化提取。"""
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
            logger.warning("Zhiye extract_jd_detail failed: %s", e)
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
            noise = {"职位 ID", "职位ID", "ID：", "ID:", "招聘人数", "发布时间", "职位类型", "薪资"}
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
