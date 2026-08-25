"""
职业诊断模块的数据模型
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class ExperienceEntry(BaseModel):
    """一段工作经历 (访谈原始材料)"""
    company: str = Field(default="", description="公司名称")
    role: str = Field(default="", description="职位/角色")
    start: str = Field(default="", description="开始时间 (YYYY-MM)")
    end: str = Field(default="", description="结束时间 (YYYY-MM 或 至今)")
    responsibilities: str = Field(default="", description="主要工作内容")
    achievements: List[str] = Field(default_factory=list, description="业绩/成果")
    tech_stack: List[str] = Field(default_factory=list, description="用到的技术")


class EducationEntry(BaseModel):
    """教育背景 (访谈原始材料)"""
    school: str = Field(default="")
    major: str = Field(default="")
    degree: str = Field(default="")
    start: str = Field(default="")
    end: str = Field(default="")


class ProjectEntry(BaseModel):
    """项目经验 (访谈原始材料)"""
    name: str = Field(default="", description="项目名称")
    description: str = Field(default="", description="项目简介")
    role: str = Field(default="", description="承担角色")
    tech_stack: List[str] = Field(default_factory=list, description="技术栈")
    highlights: List[str] = Field(default_factory=list, description="亮点/成果")


class UserProfile(BaseModel):
    """智能访谈产出的求职者实际情况 (原始材料, 非简历)"""
    name: str = Field(default="", description="姓名")
    email: str = Field(default="", description="邮箱")
    phone: str = Field(default="", description="电话")
    self_introduction: str = Field(default="", description="一句话自我介绍")
    all_skills: List[str] = Field(default_factory=list, description="所有会的东西 (可能很杂)")
    skill_notes: str = Field(default="", description="技能熟练度/使用场景补充")
    work_experience: List[ExperienceEntry] = Field(default_factory=list)
    education: List[EducationEntry] = Field(default_factory=list)
    projects: List[ProjectEntry] = Field(default_factory=list)
    certificates: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    target_hint: str = Field(default="", description="用户自己模糊的职业想法 (可空)")
    industries_interest: List[str] = Field(default_factory=list, description="感兴趣的行业")
    locations: List[str] = Field(default_factory=list, description="期望地点")
    salary_expectation: str = Field(default="", description="期望薪资")
    work_type: str = Field(default="", description="全职/兼职/远程等")
    deal_breakers: List[str] = Field(default_factory=list, description="绝对不接受的条件")


class CareerDirection(BaseModel):
    """岗位方向诊断结果"""
    title: str = Field(..., description="方向名, 如 AI Agent 应用开发工程师")
    summary: str = Field(..., description="为什么适合你 (结合你的技能与经历)")
    target_positions: List[str] = Field(..., description="具体目标职位名")
    keywords: List[str] = Field(..., description="搜索关键词")
    preferred_industries: List[str] = Field(..., description="建议关注的行业")
    skill_highlights: List[str] = Field(..., description="你已有技能中能打的亮点")
    skill_gaps: List[str] = Field(..., description="需要补足/强调的技能缺口")
    advice: str = Field(..., description="给你的具体建议 (简历怎么写、怎么投)")
    market_note: str = Field(..., description="市场情况与可行性说明")
    priority: int = Field(1, ge=1, le=5, description="推荐优先级 1-5")


class CareerAnalysisResult(BaseModel):
    """岗位方向诊断完整结果"""
    directions: List[CareerDirection] = Field(..., description="推荐方向列表 (3-5个)")
    overall_advice: str = Field(..., description="总体建议")


class ResumeBlock(BaseModel):
    """简历中的一段经历/项目/教育条目"""
    title: str = Field(..., description="公司名/项目名/学校名")
    subtitle: str = Field(default="", description="岗位/角色/专业")
    period: str = Field(default="", description="时间段")
    bullets: List[str] = Field(default_factory=list, description="要点 (突出与目标岗位匹配)")


class ResumeDraft(BaseModel):
    """针对性简历草稿 (根据目标岗位定制)"""
    name: str = Field(..., description="姓名")
    contact_line: str = Field(..., description="联系方式行, 如 邮箱 | 电话")
    objective: str = Field(..., description="求职意向 (针对目标岗位定制的一句话)")
    summary: str = Field(..., description="个人简介 (突出与目标岗位匹配的优势)")
    skills: List[str] = Field(..., description="核心技能 (按与目标岗位相关度排序)")
    work_experience: List[ResumeBlock] = Field(..., description="工作经历")
    projects: List[ResumeBlock] = Field(..., description="项目经验")
    education: List[ResumeBlock] = Field(..., description="教育背景")
    certificates: List[str] = Field(default_factory=list, description="证书")
    languages: List[str] = Field(default_factory=list, description="语言能力")
