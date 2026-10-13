"""字节跳动校招站点适配器。

已验证：
- 列表页: https://jobs.bytedance.com/campus/position
- 岗位链接格式: /campus/position/{ID}/detail
- 滚动加载（SPA 虚拟滚动）

岗位卡片结构（基于实际页面）：
<a href="/campus/position/xxx/detail">
  <div>岗位标题</div>
  <div>地点 | 团队 | 职位类别</div>
</a>
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
class BytedanceAdapter(SiteAdapter):
    """字节跳动校招适配器。"""

    site_name = "bytedance"
    company_name = "字节跳动"

    # 字节跳动有747页（每页10个，共7470个岗位），需要足够翻页次数
    max_pages = 800
    scroll_pause_ms = 1200
    no_new_threshold = 10  # 分页模式下连续空页检测
    max_jobs_hard_limit = 2000  # 硬上限，避免无限加载（可通过配置调整）

    # 岗位卡片 selector（已验证）
    CARD_SELECTOR = "a[href*='/campus/position/'][href*='/detail']"

    # 分页控件 selector（字节跳动使用传统分页，共747页，每页10个岗位）
    NEXT_PAGE_SELECTOR = "li.atsx-pagination-next:not(.disabled) a"
    CURRENT_PAGE_SELECTOR = "li.atsx-pagination-item-active"
    PAGINATION_SELECTOR = "ul.atsx-pagination"

    # 卡片内标题 selector（按优先级尝试）
    TITLE_SELECTORS = [
        "h3", ".position-title", ".job-title",
        "[class*='title']", "div:first-child",
    ]

    # 卡片内元信息 selector（地点/团队/类别通常在同一行）
    META_SELECTORS = [
        ".position-meta", ".job-meta", "[class*='meta']",
        "[class*='info']", "div:last-child",
    ]

    def __init__(self, config: SiteConfig):
        super().__init__(config)

    async def discover_jobs(self, page: Page) -> List[JobPosting]:
        """从字节跳动校招列表页发现所有岗位。

        字节跳动使用传统分页（非虚拟滚动），每页10个岗位，共747页。
        策略：逐页提取 → 点击"下一页" → 等待加载 → 重复。
        """
        logger.info("Bytedance adapter: discovering jobs (pagination mode) from %s", page.url)

        all_jobs: List[JobPosting] = []
        seen_urls: set[str] = set()
        consecutive_empty = 0

        for page_idx in range(self.max_pages):
            # 等待当前页岗位卡片加载
            await self._wait_for_cards(page)

            # 提取当前页的岗位
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

            # 达到硬上限
            if len(all_jobs) >= self.max_jobs_hard_limit:
                logger.info("Reached hard limit %d, stopping", self.max_jobs_hard_limit)
                break

            # 连续空页，停止
            if consecutive_empty >= 3:
                logger.info("3 consecutive empty pages, stopping")
                break

            # 点击"下一页"
            has_next = await self._go_to_next_page(page)
            if not has_next:
                logger.info("No more pages (reached last page), stopping")
                break

        logger.info("Bytedance adapter: discovered %d jobs from %d pages", len(all_jobs), page_idx + 1)
        return all_jobs

    async def _wait_for_cards(self, page: Page) -> None:
        """等待岗位卡片加载完成。"""
        try:
            await page.wait_for_selector(self.CARD_SELECTOR, timeout=10000)
            await page.wait_for_timeout(800)  # 额外等待渲染
        except Exception:
            logger.debug("Wait for cards timeout")

    async def _go_to_next_page(self, page: Page) -> bool:
        """点击"下一页"按钮，返回是否成功（False表示没有下一页）。"""
        try:
            next_btn = page.locator(self.NEXT_PAGE_SELECTOR).first
            if await next_btn.count() == 0:
                logger.debug("Next page button not found or disabled")
                return False

            # 记录当前页第一个卡片的 URL，用于判断页面是否变化
            old_first_url = ""
            old_cards = await page.query_selector_all(self.CARD_SELECTOR)
            if old_cards:
                old_first_url = await old_cards[0].get_attribute("href") or ""

            # 点击下一页
            await next_btn.click()
            await page.wait_for_timeout(1500)

            # 等待页面变化（第一个卡片 URL 变化）
            try:
                await page.wait_for_function(
                    """(oldUrl) => {
                        const cards = document.querySelectorAll("a[href*='/campus/position/'][href*='/detail']");
                        if (cards.length === 0) return false;
                        return cards[0].getAttribute('href') !== oldUrl;
                    }""",
                    arg=old_first_url,
                    timeout=10000,
                )
            except Exception:
                logger.debug("Wait for page change timeout")

            await page.wait_for_timeout(500)
            return True

        except Exception as e:
            logger.debug("Go to next page failed: %s", e)
            return False

    async def _extract_visible_jobs(self, page: Page, seen_urls: set[str]) -> List[JobPosting]:
        """提取当前可见区域的所有岗位卡片。"""
        jobs: List[JobPosting] = []

        try:
            cards = await page.query_selector_all(self.CARD_SELECTOR)
        except Exception as e:
            logger.warning("Failed to query cards: %s", e)
            return jobs

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
        """从单个岗位卡片提取信息。"""
        # 1. 获取详情页 URL
        href = await card.get_attribute("href")
        if not href:
            return None

        # 2. 提取标题
        title = await self._extract_title(card)
        if not title or self._is_noise_title(title):
            return None

        # 3. 提取元信息（地点/团队/类别）
        location, category_path = await self._extract_meta(card)

        return self._make_job_posting(
            title=title,
            detail_url=href,
            company=self.company_name,
            location=location,
            category_path=category_path,
        )

    async def _extract_title(self, card: ElementHandle) -> str:
        """从卡片中提取岗位标题。"""
        # 优先尝试特定 selector
        for sel in self.TITLE_SELECTORS[:-1]:  # 排除 "div:first-child" 兜底
            try:
                el = await card.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text and len(text) > 1 and len(text) < 100:
                        return text
            except Exception:
                continue

        # 兜底：取卡片全文的第一行
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
        """从卡片中提取地点和分类路径。

        字节跳动卡片的元信息通常格式为："地点 | 团队 | 职位类别"
        返回 (location, category_path)
        """
        meta_text = ""

        # 尝试特定 selector
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

        # 兜底：取卡片全文的第二行
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

        # 解析 "地点 | 团队 | 职位类别" 格式
        parts = [p.strip() for p in meta_text.replace("|", "·").split("·") if p.strip()]
        if not parts:
            parts = [meta_text]

        location = parts[0] if parts else ""
        # 分类路径 = 团队 + 职位类别（如果有）
        category_path = " / ".join(parts[1:]) if len(parts) > 1 else ""

        return location, category_path

    # ============================================================
    # JD 详情页提取
    # ============================================================

    # JD 详情页标题 selector（按优先级）
    JD_TITLE_SELECTORS = [
        "h1", ".position-title", ".job-title",
        "[class*='position-title']", "[class*='job-title']",
        "[class*='positionName']", "[class*='jobName']",
    ]

    # JD 正文容器 selector
    JD_CONTENT_SELECTORS = [
        ".position-detail", ".job-detail", ".position-content",
        ".job-content", "[class*='position-detail']",
        "[class*='job-detail']", "[class*='position-content']",
        "[class*='job-content']", "[class*='jd-content']",
        "[class*='description']", "article", "main",
    ]

    # 岗位职责/任职要求关键词（扩展，覆盖字节跳动常用表述）
    RESP_KEYWORDS = ["岗位职责", "工作职责", "工作内容", "岗位描述", "职位描述", "你将做什么", "职位职责"]
    REQ_KEYWORDS = ["任职要求", "岗位要求", "任职资格", "资格要求", "我们希望你", "职位要求", "招聘要求"]

    async def extract_jd_detail(self, page: Page, posting: JobPosting) -> Optional[JobDetail]:
        """字节跳动 JD 详情页结构化提取。"""
        try:
            # 1. 提取标题
            title = await self._extract_jd_title(page) or posting.title

            # 2. 提取元信息（地点/团队/类别）
            location, category_path = await self._extract_jd_meta(page)
            if not location:
                location = posting.location

            # 3. 提取 JD 正文
            full_text = await self._extract_jd_content(page)
            if not full_text or len(full_text) < 20:
                # 内容太短，等待后重试
                await page.wait_for_timeout(2000)
                full_text = await self._extract_jd_content(page)

            # 4. 拆分职责和要求
            responsibilities, requirements = self._split_jd_text(full_text)

            # 5. 构造增强后的 posting
            enhanced_posting = JobPosting(
                title=title,
                company=self.company_name,
                location=location,
                detail_url=posting.detail_url,
                category_path=category_path or posting.category_path,
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

            logger.info("Bytedance JD extracted: %s | jd_len=%d | resp_len=%d | req_len=%d",
                        title, len(full_text), len(responsibilities), len(requirements))
            return detail

        except Exception as e:
            logger.warning("Bytedance extract_jd_detail failed: %s", e)
            return None

    async def _extract_jd_title(self, page: Page) -> str:
        """提取 JD 详情页标题。"""
        for sel in self.JD_TITLE_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if text and 2 < len(text) < 100:
                        # 过滤通用标题
                        if text not in ("校园招聘", "社招", "职位详情", "岗位详情"):
                            return text
            except Exception:
                continue
        return ""

    async def _extract_jd_meta(self, page: Page) -> tuple[str, str]:
        """提取 JD 详情页元信息（地点、分类路径）。

        字节跳动详情页元信息通常在标题下方，格式：地点 · 团队 · 职位类别
        """
        # 尝试从标题附近的元信息行提取
        meta_selectors = [
            ".position-meta", ".job-meta", "[class*='position-meta']",
            "[class*='job-meta']", "[class*='position-info']",
            "[class*='job-info']", "[class*='meta-info']",
        ]
        for sel in meta_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if text and len(text) < 200:
                        return self._parse_meta_text(text)
            except Exception:
                continue

        # 兜底：从页面前 30 行中找包含地点关键词的行
        try:
            body_text = await page.locator("body").inner_text()
            lines = [l.strip() for l in body_text.split("\n") if l.strip()]
            for line in lines[:30]:
                # 包含城市名或"·"分隔符的行可能是元信息
                if any(city in line for city in ["北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "西安", "南京", "重庆"]) and ("·" in line or "|" in line):
                    return self._parse_meta_text(line)
        except Exception:
            pass

        return "", ""

    def _parse_meta_text(self, text: str) -> tuple[str, str]:
        """解析元信息文本：地点 · 团队 · 职位类别 → (location, category_path)

        字节跳动详情页元信息可能是多行格式：
        北京
        正式
        研发 - 客户端
        2027届校园招聘
        职位 ID：A170211

        处理策略：
        - 如果是单行，用 · 或 | 分割
        - 如果是多行，第一行是地点，后续行合并为分类路径
        """
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        if len(lines) == 1:
            # 单行：用 · 或 | 分割
            parts = [p.strip() for p in lines[0].replace("|", "·").split("·") if p.strip()]
            if not parts:
                return lines[0], ""
            location = parts[0]
            category_path = " / ".join(parts[1:]) if len(parts) > 1 else ""
            return location, category_path
        elif len(lines) >= 2:
            # 多行：第一行是地点，后续行合并（过滤职位ID等噪声）
            location = lines[0]
            # 过滤噪声行
            noise = {"职位 ID", "职位ID", "ID：", "ID:"}
            category_parts = []
            for line in lines[1:]:
                if not any(n in line for n in noise):
                    category_parts.append(line)
            category_path = " / ".join(category_parts)
            return location, category_path
        else:
            return "", ""

    async def _extract_jd_content(self, page: Page) -> str:
        """提取 JD 正文内容。

        策略：
        1. 优先选择包含职责/要求关键词的容器
        2. 其次选择内容最长的容器
        3. 兜底取 body 文本
        """
        candidates = []

        for sel in self.JD_CONTENT_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    if len(text) > 50:
                        # 检查是否包含关键词
                        has_keywords = any(kw in text for kw in self.RESP_KEYWORDS + self.REQ_KEYWORDS)
                        candidates.append((has_keywords, len(text), text, sel))
            except Exception:
                continue

        if candidates:
            # 优先：包含关键词的，按内容长度降序
            with_keywords = [c for c in candidates if c[0]]
            if with_keywords:
                with_keywords.sort(key=lambda x: x[1], reverse=True)
                logger.debug("JD content selected (with keywords): %s (len=%d)",
                             with_keywords[0][3], with_keywords[0][1])
                return with_keywords[0][2]

            # 其次：内容最长的
            candidates.sort(key=lambda x: x[1], reverse=True)
            logger.debug("JD content selected (longest): %s (len=%d)",
                         candidates[0][3], candidates[0][1])
            return candidates[0][2]

        # 兜底：取 body 文本
        try:
            body = await page.locator("body").inner_text()
            return body.strip()
        except Exception:
            return ""

    def _split_jd_text(self, full_text: str) -> tuple[str, str]:
        """拆分 JD 文本为岗位职责和任职要求。"""
        responsibilities = ""
        requirements = ""

        # 找任职要求的位置
        req_pos = -1
        for kw in self.REQ_KEYWORDS:
            idx = full_text.find(kw)
            if idx >= 0 and (req_pos < 0 or idx < req_pos):
                req_pos = idx

        # 找岗位职责的位置
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
