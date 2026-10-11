"""标题语义初筛节点。

每 20 个标题打包，一次 LLM 调用判断语义相关性。
不要求字面一致，意思相关就算。拿不准的算相关，不误杀。
"""
from __future__ import annotations

import logging
from typing import List

from src.agent.state import AgentState
from src.llm import client as llm
from src.llm.prompts import title_screen_prompt
from src.models.match import TitleScreenResult
from src.models.job import JobPosting

logger = logging.getLogger(__name__)

BATCH_SIZE = 20


async def screen_batch(titles: List[str], target_directions: List[str]) -> TitleScreenResult:
    """批量判断一组标题的语义相关性。"""
    messages = title_screen_prompt(target_directions, titles)
    result = await llm.chat_structured(messages, TitleScreenResult, temperature=0.1)
    return result


async def run(state: AgentState) -> AgentState:
    """LangGraph 节点：标题语义初筛。"""
    if not state.discovered_jobs:
        state.add_error("screen_titles", "没有可筛选的岗位")
        return state

    target_directions: List[str] = []
    if state.profile and state.profile.target_directions:
        target_directions = state.profile.target_directions
    else:
        target_directions = ["软件开发", "AI", "后端", "前端", "算法"]

    jobs = state.discovered_jobs
    titles = [j.title for j in jobs]

    logger.info("Screening %d titles in batches of %d...", len(titles), BATCH_SIZE)

    related_indices: set[int] = set()

    for start in range(0, len(titles), BATCH_SIZE):
        batch = titles[start : start + BATCH_SIZE]
        batch_indices = list(range(start, start + len(batch)))

        try:
            result = await screen_batch(batch, target_directions)
            for rel_idx in result.related_indices:
                if 0 <= rel_idx < len(batch_indices):
                    related_indices.add(batch_indices[rel_idx])
            logger.info("Batch %d-%d: %d related, %d unrelated",
                        start, start + len(batch), len(result.related_indices), len(result.unrelated_indices))
        except Exception as e:
            # LLM 调用失败时，保守地把这批全部算相关（不误杀）
            state.add_error("screen_titles", f"batch {start} 失败，全部保留: {e}")
            related_indices.update(batch_indices)

    screened = [jobs[i] for i in sorted(related_indices)]
    state.screened_jobs = screened

    filtered = len(jobs) - len(screened)
    logger.info("Screen complete: %d -> %d (filtered %d, %.1f%%)",
                len(jobs), len(screened), filtered, filtered / len(jobs) * 100 if jobs else 0)
    print(f"\n[标题初筛] {len(jobs)} -> {len(screened)}（过滤 {filtered} 个）")

    return state
