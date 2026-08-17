"""
面试相关的数据模型定义
包含面试详情和邮件分类等
"""

from pydantic import BaseModel, Field, EmailStr, HttpUrl
from typing import Optional, Literal, List, Dict
from datetime import datetime
from enum import Enum


class InterviewType(str, Enum):
    """面试类型枚举"""
    TECHNICAL = "技术面试"
    PHONE_SCREEN = "电话初筛"
    ONSITE = "现场面试"
    VIDEO = "视频面试"
    HR = "HR面试"
    FINAL = "终面"
    CODING = "编程测试"
    ASSESSMENT = "测评"
    OTHER = "其他"


class InterviewStatus(str, Enum):
    """面试状态枚举"""
    SCHEDULED = "已安排"
    CONFIRMED = "已确认"
    CANCELLED = "已取消"
    COMPLETED = "已完成"
    NO_SHOW = "缺席"


class InterviewDetailSchema(BaseModel):
    """面试详情数据模型"""
    # 基本信息
    job_title: str = Field(..., description="职位名称")
    company_name: str = Field(..., description="公司名称")
    interview_type: InterviewType = Field(..., description="面试类型")

    # 时间信息
    interview_datetime: datetime = Field(..., description="面试时间")
    duration_minutes: Optional[int] = Field(None, description="面试时长（分钟）")
    timezone: str = Field("UTC", description="时区")

    # 地点信息
    location_type: Literal["ONLINE", "ONSITE", "PHONE"] = Field(..., description="面试地点类型")
    location_details: Optional[str] = Field(None, description="详细地址（如果是现场面试）")
    meeting_link: Optional[HttpUrl] = Field(None, description="会议链接（如果是线上面试）")

    # 联系信息
    contact_name: Optional[str] = Field(None, description="联系人姓名")
    contact_email: Optional[EmailStr] = Field(None, description="联系人邮箱")
    contact_phone: Optional[str] = Field(None, description="联系人电话")

    # 补充信息
    interviewers: Optional[List[str]] = Field(default_factory=list, description="面试官列表")
    agenda: Optional[str] = Field(None, description="面试议程")
    notes: Optional[str] = Field(None, description="备注信息")

    # 状态信息
    status: InterviewStatus = Field(InterviewStatus.SCHEDULED, description="面试状态")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    class Config:
        json_encoders = {
            'datetime': lambda v: v.isoformat() if v else None,
            'HttpUrl': lambda v: str(v) if v else None
        }


class InterviewReminderSchema(BaseModel):
    """面试提醒数据模型"""
    minutes_before: int = Field(30, description="提前提醒时间（分钟）")
    email_notification: bool = Field(True, description="是否发送邮件提醒")
    push_notification: bool = Field(True, description="是否推送通知")
    custom_message: Optional[str] = Field(None, description="自定义提醒消息")


class EmailCategorySchema(BaseModel):
    """邮件分类数据模型"""
    category: Literal['INTERVIEW_INVITE', 'ONLINE_TEST', 'REJECTED', 'OTHER'] = Field(..., description="邮件类别")
    company_name: str = Field(..., description="公司名称")
    summary: str = Field(..., description="邮件内容摘要")
    extracted_interview_details: Optional[InterviewDetailSchema] = Field(None, description="提取的面试详情")
    confidence_score: float = Field(0.0, ge=0.0, le=1.0, description="识别置信度")
    email_from: Optional[str] = Field(None, description="发件人邮箱")
    email_subject: Optional[str] = Field(None, description="邮件主题")
    email_timestamp: Optional[datetime] = Field(None, description="邮件时间戳")

    class Config:
        json_encoders = {
            'datetime': lambda v: v.isoformat() if v else None
        }


class CalendarEventSchema(BaseModel):
    """日历事件数据模型"""
    event_id: Optional[str] = Field(None, description="事件ID")
    title: str = Field(..., description="事件标题")
    description: str = Field(..., description="事件描述")
    start_time: datetime = Field(..., description="开始时间")
    end_time: datetime = Field(..., description="结束时间")
    location: Optional[str] = Field(None, description="地点")
    attendees: Optional[List[str]] = Field(default_factory=list, description="参与者")
    reminders: Optional[List[Dict]] = Field(default_factory=list, description="提醒设置")

    class Config:
        json_encoders = {
            'datetime': lambda v: v.isoformat() if v else None
        }


# 面试详情的补充信息模型
class InterviewPreparationSchema(BaseModel):
    """面试准备信息"""
    documents_needed: List[str] = Field(default_factory=list, description="需要的文档")
    skills_to_review: List[str] = Field(default_factory=list, description="需要复习的技能")
    questions_to_prepare: List[str] = Field(default_factory=list, description="需要准备的问题")
    research_topics: List[str] = Field(default_factory=list, description="研究主题")


class InterviewFeedbackSchema(BaseModel):
    """面试反馈信息"""
    feedback_text: Optional[str] = Field(None, description="反馈内容")
    next_steps: Optional[str] = Field(None, description="后续步骤")
    rating: Optional[int] = Field(None, ge=1, le=5, description="面试评分")
    notes: Optional[str] = Field(None, description="备注信息")


__all__ = [
    "InterviewType",
    "InterviewStatus",
    "InterviewDetailSchema",
    "InterviewReminderSchema",
    "EmailCategorySchema",
    "CalendarEventSchema",
    "InterviewPreparationSchema",
    "InterviewFeedbackSchema"
]