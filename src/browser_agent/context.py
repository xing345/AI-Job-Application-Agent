"""组装给通用 agent 的用户上下文：简历文本 + 结构化资料 + 知识库素材。"""
from __future__ import annotations

from typing import Optional

from src.browser_agent.kb_client import PersonalKB

# 填表前从知识库检索的主题（覆盖项目/作品/自我描述）
_KB_TOPICS = [
    "项目经历",
    "自我评价",
    "Agent 项目",
    "技术栈与技能",
    "GitHub 项目",
]


async def build_user_context(profile=None, resume=None, use_kb: bool = True) -> str:
    parts: list[str] = []

    # 1. 简历全文（信息最完整）
    if resume is not None:
        txt = resume.full_text() if hasattr(resume, "full_text") else getattr(resume, "raw_text", "")
        if txt and txt.strip():
            parts.append("【简历全文】\n" + txt.strip())

    # 2. 结构化资料（确保字段齐全）
    if profile is not None:
        ptext = profile.to_resume_text() if hasattr(profile, "to_resume_text") else ""
        if ptext and ptext.strip():
            parts.append("【结构化资料】\n" + ptext.strip())

    # 3. 知识库素材（项目/作品/自我描述，服务未启动则自动跳过）
    if use_kb:
        kb = PersonalKB()
        material = await kb.gather_material(_KB_TOPICS, top_k=3)
        if material:
            parts.append("【知识库素材（含项目/作品，填写时优先参考）】\n" + material)

    return "\n\n".join(parts) if parts else "（暂无用户资料，遇到字段请用 ask 询问）"
