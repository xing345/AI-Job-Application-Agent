"""
LangGraph 状态机实现
管理整个求职流程的控制流
"""

import asyncio
import json
from datetime import datetime
from typing import TypedDict, Optional, List, Annotated
from loguru import logger

# LangGraph 相关
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# 添加项目根目录到 Python 路径
import sys
import os
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from src.orchestrator.state import (
    AgentState,
    AgentStatus,
    create_initial_state,
    update_state,
    add_log,
    get_progress_message,
    state_validator
)
from src.parsers.resume_parser import parse_pdf
from src.search.search_pipeline import SearchPipeline
from src.automation.auto_fill import AutoFillAgent
from src.notifications.notification_pipeline import NotificationPipeline


# 定义消息类型
class HumanMessage(TypedDict):
    """人类消息类型"""
    content: str


class AIMessage(TypedDict):
    """AI 消息类型"""
    content: str
    additional_kwargs: dict


# 状态更新器
def update_state_wrapper(
    state: AgentState,
    key: str,
    value: any
) -> AgentState:
    """包装的更新函数"""
    return update_state(state, {key: value})


# 节点定义
async def initialize_node(state: AgentState) -> AgentState:
    """初始化节点"""
    logger.info("开始初始化系统...")

    # 更新状态
    state = update_state(state, status=AgentStatus.INITIALIZING, progress=5.0)
    state = add_log(state, "系统初始化开始")

    # 验证输入
    if not state.get("pdf_path"):
        state = add_error(state, "简历 PDF 路径不能为空")
        return update_state(state, status=AgentStatus.FAILED, progress=0.0)

    if not state.get("target_instruction"):
        state = add_error(state, "目标指令不能为空")
        return update_state(state, status=AgentStatus.FAILED, progress=0.0)

    # 验证 PDF 文件是否存在
    if not os.path.exists(state["pdf_path"]):
        state = add_error(state, f"简历文件不存在: {state['pdf_path']}")
        return update_state(state, status=AgentStatus.FAILED, progress=0.0)

    state = add_log(state, "系统初始化完成")
    state = update_state(state, progress=10.0)

    return state


async def parse_resume_node(state: AgentState) -> AgentState:
    """解析简历节点"""
    logger.info("开始解析简历...")

    # 更新状态
    state = update_state(state, status=AgentStatus.PARSING_RESUME, progress=15.0)
    state = add_log(state, "开始解析简历文件")

    try:
        # 解析简历
        parsed_resume = await parse_pdf(state["pdf_path"])

        if not parsed_resume:
            state = add_error(state, "简历解析失败")
            return update_state(state, status=AgentStatus.FAILED, progress=0.0)

        # 更新状态
        state = update_state(state, parsed_resume=parsed_resume, progress=30.0)
        state = add_log(state, f"简历解析成功，提取到 {len(parsed_resume.work_experience)} 条工作经历")

        # 记录解析结果摘要
        summary = f"""
        姓名: {parsed_resume.name}
        电话: {parsed_resume.phone}
        邮箱: {parsed_resume.email}
        工作经验: {len(parsed_resume.work_experience)} 年
        项目经验: {len(parsed_resume.project_experience)} 个
        """
        state = add_log(state, f"简历信息: {summary}")

        return state

    except Exception as e:
        error_msg = f"简历解析失败: {str(e)}"
        logger.error(error_msg)
        state = add_error(state, error_msg)
        return update_state(state, status=AgentStatus.FAILED, progress=0.0)


