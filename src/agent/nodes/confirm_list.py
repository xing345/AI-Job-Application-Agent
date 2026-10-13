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
from src.storage import state_db

logger = logging.getLogger(__name__)


def _sort_key(match: MatchResult) -> tuple:
    """排序键：匹配分降序 → 硬性要求满足度 → 方向匹配。

    返回 tuple，用于 sorted(reverse=True)：
    - 第1位：匹配分（高优先）
    - 第2位：硬性要求满足比例（高优先）
    - 第3位：方向匹配（True 优先）
    """
    score = match.score
    hard_ratio = (match.hard_requirements_met / match.hard_requirements_total
                  if match.hard_requirements_total > 0 else 0)
    direction = 1 if match.direction_match else 0
    return (score, hard_ratio, direction)


def _fallback_sort(candidates: List[JobDetail], matches: List[MatchResult], max_count: int) -> List[int]:
    """LLM 排序失败时的回退排序：按匹配分降序，同分时按硬性要求满足度。"""
    # 构造 (index, match) 列表
    indexed = []
    for i, match in enumerate(matches):
        if i < len(candidates):
            indexed.append((i, match))

    # 按排序键降序
    indexed.sort(key=lambda x: _sort_key(x[1]), reverse=True)

    # 取前 max_count 个
    return [idx for idx, _ in indexed[:max_count]]


async def quota_sort(
    state: AgentState,
    candidates: List[JobDetail],
    max_count: int,
) -> List[int]:
    """超过配额时，LLM 辅助排序推荐。

    排序优先级：
    1. 目标方向匹配的岗位优先
    2. 匹配分降序
    3. 硬性要求满足度高的优先
    4. 兼顾岗位多样性（不同团队/类别）
    """
    if not state.match_results:
        return list(range(min(max_count, len(candidates))))

    target_directions = state.profile.target_directions if state.profile else []
    resume_summary = state.resume.full_text()[:500] if state.resume else ""

    # 构造候选岗位摘要（包含硬性要求满足情况）
    jobs_summary_lines = []
    for i, (detail, match) in enumerate(zip(candidates, state.match_results)):
        hard_info = f"硬性要求{match.hard_requirements_met}/{match.hard_requirements_total}" if match.hard_requirements_total else ""
        jobs_summary_lines.append(
            f"{i}. 岗位: {detail.posting.title} | 公司: {detail.posting.company} | "
            f"地点: {detail.posting.location} | 匹配度: {match.score} | "
            f"方向匹配: {match.direction_match} | {hard_info} | "
            f"JD摘要: {detail.jd_for_match()[:80]}"
        )
    jobs_summary = "\n".join(jobs_summary_lines)

    messages = quota_sort_prompt(target_directions, resume_summary, jobs_summary, max_count)

    try:
        result: QuotaSortResult = await llm.chat_structured(messages, QuotaSortResult, temperature=0.1, run_id=state.run_id)
        # 验证推荐索引有效性
        valid = [idx for idx in result.recommended if 0 <= idx < len(candidates)]
        if valid:
            logger.info("Quota sort (LLM): recommended %d jobs, reason: %s",
                        len(valid), result.reasoning[:100])
            return valid
        logger.warning("LLM returned invalid indices, falling back to score sort")
    except Exception as e:
        logger.warning("Quota sort LLM failed, falling back to score sort: %s", e)

    # 回退：按匹配分降序
    return _fallback_sort(candidates, state.match_results, max_count)


def _print_match_table(details: List[JobDetail], matches: List[MatchResult]) -> None:
    """终端打印匹配表格。"""
    print("\n" + "=" * 110)
    print(f"{'序号':<4} {'分数':<6} {'方向':<5} {'硬性':<7} {'岗位':<38} {'公司':<16} {'地点':<10}")
    print("-" * 110)
    for i, (detail, match) in enumerate(zip(details, matches)):
        direction = "Y" if match.direction_match else "N"
        hard = f"{match.hard_requirements_met}/{match.hard_requirements_total}" if match.hard_requirements_total else "-"
        title = detail.posting.title[:36] + ".." if len(detail.posting.title) > 38 else detail.posting.title
        company = detail.posting.company[:14] + ".." if len(detail.posting.company) > 16 else detail.posting.company
        loc = detail.posting.location[:8] or detail.location[:8]
        print(f"{i:<4} {match.score:<6} {direction:<5} {hard:<7} {title:<38} {company:<16} {loc:<10}")
    print("=" * 110)

    # 打印 Top3 的匹配理由
    print("\n【匹配理由 Top3】")
    for i, (detail, match) in enumerate(zip(details[:3], matches[:3])):
        print(f"\n  [{i}] {detail.posting.title} (分数: {match.score})")
        if match.reason:
            print(f"      理由: {match.reason[:150]}")
        if match.missing_points:
            print(f"      缺失: {'; '.join(match.missing_points[:3])}")


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

    # 过滤已投递的岗位（本周期内）
    if state.site_name:
        filtered_details = []
        filtered_matches = []
        skipped_count = 0
        for i, detail in enumerate(details):
            already = await state_db.has_applied(detail.posting.detail_url, state.site_name)
            if already:
                skipped_count += 1
                logger.info("Skipping already applied job: %s", detail.posting.title)
            else:
                filtered_details.append(detail)
                if i < len(matches):
                    filtered_matches.append(matches[i])
        if skipped_count > 0:
            print(f"\n[去重提醒] 已过滤 {skipped_count} 个本周期内已投递的岗位")
            details = filtered_details
            matches = filtered_matches
            state.job_details = filtered_details
            state.match_results = filtered_matches

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
