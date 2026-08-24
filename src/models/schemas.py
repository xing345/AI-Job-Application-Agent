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
    industry: Optional[str] = Field(None, description="所属行业")
    company_size: Optional[str] = Field(None, description="公司规模")


class Education(BaseModel):
    """教育背景模型"""
    school: str = Field(..., description="学校名称")
    major: str = Field(..., description="专业")
    degree: EducationLevel = Field(..., description="学位")
    start_date: str = Field(..., description="开始日期，格式: YYYY-MM")
    end_date: str = Field(..., description="结束日期，格式: YYYY-MM")
    gpa: Optional[float] = Field(None, description="GPA")
    honors: Optional[str] = Field(None, description="荣誉奖项")
    school_type: Optional[str] = Field(None, description="学校类型")


class ProjectExperience(BaseModel):
    """项目经验模型"""
    name: str = Field(..., description="项目名称")
    description: str = Field(..., description="项目描述")
    technologies: List[str] = Field(..., description="使用的技术栈")
    role: str = Field(..., description="担任角色")
    duration: str = Field(..., description="项目时长")
    achievements: Optional[List[str]] = Field(default_factory=list, description="项目成果")
    industry: Optional[str] = Field(None, description="项目所属行业")


class CareerObjective(BaseModel):
    """职业目标模型"""
    target_positions: List[str] = Field(..., description="目标职位")
    preferred_industries: List[str] = Field(..., description="偏好行业")
    location_preference: List[str] = Field(..., description="地点偏好")
    salary_expectation: Optional[str] = Field(None, description="薪资期望")
    work_type_preference: Optional[str] = Field(None, description="工作类型偏好")
    career_growth_focus: List[str] = Field(..., description="职业发展重点")


class SoftSkills(BaseModel):
    """软技能模型"""
    communication: Optional[List[str]] = Field(default_factory=list, description="沟通能力")
    leadership: Optional[List[str]] = Field(default_factory=list, description="领导力")
    teamwork: Optional[List[str]] = Field(default_factory=list, description="团队协作")
    problem_solving: Optional[List[str]] = Field(default_factory=list, description="解决问题")
    creativity: Optional[List[str]] = Field(default_factory=list, description="创新思维")
    adaptability: Optional[List[str]] = Field(default_factory=list, description="适应能力")


class CareerConstraints(BaseModel):
    """职业约束模型"""
    excluded_companies: List[str] = Field(default_factory=list, description="排除的公司")
    excluded_industries: List[str] = Field(default_factory=list, description="排除的行业")
    excluded_positions: List[str] = Field(default_factory=list, description="排除的职位")
    compensation_floor: Optional[str] = Field(None, description="薪资底线")
    compensation_ceiling: Optional[str] = Field(None, description="薪资上限")
    location_constraints: List[str] = Field(default_factory=list, description="地点限制")
    travel_requirements: Optional[str] = Field(None, description="出差要求")
    work_schedule: Optional[str] = Field(None, description="工作时间要求")


class PersonalityTraits(BaseModel):
    """性格特质模型"""
    work_style: List[str] = Field(default_factory=list, description="工作风格")
    motivation_factors: List[str] = Field(default_factory=list, description="激励因素")
    stress_response: Optional[str] = Field(None, description="压力应对方式")
    learning_style: List[str] = Field(default_factory=list, description="学习方式")
    cultural_fit: List[str] = Field(default_factory=list, description="文化匹配")


class WorkExperience(BaseModel):
    """工作经历模型"""
    company: str = Field(..., description="公司名称")
    position: str = Field(..., description="职位名称")
    start_date: str = Field(..., description="开始日期，格式: YYYY-MM")
    end_date: Optional[str] = Field(None, description="结束日期，格式: YYYY-MM")
    description: str = Field(..., description="工作描述")
    achievements: Optional[List[str]] = Field(default_factory=list, description="主要成就")
    industry: Optional[str] = Field(None, description="所属行业")
    company_size: Optional[str] = Field(None, description="公司规模")
    technologies_used: Optional[List[str]] = Field(default_factory=list, description="使用技术")