async def search_jobs_node(state: AgentState) -> AgentState:
    """搜索职位节点"""
    logger.info("开始搜索职位...")

    # 更新状态
    state = update_state(state, status=AgentStatus.FINDING_JOBS, progress=35.0)
    state = add_log(state, "开始搜索匹配的职位")

    try:
        # 创建搜索管道
        search_pipeline = SearchPipeline()

        # 执行搜索
        search_results = await search_pipeline.run_full_pipeline(
            resume_data=state["parsed_resume"],
            instruction=state["target_instruction"]
        )

        if not search_results.get("qualified_urls"):
            state = add_error(state, "未找到符合条件的职位")
            return update_state(state, status=AgentStatus.FAILED, progress=0.0)

        # 更新状态
        state = update_state(
            state,
            qualified_urls=search_results["qualified_urls"],
            match_results=search_results.get("match_results", []),
            progress=50.0
        )

        state = add_log(
            state,
            f"搜索完成，找到 {len(search_results['qualified_urls'])} 个符合条件的职位"
        )

        # 记录前5个职位信息
        for i, url in enumerate(search_results["qualified_urls"][:5], 1):
            match = next((m for m in search_results.get("match_results", []) if m["url"] == url), None)
            if match:
                state = add_log(state, f"职位 {i}: {match['title']} - {match['company']} (匹配度: {match['match_score']}%)")

        return state

    except Exception as e:
        error_msg = f"职位搜索失败: {str(e)}"
        logger.error(error_msg)
        state = add_error(state, error_msg)
        return update_state(state, status=AgentStatus.FAILED, progress=0.0)


async def match_jobs_node(state: AgentState) -> AgentState:
    """匹配职位节点"""
    logger.info("开始匹配职位...")

    # 更新状态
    state = update_state(state, status=AgentStatus.MATCHING_JOBS, progress=55.0)
    state = add_log(state, "开始职位匹配评分")

    try:
        # 这里实际上已经在搜索节点完成了匹配
        # 可以根据需要添加更复杂的匹配逻辑

        if state.get("match_results"):
            # 过滤高匹配度的职位
            high_match_jobs = [
                m for m in state["match_results"]
                if m.get("match_score", 0) >= 70
            ]

            state = update_state(
                state,
                qualified_urls=[m["url"] for m in high_match_jobs],
                match_results=high_match_jobs,
                progress=65.0
            )

            state = add_log(
                state,
                f"高匹配度职位筛选完成，保留 {len(high_match_jobs)} 个职位"
            )
        else:
            state = add_log(state, "无需额外匹配处理")

        return state

    except Exception as e:
        error_msg = f"职位匹配失败: {str(e)}"
        logger.error(error_msg)
        state = add_error(state, error_msg)
        return update_state(state, status=AgentStatus.FAILED, progress=0.0)


async def fill_forms_node(state: AgentState) -> AgentState:
    """自动填报节点"""
    logger.info("开始自动填报...")

    # 更新状态
    state = update_state(state, status=AgentStatus.FILLING_FORMS, progress=70.0)
    state = add_log(state, "开始自动填报申请表")

    try:
        # 创建自动填报实例
        auto_fill = AutoFillAgent()

        submitted_urls = []
        total_urls = len(state["qualified_urls"])

        for i, url in enumerate(state["qualified_urls"], 1):
            try:
                state = update_state(state, current_url=url)
                state = add_log(state, f"正在处理第 {i}/{total_urls} 个职位: {url}")

                # 检查是否需要审批
                if i == 1:  # 第一个申请需要人工确认
                    state = update_state(
                        state,
                        needs_approval=True,
                        progress=75.0
                    )
                    state = add_log(
                        state,
                        "需要人工确认第一个申请，暂停等待审批..."
                    )
                    return state

                # 执行自动填报
                result = await auto_fill.fill_application_form(
                    url=url,
                    resume_data=state["parsed_resume"],
                    target_instruction=state["target_instruction"]
                )

                if result and result.get("success"):
                    submitted_urls.append(url)
                    state = add_log(
                        state,
                        f"✅ 第 {i} 个职位申请成功: {url}"
                    )
                else:
                    state = add_log(
                        state,
                        f"❌ 第 {i} 个职位申请失败: {url} - {result.get('error', '未知错误')}"
                    )

                # 更新进度
                progress = 75.0 + (i / total_urls) * 20
                state = update_state(state, progress=progress)

                # 添加延迟，避免请求过于频繁
                await asyncio.sleep(2)

            except Exception as e:
                error_msg = f"处理职位 {url} 时出错: {str(e)}"
                logger.error(error_msg)
                state = add_log(state, error_msg)

        # 更新最终状态
        state = update_state(
            state,
            submitted_urls=submitted_urls,
            progress=95.0
        )

        success_rate = len(submitted_urls) / total_urls * 100 if total_urls > 0 else 0
        state = add_log(
            state,
            f"自动填报完成！成功率: {success_rate:.1f}% ({len(submitted_urls)}/{total_urls})"
        )

        return state

    except Exception as e:
        error_msg = f"自动填报失败: {str(e)}"
        logger.error(error_msg)
        state = add_error(state, error_msg)
        return update_state(state, status=AgentStatus.FAILED, progress=0.0)


