"""岗位发现节点。

遍历官方招聘网站的分类导航 + 分页，全量收集岗位标题。
用 CSS selector 提取 JobPosting，不调 LLM。
Tavily 关键词搜索默认关闭。
"""
from __future__ import annotations

import logging
from typing import List

from src.agent.state import AgentState
from src.models.job import JobPosting
from src.search.discoverer import discover_jobs as do_discover
from src.search.site_registry import get_site_config

logger = logging.getLogger(__name__)


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

        state.discovered_jobs = unique
        logger.info("Discovered %d unique jobs from %s", len(unique), site_name)
        print(f"\n[岗位发现] {site_name}: 共发现 {len(unique)} 个岗位")
    except Exception as e:
        state.add_error("discover_jobs", str(e))
        logger.exception("discover_jobs failed")

    return state
