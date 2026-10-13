"""匹配结果与表单字段数据模型。"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class FillStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    FAILED = "failed"
    SKIPPED = "skipped"
    NEEDS_USER_INPUT = "needs_user_input"


class MatchResult(BaseModel):
    """LLM 深度匹配结果。"""

    model_config = ConfigDict(extra="forbid")

    job_url: str = ""  # 由代码后设置，LLM 不输出
    job_title: str = ""
    company: str = ""

    score: int = Field(0, ge=0, le=100, description="匹配度分数 0-100")
    direction_match: bool = False
    direction_reason: str = ""

    # 硬性要求统计
    hard_requirements_total: int = Field(0, description="JD 中识别出的硬性要求总数")
    hard_requirements_met: int = Field(0, description="候选人满足的硬性要求数量")

    matched_points: List[str] = Field(default_factory=list, description="匹配点列表（格式：[硬性/加分] 内容）")
    missing_points: List[str] = Field(default_factory=list, description="缺失点列表（格式：[硬性/加分] 内容）")
    reason: str = ""  # LLM 生成的综合匹配理由，包含评分依据


class FillField(BaseModel):
    """申请表单字段。"""

    model_config = ConfigDict(extra="forbid")

    # Playwright 提取的元素信息
    label: str = ""
    placeholder: str = ""
    name: str = ""
    field_type: str = ""  # text/email/number/textarea/select/radio/checkbox/file/hidden
    options: List[str] = Field(default_factory=list)  # select/radio 的选项
    element_selector: str = ""  # 用于定位元素的 CSS selector

    # LLM 生成的填写信息
    semantic_type: str = ""  # 语义分类，如 name/phone/email/education/experience/open_question
    value: Optional[str] = None  # 填写值，null 表示不确定不编造

    status: FillStatus = FillStatus.PENDING
    error: str = ""


class TitleScreenResult(BaseModel):
    """标题语义初筛批量结果。"""

    model_config = ConfigDict(extra="forbid")

    related_indices: List[int] = Field(default_factory=list)
    unrelated_indices: List[int] = Field(default_factory=list)


class QuotaSortResult(BaseModel):
    """投递配额排序结果。"""

    model_config = ConfigDict(extra="forbid")

    recommended: List[int] = Field(default_factory=list, description="推荐的岗位序号列表")
    reasoning: str = ""
