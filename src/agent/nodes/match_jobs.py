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


async def match_one(resume_text: str, job_title: str, jd_text: str) -> MatchResult:
    """对单个岗位做 LLM 深度匹配。"""
    messages = job_match_prompt(resume_text, job_title, jd_text)
    result = await llm.chat_structured(messages, MatchResult, temperature=0.1)
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
            result = await match_one(resume_text, job_title, jd_text)
            result.job_url = job_url
            result.job_title = job_title
            result.company = detail.posting.company
            results.append(result)
            logger.info("Matched: %s | score=%d | direction=%s", job_title, result.score, result.direction_match)
        except Exception as e:
            state.add_error("match_jobs", f"{job_title} ({job_url}): {e}")
            logger.exception("match failed: %s", job_title)

    # 按分数降序
    results.sort(key=lambda r: r.score, reverse=True)
    state.match_results = results

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

    print("\n" + "=" * 90)
    print(f"{'序号':<4} {'分数':<6} {'方向':<6} {'岗位':<40} {'公司':<20}")
    print("-" * 90)
    for i, r in enumerate(results):
        direction = "✓" if r.direction_match else "✗"
        title = r.job_title[:38] + ".." if len(r.job_title) > 40 else r.job_title
        company = r.company[:18] + ".." if len(r.company) > 20 else r.company
        print(f"{i:<4} {r.score:<6} {direction:<6} {title:<40} {company:<20}")
    print("=" * 90 + "\n")
