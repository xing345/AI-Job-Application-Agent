"""岗位相关数据模型。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class JobPosting(BaseModel):
    """列表页提取的岗位摘要信息。"""

    title: str
    company: str = ""
    location: str = ""
    detail_url: str
    category_path: str = ""  # 分类导航路径，如 "技术类/后端开发"
    site_name: str = ""

    def dedup_key(self) -> str:
        return self.detail_url


class JobDetail(BaseModel):
    """详情页提取的完整岗位信息。"""

    posting: JobPosting
    full_jd: str = ""  # 完整 JD 原文，不截断
    responsibilities: str = ""  # 岗位职责
    requirements: str = ""  # 任职要求
    salary: str = ""
    location: str = ""
    publish_date: str = ""
    apply_url: str = ""  # 申请入口 URL

    def jd_for_match(self) -> str:
        """给 LLM 匹配用的 JD 文本。"""
        parts: list[str] = []
        if self.responsibilities:
            parts.append(f"【岗位职责】\n{self.responsibilities}")
        if self.requirements:
            parts.append(f"【任职要求】\n{self.requirements}")
        if not parts and self.full_jd:
            parts.append(self.full_jd)
        return "\n\n".join(parts)
