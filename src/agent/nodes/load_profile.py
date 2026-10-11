"""加载用户画像与简历节点。

从 JSON 文件加载 UserProfile，从 PDF/JSON/TXT 加载 Resume。
只解析不修改。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from src.agent.state import AgentState
from src.models.profile import Resume, UserProfile

logger = logging.getLogger(__name__)

_DEFAULT_PROFILE = str(Path(__file__).resolve().parent.parent.parent.parent / "data" / "user_profile.json")
_DEFAULT_RESUME_PDF = str(Path(__file__).resolve().parent.parent.parent.parent / "data" / "resume.pdf")


def load_profile_from_json(path: str) -> UserProfile:
    """从 JSON 文件加载 UserProfile。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return UserProfile.model_validate(data)


def load_resume(path: str, profile: Optional[UserProfile] = None) -> Resume:
    """加载简历。

    - .json: 直接解析为 UserProfile
    - .txt: 作为纯文本简历
    - .pdf: 提取文本（需要 pdfplumber）
    """
    ext = Path(path).suffix.lower()
    resume = Resume(source_file=path)

    if ext == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        p = UserProfile.model_validate(data)
        resume.profile = p
        resume.raw_text = p.to_resume_text()

    elif ext == ".txt":
        with open(path, "r", encoding="utf-8") as f:
            resume.raw_text = f.read()

    elif ext == ".pdf":
        try:
            import pdfplumber

            texts = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        texts.append(t)
            resume.raw_text = "\n".join(texts)
        except ImportError:
            logger.warning("pdfplumber 未安装，无法解析 PDF，将使用空简历")
        except Exception as e:
            logger.warning("PDF 解析失败: %s", e)

    else:
        logger.warning("不支持的简历格式: %s，将使用空简历", ext)

    if profile and not resume.profile:
        resume.profile = profile

    return resume


async def run(state: AgentState) -> AgentState:
    """LangGraph 节点：加载画像与简历。"""
    profile_path = state.profile_path or os.getenv("USER_PROFILE_PATH", _DEFAULT_PROFILE)
    resume_path = state.resume_path or os.getenv("RESUME_PATH", _DEFAULT_RESUME_PDF)

    try:
        if os.path.exists(profile_path):
            state.profile = load_profile_from_json(profile_path)
            logger.info("Profile loaded: %s", profile_path)
        else:
            logger.warning("Profile file not found: %s，使用空画像", profile_path)
            state.profile = UserProfile()

        if os.path.exists(resume_path):
            state.resume = load_resume(resume_path, state.profile)
            logger.info("Resume loaded: %s", resume_path)
        else:
            logger.warning("Resume file not found: %s，使用画像生成简历文本", resume_path)
            state.resume = Resume(profile=state.profile)

    except Exception as e:
        state.add_error("load_profile", str(e))
        logger.exception("load_profile failed")

    return state