class Education(BaseModel):
    """教育背景模型"""
    school: str = Field(..., description="学校名称")
    major: str = Field(..., description="专业")
    degree: EducationLevel = Field(..., description="学位")
    start_date: str = Field(..., description="开始日期，格式: YYYY-MM")
    end_date: str = Field(..., description="结束日期，格式: YYYY-MM")
    gpa: Optional[float] = Field(None, description="GPA")
    honors: Optional[str] = Field(None, description="荣誉奖项")
    school_type: Optional[str] = Field(None, description="学校类型")


class ProjectExperience(BaseModel):
    """项目经验模型"""
    name: str = Field(..., description="项目名称")
    description: str = Field(..., description="项目描述")
    technologies: List[str] = Field(..., description="使用的技术栈")
    role: str = Field(..., description="担任角色")
    duration: str = Field(..., description="项目时长")
    achievements: Optional[List[str]] = Field(default_factory=list, description="项目成果")
    industry: Optional[str] = Field(None, description="项目所属行业")


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


class DynamicUserPersona(BaseModel):
    """动态用户画像模型 - v2.0 新增"""
    # 基本信息
    name: str = Field(..., description="姓名")
    email: EmailStr = Field(..., description="邮箱")
    phone: Optional[str] = Field(None, description="电话")

    # 核心技能与能力
    technical_skills: List[str] = Field(..., description="技术技能")
    soft_skills: SoftSkills = Field(..., description="软技能")
    domain_knowledge: Dict[str, int] = Field(..., description="领域知识掌握程度")

    # 职业目标
    career_objective: CareerObjective = Field(..., description="职业目标")
    personality_traits: PersonalityTraits = Field(..., description="性格特质")

    # 约束条件
    constraints: CareerConstraints = Field(..., description="职业约束")

    # 隐性特征
    work_preferences: Dict[str, Any] = Field(..., description="工作偏好")
    motivators: List[str] = Field(..., description="激励因素")
    deal_breakers: List[str] = Field(..., description="绝对拒绝的条件")

    # 分析维度
    strengths: List[str] = Field(..., description="核心竞争力")
    weaknesses: List[str] = Field(..., description="待改进领域")
    ideal_work_environment: List[str] = Field(..., description="理想工作环境")

    # 生成元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    version: str = Field("1.0", description="版本号")
    confidence_score: float = Field(0.0, ge=0.0, le=1.0, description="置信度")


class ResumePrompt(BaseModel):
    """简历与用户提示组合模型"""
    resume_data: ResumeSchema = Field(..., description="原始简历数据")
    user_prompt: str = Field(..., description="用户自定义描述文本")
    generated_persona: Optional[DynamicUserPersona] = Field(None, description="生成的用户画像")

    # 生成参数
    llm_model: str = Field("gpt-4", description="使用的LLM模型")
    generation_timestamp: datetime = Field(default_factory=datetime.now, description="生成时间")


class MatchAnalysisResult(BaseModel):
    """职位匹配分析结果"""
    job_id: str = Field(..., description="职位ID")
    match_score: float = Field(..., ge=0.0, le=100.0, description="匹配分数")

    # 详细分析
    strengths_match: List[str] = Field(..., description="优势匹配点")
    weaknesses_mismatch: List[str] = Field(..., description="劣势不匹配点")
    cultural_fit_analysis: str = Field(..., description="文化匹配分析")
    growth_potential: str = Field(..., description="成长潜力评估")
    compensation_evaluation: str = Field(..., description="薪资评估")

    # 决策建议
    recommendation: str = Field(..., description="推荐意见")
    priority_level: int = Field(..., ge=1, le=5, description="优先级")
    estimated_success_rate: float = Field(..., ge=0.0, le=1.0, description="预计成功率")

    # 分析时间
    analyzed_at: datetime = Field(default_factory=datetime.now, description="分析时间")


class BrowserAction(BaseModel):
    """浏览器操作指令"""
    action_type: str = Field(..., description="操作类型: click, type, select, wait, navigate")
    target: str = Field(..., description="目标元素描述或XPath/CSS选择器")
    value: Optional[str] = Field(None, description="输入值（如果是type操作）")
    timeout: int = Field(10, description="超时时间（秒）")
    description: str = Field(..., description="操作描述")