async def approval_node(state: AgentState) -> AgentState:
    """人工审批节点"""
    logger.info("等待人工审批...")

    # 更新状态
    state = update_state(state, status=AgentStatus.WAITING_APPROVAL, progress=75.0)
    state = add_log(state, "等待人工审批中...")

    # 这里应该有实际的审批机制
    # 为了演示，我们假设自动批准
    print(f"\n🔍 需要审批的事项:")
    print(f"   职位申请: {state.get('current_url', '未知')}")
    print(f"   申请人: {state['parsed_resume'].name if state.get('parsed_resume') else '未知'}")
    print(f"   目标职位: {state['target_instruction'].job_title}")

    # 模拟审批
    approval_input = input("是否批准继续申请？(y/n): ").strip().lower()

    if approval_input == 'y':
        state = update_state(
            state,
            needs_approval=False,
            approved_by="user",
            approval_notes="手动批准",
            progress=80.0
        )
        state = add_log(state, "✅ 人工审批通过，继续执行")
        return state
    else:
        state = update_state(
            state,
            needs_approval=False,
            approved_by="user",
            approval_notes="手动拒绝",
            progress=0.0
        )
        state = add_log(state, "❌ 人工审批拒绝，任务终止")
        return update_state(state, status=AgentStatus.FAILED, progress=0.0)


async def complete_node(state: AgentState) -> AgentState:
    """完成节点"""
    logger.info("任务完成！")

    # 更新最终状态
    state = update_state(state, status=AgentStatus.COMPLETED, progress=100.0)
    state = add_log(state, "🎉 任务完成！")

    # 生成摘要报告
    summary = f"""
    📊 任务执行摘要:
    - 总进度: 100%
    - 成功提交: {len(state.get('submitted_urls', []))} 个职位
    - 找到职位: {len(state.get('qualified_urls', []))} 个
    - 错误数量: {len(state.get('errors', []))}
    - 日志数量: {len(state.get('logs', []))}
    """

    if state.get('parsed_resume'):
        summary += f"\n👤 申请人: {state['parsed_resume'].name}"
        summary += f"\n📞 联系方式: {state['parsed_resume'].phone}"

    state = add_log(state, summary)

    return state


async def failed_node(state: AgentState) -> AgentState:
    """失败节点"""
    logger.error("任务失败！")

    # 更新失败状态
    state = update_state(state, status=AgentStatus.FAILED, progress=0.0)
    state = add_log(state, "❌ 任务执行失败")

    # 生成错误报告
    error_summary = f"""
    🚨 错误报告:
    - 错误数量: {len(state.get('errors', []))}
    - 最后更新: {state.get('updated_at', '未知')}
    """

    if state.get('errors'):
        error_summary += "\n📝 错误详情:"
        for error in state['errors'][-5:]:  # 只显示最后5个错误
            error_summary += f"\n  - {error}"

    state = add_log(state, error_summary)

    return state


# 条件判断函数
def should_continue(state: AgentState) -> str:
    """判断是否应该继续"""
    if state.get("needs_approval"):
        return "approval"
    elif state.get("errors"):
        return "failed"
    elif state.get("status") == AgentStatus.COMPLETED:
        return "completed"
    else:
        return "continue"


