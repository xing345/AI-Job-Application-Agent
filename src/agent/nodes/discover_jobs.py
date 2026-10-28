"""岗位发现节点。

遍历官方招聘网站的分类导航 + 分页，全量收集岗位标题。
用 CSS selector 提取 JobPosting，不调 LLM。
Tavily 关键词搜索默认关闭。
"""
from __future__ import annotations

import logging
import os
from typing import List

from src.agent.state import AgentState
from src.models.job import JobPosting
from src.search.discoverer import discover_jobs as do_discover
from src.search.site_registry import get_site_config
from src.storage import state_db

logger = logging.getLogger(__name__)


def _posting_from_row(row: dict, site_name: str) -> JobPosting:
    return JobPosting(
        title=row.get("job_title") or "",
        company=row.get("company") or "",
        location=row.get("location") or "",
        detail_url=row["job_url"],
        category_path=row.get("category_path") or "",
        site_name=row.get("site_name") or site_name,
    )


async def run(state: AgentState) -> AgentState:
    """LangGraph 节点：岗位发现。"""
    site_name = state.site_name
    if not site_name:
        state.add_error("discover_jobs", "未指定招聘站点（--site 参数）")
        return state

    config = get_site_config(site_name)
    if not config:
        state.add_error("discover_jobs", f"未找到站点配置: {site_name}")
        return state

    logger.info("Discovering jobs from: %s", site_name)

    # 缓存复用：非 --refresh 且库中已有该站点岗位时，直接加载，跳过浏览器发现
    refresh = os.environ.get("JOB_AGENT_REFRESH", "").strip() == "1"
    if not refresh:
        cached_rows = await state_db.get_site_job_postings(site_name)
        if cached_rows:
            cached_jobs = [_posting_from_row(r, site_name) for r in cached_rows]
            state.discovered_jobs = cached_jobs
            logger.info("Loaded %d jobs from cache (site=%s)", len(cached_jobs), site_name)
            print(f"\n[岗位发现] 从本地缓存加载 {len(cached_jobs)} 个岗位（加 --refresh 强制重新发现）")
            return state

    try:
        jobs: List[JobPosting] = await do_discover(config)
        # 去重（按 URL）
        seen = set()
        unique = []
        for j in jobs:
            key = j.dedup_key()
            if key not in seen:
                seen.add(key)
                unique.append(j)

        # 接入 SQLite 岗位去重：记录所有发现的岗位
        new_count = 0
        seen_count = 0
        for job in unique:
            was_seen = await state_db.is_job_seen(job.detail_url)
            if was_seen:
                seen_count += 1
            else:
                new_count += 1
            await state_db.upsert_job(
                job_url=job.detail_url,
                job_title=job.title,
                company=job.company,
                site_name=job.site_name,
                location=job.location,
                category_path=job.category_path,
            )

        # 实际重新发现后，重置初筛标记，强制重新初筛（岗位列表可能已变化）
        await state_db.reset_screen_flags(site_name)

        state.discovered_jobs = unique
        logger.info("Discovered %d unique jobs from %s (new=%d, seen=%d) run_id=%s",
                    len(unique), site_name, new_count, seen_count, state.run_id)
        print(f"\n[岗位发现] {site_name}: 共发现 {len(unique)} 个岗位（新发现 {new_count}，已见过 {seen_count}）")
    except Exception as e:
        state.add_error("discover_jobs", str(e))
        logger.exception("discover_jobs failed")

    return state
