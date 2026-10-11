"""用户画像与简历数据模型。

只做结构化表示和加载，不做简历修改/生成。
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


class Education(BaseModel):
    school: str = ""
    major: str = ""
    degree: str = ""  # 本科/硕士/博士/大专
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: str = ""


class WorkExperience(BaseModel):
    company: str = ""
    position: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    responsibilities: str = ""
    achievements: str = ""


class ProjectExperience(BaseModel):
    name: str = ""
    role: str = ""
    tech_stack: List[str] = Field(default_factory=list)
    description: str = ""
    achievements: str = ""


class UserProfile(BaseModel):
    """候选人画像。"""

    name: str = ""
    phone: str = ""
    email: str = ""

    education: List[Education] = Field(default_factory=list)
    work_experience: List[WorkExperience] = Field(default_factory=list)
    projects: List[ProjectExperience] = Field(default_factory=list)

    skills: List[str] = Field(default_factory=list)

    target_cities: List[str] = Field(default_factory=list)
    target_directions: List[str] = Field(default_factory=list)
    expected_salary: str = ""
    available_date: str = ""  # 可到岗时间

    self_introduction: str = ""

    def to_resume_text(self) -> str:
        """把画像转成纯文本简历，供 LLM 匹配时使用。"""
        lines: list[str] = []
        lines.append(f"姓名：{self.name}")
        if self.phone:
            lines.append(f"电话：{self.phone}")
        if self.email:
            lines.append(f"邮箱：{self.email}")
        if self.self_introduction:
            lines.append(f"个人简介：{self.self_introduction}")

        if self.education:
            lines.append("\n【教育背景】")
            for e in self.education:
                period = f"{e.start_date or ''} - {e.end_date or ''}"
                lines.append(f"- {e.school} | {e.major} | {e.degree} | {period}")
                if e.description:
                    lines.append(f"  {e.description}")

        if self.work_experience:
            lines.append("\n【工作/实习经历】")
            for w in self.work_experience:
                period = f"{w.start_date or ''} - {w.end_date or ''}"
                lines.append(f"- {w.company} | {w.position} | {period}")
                if w.responsibilities:
                    lines.append(f"  职责：{w.responsibilities}")
                if w.achievements:
                    lines.append(f"  成果：{w.achievements}")

        if self.projects:
            lines.append("\n【项目经历】")
            for p in self.projects:
                tech = "、".join(p.tech_stack) if p.tech_stack else ""
                lines.append(f"- {p.name} | 角色：{p.role} | 技术栈：{tech}")
                if p.description:
                    lines.append(f"  描述：{p.description}")
                if p.achievements:
                    lines.append(f"  成果：{p.achievements}")

        if self.skills:
            lines.append("\n【技能】")
            lines.append("、".join(self.skills))

        if self.target_directions:
            lines.append(f"\n【目标方向】{'、'.join(self.target_directions)}")
        if self.target_cities:
            lines.append(f"【目标城市】{'、'.join(self.target_cities)}")
        if self.expected_salary:
            lines.append(f"【期望薪资】{self.expected_salary}")
        if self.available_date:
            lines.append(f"【可到岗时间】{self.available_date}")

        return "\n".join(lines)


class Resume(BaseModel):
    """从 PDF 或 JSON 加载的结构化简历，只解析不修改。"""

    raw_text: str = ""
    profile: Optional[UserProfile] = None
    source_file: str = ""

    def full_text(self) -> str:
        if self.profile:
            return self.profile.to_resume_text()
        return self.raw_text