# 创建状态图
def create_application_graph() -> StateGraph:
    """创建申请流程的状态图"""
    # 创建图
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("initialize", initialize_node)
    workflow.add_node("parse_resume", parse_resume_node)
    workflow.add_node("search_jobs", search_jobs_node)
    workflow.add_node("match_jobs", match_jobs_node)
    workflow.add_node("fill_forms", fill_forms_node)
    workflow.add_node("approval", approval_node)
    workflow.add_node("complete", complete_node)
    workflow.add_node("failed", failed_node)

    # 添加边
    workflow.add_edge(START, "initialize")
    workflow.add_edge("initialize", "parse_resume")
    workflow.add_edge("parse_resume", "search_jobs")
    workflow.add_edge("search_jobs", "match_jobs")
    workflow.add_edge("match_jobs", "fill_forms")

    # 添加条件边
    workflow.add_conditional_edges(
        "fill_forms",
        should_continue,
        {
            "approval": "approval",
            "continue": "search_jobs",  # 继续下一个职位
            "failed": "failed",
            "completed": "complete"
        }
    )

    workflow.add_edge("approval", "fill_forms")
    workflow.add_edge("complete", END)
    workflow.add_edge("failed", END)

    return workflow


# 创建编译后的图
compiled_graph = create_application_graph()


# 工具函数
class ApplicationOrchestrator:
    """申请流程编排器"""

    def __init__(self):
        self.graph = compiled_graph
        self.logger = logger.bind(module="orchestrator")

    async def run_application(
        self,
        pdf_path: str,
        target_instruction,
        config: dict = None
    ) -> AgentState:
        """运行完整的申请流程"""

        # 创建初始状态
        initial_state = create_initial_state(pdf_path, target_instruction)

        # 应用配置
        if config:
            initial_state.update(config)

        # 打印初始信息
        self.logger.info(f"开始运行申请流程，简历文件: {pdf_path}")

        # 运行工作流
        try:
            # 编译图（如果需要）
            app = self.graph.compile()

            # 执行工作流
            result = await app.ainvoke(initial_state)

            # 打印最终摘要
            self._print_final_summary(result)

            return result

        except Exception as e:
            self.logger.error(f"工作流执行失败: {e}")
            return update_state(initial_state, status=AgentStatus.FAILED, errors=[str(e)])

    def _print_final_summary(self, state: AgentState):
        """打印最终摘要"""
        print(f"\n{'='*60}")
        print("🎯 申请流程执行结果")
        print(f"{'='*60}")
        print(f"✅ 状态: {state['status']}")
        print(f"📊 进度: {state['progress']:.1f}%")
        print(f"📋 找到职位: {len(state['qualified_urls'])} 个")
        print(f"✅ 成功提交: {len(state['submitted_urls'])} 个")
        print(f"❌ 错误数量: {len(state['errors'])}")

        if state.get('parsed_resume'):
            print(f"👤 申请人: {state['parsed_resume'].name}")

        if state['logs']:
            print(f"\n📝 最近日志:")
            for log in state['logs'][-3:]:
                timestamp = log.created_at.strftime('%H:%M:%S')
                print(f"   [{timestamp}] {log.message}")


# 测试函数
async def test_graph_flow():
    """测试图流程"""
    print("=== LangGraph 状态机测试 ===\n")

    from src.models.instruction_schemas import TargetInstructionSchema

    # 创建测试数据
    instruction = TargetInstructionSchema(
        job_title="前端开发工程师",
        company_names=["字节跳动", "腾讯", "阿里巴巴"],
        location="北京",
        salary_range="15-25K",
        experience="3-5年",
        keywords=["React", "Vue", "JavaScript", "TypeScript"],
        exclude_keywords=["管理", "销售", "市场"]
    )

    # 获取测试 PDF 路径
    pdf_path = os.path.join(project_root, "sample_resume.pdf")
    if not os.path.exists(pdf_path):
        # 创建一个测试用的 PDF 路径
        pdf_path = os.path.join(project_root, "tests", "data", "sample_resume.pdf")

    # 创建编排器
    orchestrator = ApplicationOrchestrator()

    # 运行流程
    if os.path.exists(pdf_path):
        result = await orchestrator.run_application(pdf_path, instruction)
        return result
    else:
        print(f"❌ 测试 PDF 文件不存在: {pdf_path}")
        print("创建模拟测试...")

        # 创建模拟状态
        mock_state = create_initial_state("mock.pdf", instruction)
        mock_state = update_state(mock_state, status=AgentStatus.INITIALIZING, progress=50.0)
        mock_state = add_log(mock_state, "这是模拟测试")

        return mock_state


if __name__ == "__main__":
    asyncio.run(test_graph_flow())