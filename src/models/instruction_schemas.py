"""
指令相关的数据模型定义
包含目标公司/岗位指令等
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class TargetInstructionSchema(BaseModel):
    """目标公司/岗位指令"""
    # 基本信息
    company: str = Field(..., description="目标公司名称")
    role: str = Field(..., description="目标职位名称")
    location: Optional[str] = Field(None, description="工作地点")

    # 搜索参数
    keywords: Optional[List[str]] = Field(default_factory=list, description="附加关键词")
    exclude_keywords: Optional[List[str]] = Field(default_factory=list, description="排除关键词")
    min_salary: Optional[int] = Field(None, description="最低薪资要求")

    # 时间参数
    posted_days_ago: Optional[int] = Field(None, description="发布天数内，默认不限制")
    remote_only: bool = Field(False, description="只搜索远程工作")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")