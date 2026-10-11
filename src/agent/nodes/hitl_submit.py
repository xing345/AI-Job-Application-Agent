"""投递结果记录节点。

在用户手动提交后，记录投递结果到 SQLite，移动到下一个岗位。
"""
from __future__ import annotations

import logging
from datetime import datetime

from src.agent.state import AgentState
from src.storage.state_db import record_application

logger = logging.getLogger(__name__)


async def run(state: AgentState) -> AgentState:
    """LangGraph 节点：记录当前岗位投递结果，索引 +1。"""
    if not state.apply_queue:
        return state

    idx = state.current_job_index
    if idx < len(state.apply_queue):
        job = state.apply_queue[idx]
        fields = state.current_fill_fields

        success = all(f.status.value != "failed" for f in fields) if fields else False
        failed_count = sum(1 for f in fields if f.status.value == "failed")

        try:
            await record_application(
                job_url=job.posting.detail_url,
                job_title=job.posting.title,
                company=job.posting.company,
                site_name=job.posting.site_name,
                success=success,
                failed_fields=failed_count,
            )
            logger.info("Application recorded: %s | success=%s", job.posting.title, success)
        except Exception as e:
            state.add_error("hitl_submit", f"记录投递结果失败: {e}")

        print(f"\n[投递完成] {job.posting.title} | 状态: {'成功' if success else '部分失败'} | 失败字段: {failed_count}")

    # 移动到下一个岗位
    state.current_job_index += 1
    state.current_fill_fields = []
    return state
