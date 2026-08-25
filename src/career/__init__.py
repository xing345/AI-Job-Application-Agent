"""
职业诊断模块 - 岗位诊断模式
智能访谈采集实际情况 → 岗位方向诊断 → 按方向搜索 → 针对性简历生成
"""

from .interviewer import CareerInterviewer
from .analyzer import CareerDirectionAnalyzer
from .resume_builder import TargetedResumeGenerator

__all__ = [
    "CareerInterviewer",
    "CareerDirectionAnalyzer",
    "TargetedResumeGenerator",
]
