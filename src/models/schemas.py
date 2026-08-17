"""
数据模型定义模块
包含简历、职位、申请日志等核心数据结构
"""

from pydantic import BaseModel, Field, HttpUrl, EmailStr
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class EducationLevel(str, Enum):
    """教育程度枚举"""
    HIGH_SCHOOL = "高中"
    BACHELOR = "本科"
    MASTER = "硕士"
    PHD = "博士"
    OTHER = "其他"


class WorkExperience(BaseModel):
    """工作经历模型"""
    company: str = Field(..., description="公司名称")
    position: str = Field(..., description="职位名称")
    start_date: str = Field(..., description="开始日期，格式: YYYY-MM")
    end_date: Optional[str] = Field(None, description="结束日期，格式: YYYY-MM")
    description: str = Field(..., description="工作描述")
    achievements: Optional[List[str]] = Field(default_factory=list, description="主要成就")


class Education(BaseModel):
    """教育背景模型"""
    school: str = Field(..., description="学校名称")
    major: str = Field(..., description="专业")
    degree: EducationLevel = Field(..., description="学位")
    start_date: str = Field(..., description="开始日期，格式: YYYY-MM")
    end_date: str = Field(..., description="结束日期，格式: YYYY-MM")
    gpa: Optional[float] = Field(None, description="GPA")
    honors: Optional[str] = Field(None, description="荣誉奖项")


class ProjectExperience(BaseModel):
    """项目经验模型"""
    name: str = Field(..., description="项目名称")
    description: str = Field(..., description="项目描述")
    technologies: List[str] = Field(..., description="使用的技术栈")
    role: str = Field(..., description="担任角色")
    duration: str = Field(..., description="项目时长")
    achievements: Optional[List[str]] = Field(default_factory=list, description="项目成果")


class ResumeSchema(BaseModel):
    """简历数据结构模型"""
    # 基本信息
    name: str = Field(..., description="姓名")
    email: EmailStr = Field(..., description="邮箱")
    phone: Optional[str] = Field(None, description="电话")
    linkedin: Optional[HttpUrl] = Field(None, description="LinkedIn 链接")
    github: Optional[HttpUrl] = Field(None, description="GitHub 链接")

    # 个人简介
    summary: str = Field(..., description="个人简介")
    skills: List[str] = Field(..., description="技能列表")

    # 工作经历
    work_experience: List[WorkExperience] = Field(..., description="工作经历")

    # 教育背景
    education: List[Education] = Field(..., description="教育背景")

    # 项目经验
    projects: List[ProjectExperience] = Field(..., description="项目经验")

    # 其他信息
    certifications: Optional[List[str]] = Field(default_factory=list, description="证书")
    languages: Optional[List[str]] = Field(default_factory=list, description="语言能力")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")


class JobSchema(BaseModel):
    """职位数据结构模型"""
    # 职位基本信息
    title: str = Field(..., description="职位名称")
    company: str = Field(..., description="公司名称")
    location: str = Field(..., description="工作地点")
    remote: bool = Field(False, description="是否远程")

    # 职位详情
    description: str = Field(..., description="职位描述")
    requirements: List[str] = Field(..., description="职位要求")
    benefits: Optional[List[str]] = Field(default_factory=list, description="福利待遇")

    # 申请信息
    application_url: HttpUrl = Field(..., description="申请链接")
    deadline: Optional[str] = Field(None, description="截止日期")
    posted_at: datetime = Field(default_factory=datetime.now, description="发布时间")

    # 匹配信息
    match_score: float = Field(0.0, ge=0.0, le=100.0, description="匹配分数")
    match_reasons: Optional[List[str]] = Field(default_factory=list, description="匹配原因")

    # 元数据
    source: str = Field(..., description="数据来源")
    crawled_at: datetime = Field(default_factory=datetime.now, description="抓取时间")


class ApplicationStatus(str, Enum):
    """申请状态枚举"""
    PENDING = "待处理"
    SUBMITTED = "已提交"
    REVIEWING = "审核中"
    REJECTED = "已拒绝"
    INTERVIEW = "面试中"
    OFFER = "已录用"
    WITHDRAWN = "已撤回"


class ApplicationLogSchema(BaseModel):
    """申请日志模型"""
    # 申请基本信息
    job_id: str = Field(..., description="职位ID")
    resume_id: str = Field(..., description="简历ID")
    application_url: HttpUrl = Field(..., description="申请链接")

    # 申请状态
    status: ApplicationStatus = Field(ApplicationStatus.PENDING, description="申请状态")
    submitted_at: Optional[datetime] = Field(None, description="提交时间")
    last_updated: datetime = Field(default_factory=datetime.now, description="最后更新时间")

    # 申请详情
    form_data: Dict[str, Any] = Field(default_factory=dict, description="表单数据")
    attachments: Optional[List[str]] = Field(default_factory=list, description="附件列表")

    # 匹配信息
    match_score: float = Field(0.0, ge=0.0, le=100.0, description="匹配分数")
    match_reasons: Optional[List[str]] = Field(default_factory=list, description="匹配原因")

    # 错误信息
    error_message: Optional[str] = Field(None, description="错误信息")
    error_details: Optional[Dict[str, Any]] = Field(None, description="错误详情")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")


# 数据模型别名，方便导入使用
Resume = ResumeSchema
Job = JobSchema
ApplicationLog = ApplicationLogSchema

__all__ = [
    "ResumeSchema",
    "JobSchema",
    "ApplicationLogSchema",
    "Resume",
    "Job",
    "ApplicationLog",
    "ApplicationStatus",
    "EducationLevel"
]