"""米哈游校招站点适配器。

列表页: https://jobs.mihoyo.com/#/campus/position
模式: API 直接调用（ats.openout.mihoyo.com/ats-portal/v1/job/list）
岗位详情页: https://jobs.mihoyo.com/#/campus/position/{id}

API 请求: POST {"pageNo":1,"pageSize":10,"channelDetailIds":[1],"hireType":1}
API 响应: {"code":0,"data":{"list":[{id,title,addressDetailList,competencyType,jobNature,...}],"total":127}}
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from playwright.async_api import Page

from src.models.job import JobDetail, JobPosting
from src.search.adapters.base import SiteAdapter, register_adapter
from src.search.site_registry import SiteConfig

logger = logging.getLogger(__name__)


@register_adapter
class MihoyoAdapter(SiteAdapter):
    """米哈游校招适配器（API模式）。"""

    site_name = "mihoyo"
    company_name = "米哈游"

    max_pages = 50  # API每页10个，50页=500个
    max_jobs_hard_limit = 500

    # 岗位列表 API
    JOB_LIST_API = "https://ats.openout.mihoyo.com/ats-portal/v1/job/list"

    # 详情页 URL 模板
    DETAIL_URL_TEMPLATE = "https://jobs.mihoyo.com/#/campus/position/{job_id}"

    # JD 详情页 selector
    # 注意：主标题是 span.jobTitle___xxx；右侧"相关岗位"侧栏是 span.jobName___xxx。
    # 绝不能用 [class*='jobName']，会读到侧栏第一个相关岗位（造成"串岗"误判）。
    JD_TITLE_SELECTORS = [
        "span[class*='jobTitle']",
        "[class*='titleLineH'] >> nth=0",
        "h1",
    ]

    # 主 JD 容器：detailContainer 只含主体（不含右侧相关岗位侧栏）
    JD_CONTENT_SELECTORS = [
        "[class*='detailContainer']",
        "[class*='jobDetail']", "[class*='positionDetail']",
        "[class*='jd-content']",
        "article", "main",
    ]

    RESP_KEYWORDS = ["岗位职责", "工作职责", "工作内容", "岗位描述", "职位描述", "职位职责"]
    REQ_KEYWORDS = ["任职要求", "岗位要求", "任职资格", "资格要求", "我们希望你", "职位要求", "招聘要求"]

    def __init__(self, config: SiteConfig):
        super().__init__(config)

    async def discover_jobs(self, page: Page) -> List[JobPosting]:
        """通过 API 获取所有岗位。

        在浏览器上下文中用 fetch 调用 API，自动带上 cookie。
        """
        logger.info("Mihoyo adapter: discovering jobs via API from %s", page.url)

        all_jobs: List[JobPosting] = []
        seen_ids: set[str] = set()

        for page_no in range(1, self.max_pages + 1):
            try:
                result = await self._fetch_job_page(page, page_no)
            except Exception as e:
                logger.warning("Fetch page %d failed: %s", page_no, e)
                break

            if not result:
                break

            job_list = result.get("list", [])
            total = result.get("total", 0)

            if not job_list:
                logger.info("Page %d: no jobs, stopping", page_no)
                break

            new_count = 0
            for job_data in job_list:
                job_id = str(job_data.get("id", ""))
                if not job_id or job_id in seen_ids:
                    continue

                title = job_data.get("title", "").strip()
                if not title or self._is_noise_title(title):
                    continue

                # 提取地点
                location = ""
                addr_list = job_data.get("addressDetailList", [])
                if addr_list:
                    location = addr_list[0].get("addressDetail", "")

                # 分类信息
                competency = job_data.get("competencyType", "")
                job_nature = job_data.get("jobNature", "")
                project = job_data.get("projectName", "")
                category_parts = [p for p in [competency, job_nature, project] if p]
                category_path = " / ".join(category_parts)

                detail_url = self.DETAIL_URL_TEMPLATE.format(job_id=job_id)

                # 注意：米哈游使用 hash 路由，岗位 ID 在 URL fragment 中。
                # 基类的 normalize_url 会移除 fragment，所以这里直接构造 JobPosting，
                # 不调用 _make_job_posting（它会调用 normalize_url）。
                job = JobPosting(
                    title=title,
                    company=self.company_name,
                    location=location,
                    detail_url=detail_url,
                    category_path=category_path,
                    site_name=self.site_name,
                )
                all_jobs.append(job)
                seen_ids.add(job_id)
                new_count += 1

            logger.info("Page %d: +%d new jobs (total %d, API total %d)",
                        page_no, new_count, len(all_jobs), total)

            # 达到硬上限
            if len(all_jobs) >= self.max_jobs_hard_limit:
                logger.info("Reached hard limit %d, stopping", self.max_jobs_hard_limit)
                break

            # 已经获取完所有岗位
            if len(all_jobs) >= total:
                logger.info("All %d jobs fetched, stopping", total)
                break

        logger.info("Mihoyo adapter: discovered %d jobs via API", len(all_jobs))
        return all_jobs

    async def _fetch_job_page(self, page: Page, page_no: int) -> Optional[dict]:
        """通过 Playwright API 请求上下文调用岗位列表 API（不受 CORS 限制，自动带 cookie）。"""
        try:
            response = await page.request.post(
                self.JOB_LIST_API,
                data={
                    "pageNo": page_no,
                    "pageSize": 10,
                    "channelDetailIds": [1],
                    "hireType": 1,
                },
                headers={"Content-Type": "application/json"},
            )

            if not response.ok:
                logger.warning("API returned HTTP %d", response.status)
                return None

            result = await response.json()

            if isinstance(result, dict) and result.get("code") == 0:
                return result.get("data")

            logger.warning("API returned non-zero code: %s", result)
            return None

        except Exception as e:
            logger.warning("Fetch job page exception: %s", e)
            return None

    # ============================================================
    # JD 详情页提取
    # ============================================================

    async def extract_jd_detail(self, page: Page, posting: JobPosting) -> Optional[JobDetail]:
        try:
            # 米哈游 hash 路由连续 goto 时，Vue Router 可能不重新渲染（JD 串岗）。
            # 策略：读取 → 验证「标题与 posting.title 一致 且 JD 有效」；
            # 失败则逐级加强：reload → 经列表中间页强制切换，最多 4 次。
            full_text = ""
            title = ""
            ok = False
            for attempt in range(4):
                if attempt == 0:
                    # 外部（fetch_single_jd）已 goto，等待渲染后直接读
                    await page.wait_for_timeout(1500)
                elif attempt == 1:
                    logger.info("Mihoyo JD mismatch, reload (attempt %d)", attempt + 1)
                    await page.reload(wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(2200)
                else:
                    logger.info("Mihoyo JD mismatch, force switch via list page (attempt %d)", attempt + 1)
                    await self._force_navigate(page, posting.detail_url)

                title = await self._extract_jd_title(page)
                full_text = await self._extract_jd_content(page)

                titles_match = self._titles_match(title, posting.title)
                jd_valid = self._is_jd_valid(full_text)
                if titles_match and jd_valid:
                    ok = True
                    break
                logger.info(
                    "Mihoyo JD verify failed attempt %d: title_match=%s jd_valid=%s "
                    "(got title='%s', expected='%s', jd_len=%d)",
                    attempt + 1, titles_match, jd_valid,
                    title[:30], posting.title[:30], len(full_text))

            if not ok:
                logger.warning(
                    "Mihoyo JD extraction failed after 4 attempts: %s (got title='%s', len=%d)",
                    posting.detail_url, title[:40], len(full_text))
                # 标题不匹配说明抓到的是别的岗位（串岗），不可信，直接返回 None
                if not self._titles_match(title, posting.title):
                    return None

            location = posting.location
            responsibilities, requirements = self._split_jd_text(full_text)

            enhanced_posting = JobPosting(
                title=title or posting.title,
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
            logger.info("Mihoyo JD extracted: %s | jd_len=%d", enhanced_posting.title, len(full_text))
            return detail
        except Exception as e:
            logger.warning("Mihoyo extract_jd_detail failed: %s", e)
            return None

    async def _force_navigate(self, page: Page, target_url: str) -> None:
        """经 about:blank 完全脱离当前文档，再加载目标岗位，强制完整重新渲染。"""
        await page.goto("about:blank")
        await page.wait_for_timeout(400)
        await page.goto(target_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

    @staticmethod
    def _normalize_title(text: str) -> str:
        """归一化标题：去标点空白，保留核心字符（含括号内方向词）。"""
        import re
        text = text or ""
        text = re.sub(r"[\s\-\|｜（）()【】\[\]，,。.、:：;；/]", "", text)
        return text.lower()

    @classmethod
    def _titles_match(cls, got: str, expected: str) -> bool:
        """判断页面实际标题与目标岗位标题是否一致（防串岗）。"""
        if not got or not expected:
            return False
        from difflib import SequenceMatcher
        a = cls._normalize_title(got)
        b = cls._normalize_title(expected)
        if not a or not b:
            return False
        ratio = SequenceMatcher(None, a, b).ratio()
        # 串岗时核心词几乎不重合（如"图形研究员动捕动画" vs "游戏AI研发Agent"），ratio 很低
        return ratio >= 0.6

    @staticmethod
    def _is_jd_valid(text: str) -> bool:
        """检查 JD 内容是否有效（不是导航文本）。"""
        if not text or len(text) < 100:
            return False
        jd_keywords = ["岗位职责", "任职要求", "工作职责", "岗位要求", "任职资格",
                       "工作内容", "职位描述", "投递说明", "面向对象"]
        nav_keywords = ["首页", "岗位投递", "校招答疑", "培养与成长", "校招动态", "切换到社招"]
        jd_count = sum(1 for kw in jd_keywords if kw in text)
        nav_count = sum(1 for kw in nav_keywords if kw in text)
        return jd_count >= 1 and nav_count <= 5

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
