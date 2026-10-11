"""用户确认投递清单节点（含配额排序）。

终端展示匹配表格，用户选岗。
超过站点配额时触发 LLM 排序推荐。
支持直接输入岗位 URL 跳过发现/匹配。
"""
from __future__ import annotations

import logging
from typing import List, Optional

from src.agent.state import AgentState
from src.llm import client as llm
from src.llm.prompts import quota_sort_prompt
from src.models.job import JobDetail
from src.models.match import MatchResult, QuotaSortResult
from src.search.site_registry import get_site_config

logger = logging.getLogger(__name__)


async def quota_sort(
    state: AgentState,
    candidates: List[JobDetail],
    max_count: int,
) -> List[int]:
    """超过配额时，LLM 辅助排序推荐。"""
    if not state.match_results:
        return list(range(min(max_count, len(candidates))))

    target_directions = state.profile.target_directions if state.profile else []
    resume_summary = state.resume.full_text()[:500] if state.resume else ""

    # 构造候选岗位摘要
    jobs_summary_lines = []
    for i, (detail, match) in enumerate(zip(candidates, state.match_results)):
        jobs_summary_lines.append(
            f"{i}. 岗位: {detail.posting.title} | 公司: {detail.posting.company} | "
            f"匹配度: {match.score} | 方向匹配: {match.direction_match} | "
            f"JD摘要: {detail.jd_for_match()[:100]}"
        )
    jobs_summary = "\n".join(jobs_summary_lines)

    messages = quota_sort_prompt(target_directions, resume_summary, jobs_summary, max_count)

    try:
        result: QuotaSortResult = await llm.chat_structured(messages, QuotaSortResult, temperature=0.1)
        logger.info("Quota sort: recommended %d jobs, reason: %s", len(result.recommended), result.reasoning[:100])
        return result.recommended
    except Exception as e:
        logger.warning("Quota sort failed, falling back to top by score: %s", e)
        return list(range(min(max_count, len(candidates))))


def _print_match_table(details: List[JobDetail], matches: List[MatchResult]) -> None:
    """终端打印匹配表格。"""
    print("\n" + "=" * 100)
    print(f"{'序号':<4} {'分数':<6} {'方向':<6} {'岗位':<45} {'公司':<20} {'地点':<12}")
    print("-" * 100)
    for i, (detail, match) in enumerate(zip(details, matches)):
        direction = "Y" if match.direction_match else "N"
        title = detail.posting.title[:43] + ".." if len(detail.posting.title) > 45 else detail.posting.title
        company = detail.posting.company[:18] + ".." if len(detail.posting.company) > 20 else detail.posting.company
        loc = detail.location[:10]
        print(f"{i:<4} {match.score:<6} {direction:<6} {title:<45} {company:<20} {loc:<12}")
    print("=" * 100)


async def run(state: AgentState) -> AgentState:
    """LangGraph 节点：用户确认投递清单。"""
    if not state.job_details:
        state.add_error("confirm_list", "没有可投递的岗位详情")
        return state

    # 配额检查
    max_apps = 999
    if state.site_name:
        config = get_site_config(state.site_name)
        if config:
            max_apps = config.max_applications_per_cycle

    details = state.job_details
    matches = state.match_results

    # 如果匹配结果数量和详情不一致，用详情数量
    if len(matches) != len(details):
        logger.warning("match_results count (%d) != job_details count (%d)", len(matches), len(details))

    _print_match_table(details, matches)

    # 超过配额时 LLM 排序推荐
    recommended_indices: Optional[List[int]] = None
    if len(details) > max_apps:
        print(f"\n[配额提醒] 该站点每周期最多投递 {max_apps} 个，当前候选 {len(details)} 个，正在智能排序...")
        recommended_indices = await quota_sort(state, details, max_apps)
        print(f"[智能推荐] 推荐投递以下 {len(recommended_indices)} 个岗位: {recommended_indices}")
        if recommended_indices:
            print("推荐理由: LLM 优先目标方向岗位，高匹配度补足，兼顾多样性")

    # 用户交互
    print("\n请选择要投递的岗位：")
    print("  - 输入序号（多个用逗号分隔，如: 0,2,5）")
    print("  - 输入 all 投递全部")
    if recommended_indices:
        print(f"  - 直接回车接受推荐（{recommended_indices}）")
    print("  - 输入 URL 直接指定岗位（跳过发现/匹配）")
    print("  - 输入 quit 退出")

    try:
        user_input = input("> ").strip()
    except EOFError:
        user_input = "all"

    selected: List[JobDetail] = []

    if user_input.lower() in ("quit", "q", "exit"):
        state.apply_queue = []
        print("已取消投递")
        return state

    if user_input.lower() == "all":
        selected = details[:max_apps]
    elif user_input == "" and recommended_indices:
        selected = [details[i] for i in recommended_indices if 0 <= i < len(details)]
    elif user_input.startswith("http"):
        # 直接输入 URL，跳过发现/匹配
        state.job_urls = [user_input]
        # 需要重新抓取 JD，这里先清空，让 graph 走 fetch_jd
        state.job_details = []
        state.apply_queue = []
        logger.info("User specified direct URL: %s", user_input)
        return state
    else:
        # 解析序号
        try:
            indices = [int(x.strip()) for x in user_input.split(",") if x.strip()]
            selected = [details[i] for i in indices if 0 <= i < len(details)]
        except ValueError:
            print("输入格式错误，将投递全部")
            selected = details[:max_apps]

    if not selected:
        print("未选择任何岗位")
        state.apply_queue = []
        return state

    state.apply_queue = selected
    state.current_job_index = 0
    print(f"\n[投递队列] 已选择 {len(selected)} 个岗位，开始投递...")

    return state