class FormFieldSchema(BaseModel):
    """表单字段模型"""
    field_name: str = Field(..., description="字段名称")
    field_type: str = Field(..., description="字段类型: text, email, tel, select, checkbox, radio, file")
    label: str = Field(..., description="字段标签")
    placeholder: Optional[str] = Field(None, description="占位文本")
    required: bool = Field(..., description="是否必填")
    options: Optional[List[str]] = Field(None, description="选项（如果是select/radio）")
    css_selector: str = Field(..., description="CSS选择器")
    xpath: str = Field(..., description="XPath")
    value: Optional[str] = Field(None, description="值")
    validation_rules: Optional[Dict[str, Any]] = Field(None, description="验证规则")


class FormSchema(BaseModel):
    """表单数据模型"""
    form_url: str = Field(..., description="表单URL")
    form_title: str = Field(..., description="表单标题")
    fields: List[FormFieldSchema] = Field(..., description="表单字段列表")
    submit_button: Dict[str, str] = Field(..., description="提交按钮信息")

    # 表单分析
    estimated_completion_time: int = Field(..., description="预计完成时间（秒）")
    difficulty_level: str = Field(..., description="难度级别: easy, medium, hard")
    form_type: str = Field(..., description="表单类型: standard, multi-step, wizard")

    # 元数据
    analyzed_at: datetime = Field(default_factory=datetime.now, description="分析时间")


# 数据模型别名，方便导入使用
Resume = ResumeSchema
Job = JobSchema
ApplicationLog = ApplicationLogSchema
UserPersona = DynamicUserPersona
PersonaPrompt = ResumePrompt
MatchResult = MatchAnalysisResult
BrowserOp = BrowserAction

class ReflectionResult(BaseModel):
    """反思结果数据模型"""
    failure_reason_category: str = Field(..., description="失败原因分类：经验年限不足、技术栈不匹配、学历/身份限制、竞聘过于激烈等")
    root_cause_analysis: str = Field(..., description="深度分析为什么这个画像与这个岗位不匹配的一句话总结")
    actionable_advice: List[str] = Field(..., description="对未来投递的具体改进建议")
    should_update_persona: bool = Field(..., description="是否需要更新 DynamicUserPersona")


class StrategyRule(BaseModel):
    """策略规则数据模型"""
    rule_type: str = Field(..., description="规则类型：搜索过滤、匹配调整、应用策略等")
    rule_content: str = Field(..., description="规则内容")
    confidence_score: float = Field(ge=0.0, le=1.0, description="置信度")
    is_active: bool = Field(True, description="是否激活")
    created_at: datetime = Field(default_factory=datetime.now)
    last_used: Optional[datetime] = Field(None, description="最后使用时间")


class ApplicationWithReflection(BaseModel):
    """包含反思信息的申请记录"""
    # 基本申请信息
    id: Optional[int] = Field(None, description="申请ID")
    job_id: str = Field(..., description="职位ID")
    company_name: str = Field(..., description="公司名称")
    job_title: str = Field(..., description="职位名称")
    match_score: float = Field(..., description="匹配分数")
    status: str = Field(..., description="申请状态")
    url: Optional[str] = Field(None, description="职位URL")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    error_message: Optional[str] = Field(None, description="错误信息")
    search_source: Optional[str] = Field(None, description="搜索来源")

    # 反思信息（可选）
    reflection: Optional[ReflectionResult] = Field(None, description="反思结果")

    # 策略规则（可选）
    applied_rules: List[StrategyRule] = Field(default_factory=list, description="应用的战略规则")


__all__ = [
    "ResumeSchema",
    "JobSchema",
    "ApplicationLogSchema",
    "DynamicUserPersona",
    "ResumePrompt",
    "MatchAnalysisResult",
    "BrowserAction",
    "FormFieldSchema",
    "FormSchema",
    "ReflectionResult",
    "StrategyRule",
    "ApplicationWithReflection",
    "Resume",
    "Job",
    "ApplicationLog",
    "UserPersona",
    "PersonaPrompt",
    "MatchResult",
    "BrowserOp",
    "ApplicationStatus",
    "EducationLevel",
    "CareerObjective",
    "SoftSkills",
    "CareerConstraints",
    "PersonalityTraits",
    "WorkExperience",
    "Education",
    "ProjectExperience"
]