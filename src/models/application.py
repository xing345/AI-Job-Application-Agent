"""申请记录与运行记录数据模型。"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(str, Enum):
    """工作流运行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    READY_FOR_REVIEW = "ready_for_review"
    USER_CONFIRMED = "user_confirmed"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    INTERRUPTED = "interrupted"


class ApplicationStatus(str, Enum):
    """单个岗位申请状态。

    各状态必须严格区分，不得混淆：
    - form_filled: 表单已填写完毕
    - waiting_for_submit: 暂停等待用户手动点击提交
    - user_confirmed_submit: 用户确认已提交（输入 continue）
    - page_verified: 恢复后验证页面已跳转/提交成功
    - failed: 填写或提交过程失败
    - unknown: 无法确认是否已提交（需人工复核）
    """

    PENDING = "pending"
    FORM_FILLED = "form_filled"
    WAITING_FOR_SUBMIT = "waiting_for_submit"
    USER_CONFIRMED_SUBMIT = "user_confirmed_submit"
    PAGE_VERIFIED = "page_verified"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ApplicationRecord(BaseModel):
    """单次岗位申请记录。"""

    model_config = ConfigDict(extra="forbid")

    job_url: str
    job_title: str = ""
    company: str = ""
    site_name: str = ""

    status: ApplicationStatus = ApplicationStatus.PENDING
    filled_fields: int = 0
    failed_fields: int = 0
    skipped_fields: int = 0

    error: str = ""
    submitted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)


class RunRecord(BaseModel):
    """一次完整工作流运行记录。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    site_name: str = ""
    status: RunStatus = RunStatus.PENDING

    # 统计
    jobs_discovered: int = 0
    jobs_screened: int = 0
    jd_fetched: int = 0
    matches_completed: int = 0
    applications_selected: int = 0
    applications_filled: int = 0
    applications_submitted: int = 0
    applications_failed: int = 0

    # LLM 调用统计
    llm_calls: int = 0
    llm_failures: int = 0

    # 错误记录（最多保留最近20条）
    errors: List[str] = Field(default_factory=list)

    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None

    def add_error(self, node: str, msg: str) -> None:
        self.errors.append(f"[{node}] {msg}")
        if len(self.errors) > 20:
            self.errors = self.errors[-20:]
