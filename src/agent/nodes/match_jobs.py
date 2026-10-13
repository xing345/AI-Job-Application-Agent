"""LLM 深度匹配节点。

读完整 JD + 简历全文，LLM 输出 MatchResult（分数、匹配点、缺失点、理由）。
按分数降序，输出匹配报告 JSON。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List

from src.agent.state import AgentState
from src.llm import client as llm
from src.llm.prompts import job_match_prompt
from src.models.match import MatchResult

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "output"

# JD 失效检测：导航/页脚关键词（出现多个且没有职责/要求关键词则判定失效）
_NAV_KEYWORDS = ["首页", "岗位投递", "校招答疑", "培养与成长", "校招动态", "切换到社招", "登录", "Previous", "Next", "搜 索", "筛选", "清除", "招聘项目", "招聘范围", "职能类型", "工作地点", "职位列表"]
_JD_VALID_KEYWORDS = ["岗位职责", "任职要求", "工作职责", "岗位要求", "任职资格", "工作内容", "职位描述", "职位要求", "responsibilities", "requirements", "qualifications"]


def _is_jd_valid(jd_text: str, job_title: str = "") -> tuple[bool, str]:
    """检查 JD 内容是否有效。

    Returns:
        (is_valid, reason)
    """
    if not jd_text or len(jd_text.strip()) < 80:
        return False, f"JD内容过短（{len(jd_text)}字符）"

    nav_count = sum(1 for kw in _NAV_KEYWORDS if kw in jd_text)
    jd_kw_count = sum(1 for kw in _JD_VALID_KEYWORDS if kw.lower() in jd_text.lower())

    # 导航词多且没有JD关键词 → 失效
    if nav_count >= 5 and jd_kw_count == 0:
        return False, f"JD内容为导航文本（导航词{nav_count}个，JD关键词0个）"

    # 完全没有JD关键词且长度较短 → 可能失效
    if jd_kw_count == 0 and len(jd_text) < 300:
        return False, f"JD缺少职责/要求关键词（长度{len(jd_text)}）"

    return True, ""


async def match_one(resume_text: str, job_title: str, jd_text: str, run_id: str = "") -> MatchResult:
    """对单个岗位做 LLM 深度匹配。"""
    # JD 有效性预检查
    is_valid, reason = _is_jd_valid(jd_text, job_title)
    if not is_valid:
        logger.warning("JD失效，跳过LLM: %s | %s", job_title, reason)
        return MatchResult(
            score=10,
            direction_match=False,
            direction_reason=f"JD内容失效：{reason}",
            hard_requirements_total=0,
            hard_requirements_met=0,
            matched_points=[],
            missing_points=[],
            reason=f"JD内容失效（{reason}），无法进行有效匹配，建议重新抓取JD。",
        )

    messages = job_match_prompt(resume_text, job_title, jd_text)
    result = await llm.chat_structured(messages, MatchResult, temperature=0.1, run_id=run_id)
    return result


async def run(state: AgentState) -> AgentState:
    """LangGraph 节点：对所有 JD 做深度匹配。"""
    if not state.job_details:
        state.add_error("match_jobs", "没有可匹配的岗位详情")
        return state

    resume_text = ""
    if state.resume:
        resume_text = state.resume.full_text()
    elif state.profile:
        resume_text = state.profile.to_resume_text()

    if not resume_text:
        state.add_error("match_jobs", "简历为空，无法匹配")
        return state

    logger.info("Matching %d jobs with resume (len=%d)...", len(state.job_details), len(resume_text))

    results: list[MatchResult] = []
    for detail in state.job_details:
        jd_text = detail.jd_for_match()
        job_title = detail.posting.title
        job_url = detail.posting.detail_url

        try:
            result = await match_one(resume_text, job_title, jd_text, state.run_id)
            result.job_url = job_url
            result.job_title = job_title
            result.company = detail.posting.company
            results.append(result)
            logger.info("Matched: %s | score=%d | direction=%s", job_title, result.score, result.direction_match)
        except Exception as e:
            state.add_error("match_jobs", f"{job_title} ({job_url}): {e}")
            logger.exception("match failed: %s", job_title)

    # 按分数降序，同时排序 job_details 保持两者索引一致（关键！否则 confirm_list 中 zip 会错位）
    paired = list(zip(state.job_details, results))
    paired.sort(key=lambda x: x[1].score, reverse=True)
    state.job_details = [p[0] for p in paired]
    state.match_results = [p[1] for p in paired]

    # 保存匹配报告
    _save_report(results)

    logger.info("Match complete: %d/%d succeeded, top score=%d", len(results), len(state.job_details),
                results[0].score if results else 0)
    return state


def _save_report(results: List[MatchResult]) -> str:
    """保存匹配报告到 output/ 目录。"""
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _OUTPUT_DIR / f"match_report_{timestamp}.json"

    report = {
        "generated_at": datetime.now().isoformat(),
        "total": len(results),
        "results": [r.model_dump() for r in results],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info("Match report saved: %s", path)
    return str(path)


def print_match_table(results: List[MatchResult]) -> None:
    """终端打印匹配表格。"""
    if not results:
        print("（无匹配结果）")
        return

    print("\n" + "=" * 100)
    print(f"{'序号':<4} {'分数':<6} {'方向':<6} {'硬性':<8} {'岗位':<35} {'公司':<18}")
    print("-" * 100)
    for i, r in enumerate(results):
        direction = "✓" if r.direction_match else "✗"
        hard = f"{r.hard_requirements_met}/{r.hard_requirements_total}" if r.hard_requirements_total else "-"
        title = r.job_title[:33] + ".." if len(r.job_title) > 35 else r.job_title
        company = r.company[:16] + ".." if len(r.company) > 18 else r.company
        print(f"{i:<4} {r.score:<6} {direction:<6} {hard:<8} {title:<35} {company:<18}")
    print("=" * 100 + "\n")
