"""腾讯校招站点适配器。

列表页: https://join.qq.com/post.html
模式: API 分页（POST /api/v1/position/searchPosition）
详情页: https://join.qq.com/post_detail.html?postid={postId}
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import List, Optional

from playwright.async_api import Page

from src.models.job import JobDetail, JobPosting
from src.search.adapters.base import SiteAdapter, register_adapter
from src.search.site_registry import SiteConfig

logger = logging.getLogger(__name__)

_API_URL = "https://join.qq.com/api/v1/position/searchPosition"
_DETAIL_BASE = "https://join.qq.com/post_detail.html?postid="
_LIST_URL = "https://join.qq.com/post.html"


@register_adapter
class TencentAdapter(SiteAdapter):
    """腾讯校招适配器（API 分页模式）。"""

    site_name = "tencent"
    company_name = "腾讯"

    max_pages = 100
    page_size = 10
    max_jobs_hard_limit = 1000

    RESP_KEYWORDS = ["岗位描述", "岗位职责", "工作职责", "工作内容", "课题描述"]
    REQ_KEYWORDS = ["岗位要求", "任职要求", "任职资格", "课题要求"]
    BONUS_KEYWORDS = ["加分项", "加分", "注意事项"]
    # 正文结束锚点（要求/职责段落之后的页面区块，用于截断噪声）
    STOP_KEYWORDS = [
        "参加面试的城市", "课题部门", "工作地", "投递简历", "关注腾讯",
        "相关推荐", "相关岗位", "面试城市", "工作地点",
    ]

    def __init__(self, config: SiteConfig):
        super().__init__(config)

    # ============================================================
    # 岗位发现（API 分页）
    # ============================================================

    async def discover_jobs(self, page: Page) -> List[JobPosting]:
        """通过 searchPosition API 分页获取全部岗位。"""
        logger.info("Tencent adapter: discovering jobs (API mode)")

        # 先打开列表页建立会话/cookie
        if "join.qq.com" not in page.url:
            await page.goto(_LIST_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

        all_jobs: List[JobPosting] = []
        total = 0

        for page_index in range(1, self.max_pages + 1):
            payload = self._build_payload(page_index)
            try:
                resp = await page.request.post(_API_URL, data=payload)
                if not resp.ok:
                    logger.warning("API page %d failed: status=%s", page_index, resp.status)
                    break
                data = await resp.json()
            except Exception as e:
                logger.warning("API page %d error: %s", page_index, e)
                break

            if data.get("status") != 0:
                logger.warning("API page %d returned status=%s message=%s",
                               page_index, data.get("status"), data.get("message"))
                break

            inner = data.get("data", {})
            positions = inner.get("positionList", [])
            total = inner.get("count", total)

            if not positions:
                logger.info("Page %d: empty list, stopping", page_index)
                break

            batch: List[JobPosting] = []
            for p in positions:
                post_id = str(p.get("postId", "")).strip()
                title = (p.get("positionTitle") or "").strip()
                if not post_id or not title:
                    continue
                location = (p.get("workCities") or "").strip()
                bgs = (p.get("bgs") or "").strip()
                family = p.get("positionFamily")
                recruit = p.get("recruitLabelName") or p.get("projectName") or ""

                category_parts = []
                if recruit:
                    category_parts.append(recruit)
                if bgs:
                    category_parts.append(bgs)

                posting = self._make_job_posting(
                    title=title,
                    detail_url=_DETAIL_BASE + post_id,
                    company=self.company_name,
                    location=location,
                    category_path=" / ".join(category_parts),
                )
                batch.append(posting)

            all_jobs.extend(batch)
            logger.info("API page %d: +%d jobs (total %d / %s)",
                        page_index, len(batch), len(all_jobs), total)

            if len(all_jobs) >= self.max_jobs_hard_limit:
                break
            # 已取完全部
            if total and len(all_jobs) >= total:
                break

        logger.info("Tencent adapter: discovered %d jobs (site total=%s)", len(all_jobs), total)
        return self._dedup_jobs(all_jobs)

    def _build_payload(self, page_index: int) -> dict:
        return {
            "projectIdList": [],
            "projectMappingIdList": [1, 2, 104, 14, 20],
            "keyword": "",
            "bgList": [],
            "workCountryType": 0,
            "workCityList": [],
            "recruitCityList": [],
            "positionFidList": [],
            "pageIndex": page_index,
            "pageSize": self.page_size,
        }

    # ============================================================
    # JD 详情页提取
    # ============================================================

    async def extract_jd_detail(self, page: Page, posting: JobPosting) -> Optional[JobDetail]:
        try:
            await page.goto(posting.detail_url, wait_until="domcontentloaded", timeout=30000)
            # 等待JD内容渲染
            full_text = ""
            lines: List[str] = []
            valid = False
            for attempt in range(3):
                await page.wait_for_timeout(2500)
                body = await page.locator("body").inner_text()
                lines = [l.strip() for l in body.split("\n") if l.strip()]
                _, full_text = self._parse_detail_lines(lines)
                # 校验：含 岗位/课题 关键词，且页面包含列表 API 权威标题（防宣传页/失效岗串岗）
                if full_text and self._has_jd_keywords(full_text) and self._page_has_title(lines, posting.title):
                    valid = True
                    break
                logger.debug("Tencent detail attempt %d: jd_len=%d has_kw=%s has_title=%s",
                             attempt + 1, len(full_text),
                             self._has_jd_keywords(full_text),
                             self._page_has_title(lines, posting.title))

            if not valid:
                logger.warning("Tencent JD 无效/标题不符: 期望='%s' url=%s",
                               posting.title, posting.detail_url)
                return None

            location = posting.location
            responsibilities, requirements, bonus = self._split_jd_sections(full_text)

            enhanced_posting = JobPosting(
                title=posting.title,  # 统一用列表 API 权威标题，避免页面标题错误
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
            logger.info("Tencent JD extracted: %s | jd_len=%d", enhanced_posting.title, len(full_text))
            return detail
        except Exception as e:
            logger.warning("Tencent extract_jd_detail failed: %s", e)
            return None

    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"\s+", "", s or "")

    def _page_has_title(self, lines: List[str], expected: str) -> bool:
        """页面是否包含列表 API 权威标题（规范化后子串匹配，兼容普通岗与青云课题）。"""
        et = self._norm(expected)
        if not et:
            return False
        return any(et in self._norm(line) for line in lines)

    @staticmethod
    def _titles_match(t1: str, t2: str, threshold: float = 0.6) -> bool:
        """标题一致性校验（规范化后相似度≥阈值），备用。"""
        if not t1 or not t2:
            return False
        a = re.sub(r"\s+", "", t1)
        b = re.sub(r"\s+", "", t2)
        return difflib.SequenceMatcher(None, a, b).ratio() >= threshold

    def _parse_detail_lines(self, lines: List[str]) -> tuple[str, str]:
        """从详情页文本行中提取标题和JD正文。

        典型结构：
          0: 腾讯校园招聘
          1: 导航...
          2: Agent开发工程师   <- 标题
          3: 技术
          4: 应届毕业生
          5: 岗位描述
          ...
        """
        title = ""
        # 找"岗位描述/岗位职责"位置
        desc_idx = -1
        for i, line in enumerate(lines):
            if line in self.RESP_KEYWORDS:
                desc_idx = i
                break

        if desc_idx >= 0:
            # 标题在"岗位描述"之前，跳过导航和类别行
            for i in range(desc_idx - 1, -1, -1):
                line = lines[i]
                if line in ("技术", "产品", "市场", "设计", "应届毕业生", "实习生") or \
                   line in ("腾讯校园招聘",) or "首页" in line or "登录" in line:
                    continue
                if len(line) > 2:
                    title = line
                    break
            jd_text = "\n".join(lines[desc_idx:])
        else:
            # 兜底：用第一个非导航长行作为标题
            for line in lines:
                if len(line) > 4 and "腾讯" not in line and "首页" not in line:
                    title = line
                    break
            jd_text = "\n".join(lines)

        return title, jd_text

    def _has_jd_keywords(self, text: str) -> bool:
        return any(kw in text for kw in self.RESP_KEYWORDS + self.REQ_KEYWORDS)

    def _split_jd_sections(self, full_text: str) -> tuple[str, str, str]:
        """切分职责/要求/加分项三段。"""
        lines = full_text.split("\n")

        def find_idx(keywords: List[str], start: int = 0) -> int:
            for i in range(start, len(lines)):
                if lines[i].strip() in keywords:
                    return i
            return -1

        def next_stop(start: int) -> int:
            idx = find_idx(self.STOP_KEYWORDS, start)
            return idx if idx >= 0 else len(lines)

        resp_idx = find_idx(self.RESP_KEYWORDS)
        req_idx = find_idx(self.REQ_KEYWORDS, resp_idx + 1 if resp_idx >= 0 else 0)
        bonus_idx = find_idx(self.BONUS_KEYWORDS, req_idx + 1 if req_idx >= 0 else 0)

        responsibilities = ""
        requirements = ""
        bonus = ""

        # 职责 / 课题描述：到 要求段、加分项或结束锚点（取最近）
        if resp_idx >= 0:
            ends = [next_stop(resp_idx + 1)]
            if req_idx > resp_idx:
                ends.append(req_idx)
            if bonus_idx > resp_idx:
                ends.append(bonus_idx)
            responsibilities = "\n".join(lines[resp_idx + 1:min(ends)]).strip()

        # 要求 / 课题要求：到 加分项或结束锚点
        if req_idx >= 0:
            ends = [next_stop(req_idx + 1)]
            if bonus_idx > req_idx:
                ends.append(bonus_idx)
            requirements = "\n".join(lines[req_idx + 1:min(ends)]).strip()

        if bonus_idx >= 0:
            bonus = "\n".join(lines[bonus_idx + 1:next_stop(bonus_idx + 1)]).strip()

        # 加分项并入要求文本（供匹配使用）
        if bonus and requirements:
            requirements = requirements + "\n" + bonus
        elif bonus:
            requirements = bonus

        return responsibilities, requirements, bonus
