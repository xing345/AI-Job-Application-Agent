"""LangGraph 共享状态。"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.models.application import ApplicationStatus, RunStatus
from src.models.job import JobDetail, JobPosting
from src.models.match import FillField, MatchResult
from src.models.profile import Resume, UserProfile


class AgentState(BaseModel):
    """Agent 全流程共享状态。"""

    model_config = ConfigDict(extra="forbid")

    # 运行标识与状态
    run_id: str = ""
    status: RunStatus = RunStatus.PENDING
    current_application_status: ApplicationStatus = ApplicationStatus.PENDING

    # 输入
    profile: Optional[UserProfile] = None
    resume: Optional[Resume] = None

    # 岗位发现
    discovered_jobs: List[JobPosting] = Field(default_factory=list)

    # 标题初筛后保留的岗位
    screened_jobs: List[JobPosting] = Field(default_factory=list)

    # JD 详情
    job_details: List[JobDetail] = Field(default_factory=list)

    # 匹配结果
    match_results: List[MatchResult] = Field(default_factory=list)

    # 用户确认后的投递队列
    apply_queue: List[JobDetail] = Field(default_factory=list)
    current_job_index: int = 0

    # 当前岗位填写结果
    current_fill_fields: List[FillField] = Field(default_factory=list)
    fill_results: Dict[str, List[FillField]] = Field(default_factory=dict)

    # 错误记录
    errors: List[str] = Field(default_factory=list)

    # 运行配置
    site_name: str = ""
    job_urls: List[str] = Field(default_factory=list)  # 手动指定的岗位 URL（跳过发现）
    apply_url: str = ""  # 直达填表链接：直接打开并填表，跳过发现/初筛/匹配
    resume_path: str = ""
    profile_path: str = ""

    def add_error(self, node: str, msg: str) -> None:
        self.errors.append(f"[{node}] {msg}")
