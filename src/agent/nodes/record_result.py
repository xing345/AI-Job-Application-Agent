"""投递结果记录节点。

在用户手动提交并验证页面状态后，记录投递结果到 SQLite，移动到下一个岗位。

状态流转（在 fill_application 节点中设置）：
  FORM_FILLED → WAITING_FOR_SUBMIT → USER_CONFIRMED_SUBMIT → PAGE_VERIFIED / UNKNOWN

本节点只负责记录和索引移动，不做页面操作。
"""
from __future__ import annotations

import logging
from datetime import datetime

from src.agent.state import AgentState
from src.models.application import ApplicationStatus
from src.storage import state_db

logger = logging.getLogger(__name__)


async def run(state: AgentState) -> AgentState:
    """LangGraph 节点：记录当前岗位投递结果，索引 +1。"""
    if not state.apply_queue:
        return state

    idx = state.current_job_index
    if idx >= len(state.apply_queue):
        state.add_error("record_result", f"岗位索引越界: {idx}/{len(state.apply_queue)}")
        return state

    job = state.apply_queue[idx]
    fields = state.current_fill_fields
    app_status = state.current_application_status

    # 根据状态判断投递结果
    if app_status == ApplicationStatus.PAGE_VERIFIED:
        success = True
        status_label = "已验证提交成功"
    elif app_status == ApplicationStatus.USER_CONFIRMED_SUBMIT:
        # 用户确认提交但页面未验证（可能页面未跳转），标记为部分成功
        success = True
        status_label = "用户确认提交（页面未验证）"
    elif app_status == ApplicationStatus.UNKNOWN:
        success = False
        status_label = "提交状态未知，需人工复核"
    else:
        success = False
        status_label = f"未完成提交（状态: {app_status.value}）"

    filled_count = sum(1 for f in fields if f.status.value == "filled")
    failed_count = sum(1 for f in fields if f.status.value == "failed")
    skipped_count = sum(1 for f in fields if f.status.value == "skipped")

    try:
        await state_db.record_application(
            job_url=job.posting.detail_url,
            job_title=job.posting.title,
            company=job.posting.company,
            site_name=job.posting.site_name,
            success=success,
            failed_fields=failed_count,
            status=app_status.value,
        )
        logger.info(
            "Application recorded: %s | status=%s | filled=%d failed=%d skipped=%d run_id=%s",
            job.posting.title, app_status.value, filled_count, failed_count, skipped_count, state.run_id,
        )
    except Exception as e:
        state.add_error("record_result", f"记录投递结果失败: {e}")
        logger.exception("record_application failed")

    print(f"\n[投递记录] {job.posting.title}")
    print(f"  状态: {status_label}")
    print(f"  字段: 成功={filled_count} 失败={failed_count} 跳过={skipped_count}")
    if app_status == ApplicationStatus.UNKNOWN:
        print("  ⚠️  提交状态无法确认，请手动检查投递是否成功")

    # 移动到下一个岗位，重置当前状态
    state.current_job_index += 1
    state.current_fill_fields = []
    state.current_application_status = ApplicationStatus.PENDING

    return state
