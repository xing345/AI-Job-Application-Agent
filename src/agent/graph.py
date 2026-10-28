"""LangGraph StateGraph 定义。

节点流程：
load_profile → discover_jobs → screen_titles → fetch_jd → match_jobs → confirm_list
→ [循环] fill_application → record_result → (还有岗位? 继续 fill : 结束)

如果指定了 --job-url，跳过 discover_jobs/screen_titles，直接 fetch_jd。
"""
from __future__ import annotations

import logging
from typing import TypedDict

from langgraph.graph import END, StateGraph

from src.agent.state import AgentState
from src.agent.nodes import load_profile, discover_jobs, screen_titles, fetch_jd, match_jobs, confirm_list, fill_application, record_result

logger = logging.getLogger(__name__)


# LangGraph 需要 TypedDict 状态；我们用 Pydantic AgentState，
# 但 LangGraph 的 reducer 需要 dict-like 接口。这里用一个包装。
class GraphState(TypedDict, total=False):
    profile: dict
    resume: dict
    discovered_jobs: list
    screened_jobs: list
    job_details: list
    match_results: list
    apply_queue: list
    current_job_index: int
    current_fill_fields: list
    fill_results: dict
    errors: list
    site_name: str
    job_urls: list
    resume_path: str
    profile_path: str


def _state_to_dict(state: AgentState) -> dict:
    return state.model_dump(mode="json")


def _dict_to_state(data: dict) -> AgentState:
    return AgentState.model_validate(data)


def build_graph():
    """构建并编译 LangGraph。"""
    workflow = StateGraph(AgentState)

    # 注册节点
    workflow.add_node("load_profile", load_profile.run)
    workflow.add_node("discover_jobs", discover_jobs.run)
    workflow.add_node("screen_titles", screen_titles.run)
    workflow.add_node("fetch_jd", fetch_jd.run)
    workflow.add_node("match_jobs", match_jobs.run)
    workflow.add_node("confirm_list", confirm_list.run)
    workflow.add_node("fill_application", fill_application.run)
    workflow.add_node("prepare_direct", fill_application.prepare_direct_apply)
    workflow.add_node("record_result", record_result.run)

    # 入口
    workflow.set_entry_point("load_profile")

    # load_profile 后：直达填表 > 直接 job_url > 站点发现
    def after_load(state: AgentState) -> str:
        if state.apply_url:
            logger.info("Direct apply URL specified, jumping straight to form fill")
            return "prepare_direct"
        if state.job_urls:
            logger.info("Direct job URLs specified, skipping discovery")
            return "fetch_jd"
        if state.site_name:
            return "discover_jobs"
        # 既没有 URL 也没有 site，无法继续
        logger.error("No site_name or job_urls specified")
        state.add_error("graph", "请指定 --site 或 --job-url")
        return END

    workflow.add_conditional_edges("load_profile", after_load, {
        "prepare_direct": "prepare_direct",
        "discover_jobs": "discover_jobs",
        "fetch_jd": "fetch_jd",
        END: END,
    })

    # 直达填表：prepare_direct → fill_application → record_result → END
    workflow.add_edge("prepare_direct", "fill_application")

    # discover_jobs → screen_titles
    workflow.add_edge("discover_jobs", "screen_titles")

    # screen_titles → fetch_jd
    workflow.add_edge("screen_titles", "fetch_jd")

    # fetch_jd → match_jobs
    workflow.add_edge("fetch_jd", "match_jobs")

    # match_jobs → confirm_list
    workflow.add_edge("match_jobs", "confirm_list")

    # confirm_list 后：有投递队列则 fill，否则结束
    def after_confirm(state: AgentState) -> str:
        if state.apply_queue:
            return "fill_application"
        return END

    workflow.add_conditional_edges("confirm_list", after_confirm, {
        "fill_application": "fill_application",
        END: END,
    })

    # fill_application → record_result
    workflow.add_edge("fill_application", "record_result")

    # record_result 后：还有岗位则继续 fill，否则结束
    def after_submit(state: AgentState) -> str:
        if state.current_job_index < len(state.apply_queue):
            return "fill_application"
        logger.info("All applications completed")
        return END

    workflow.add_conditional_edges("record_result", after_submit, {
        "fill_application": "fill_application",
        END: END,
    })

    return workflow.compile()
