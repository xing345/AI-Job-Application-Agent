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
    role_variants: Optional[List[str]] = Field(
        default_factory=list,
        description="目标岗位的近义变体(如 前端工程师 -> 前端开发/Web前端), 用于模糊匹配"
    )
    exclude_keywords: Optional[List[str]] = Field(default_factory=list, description="排除关键词")
    # 模糊方向推断（query_expander.infer_direction）：浏览器阶段按标题词族判相关
    direction_family: Optional[str] = Field(None, description="方向大类 key，如 ai/frontend")
    direction_category: Optional[str] = Field(None, description="方向大类，如 技术类")
    title_keywords: Optional[List[str]] = Field(
        default_factory=list, description="方向标题词族，用于招聘列表按标题判相关"
    )
    min_salary: Optional[int] = Field(None, description="最低薪资要求")

    # 时间参数
    posted_days_ago: Optional[int] = Field(None, description="发布天数内，默认不限制")
    remote_only: bool = Field(False, description="只搜索远程工作")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    # 招聘类型：campus=校招 / social=社招 / all=都要；默认只找校招
    recruit_type: Optional[str] = Field(
        "campus", description="招聘类型：campus=校招 / social=社招 / all=都要"
    )