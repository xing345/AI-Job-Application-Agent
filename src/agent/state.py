"""LangGraph 共享状态。"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from src.models.job import JobDetail, JobPosting
from src.models.match import FillField, MatchResult
from src.models.profile import Resume, UserProfile


class AgentState(BaseModel):
    """Agent 全流程共享状态。"""

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
    resume_path: str = ""
    profile_path: str = ""

    def add_error(self, node: str, msg: str) -> None:
        self.errors.append(f"[{node}] {msg}")
