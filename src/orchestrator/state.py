"""
全局状态定义
使用 LangGraph 管理整个求职流程的状态
"""

from typing import TypedDict, Optional, List
from datetime import datetime
import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from src.models.instruction_schemas import TargetInstructionSchema
from src.models.schemas import ResumeSchema, ApplicationLogSchema
from src.models.interview_schemas import InterviewDetailSchema


class AgentState(TypedDict):
    """
    Agent 状态定义
    """
    # 基础信息
    pdf_path: str  # 简历 PDF 路径
    target_instruction: TargetInstructionSchema  # 目标指令
    current_url: Optional[str]  # 当前处理的 URL

    # 流程状态
    status: str  # 当前状态（初始化、解析中、搜索中、匹配中、填报中、完成）
    progress: float  # 进度 0-100

    # 数据结果
    parsed_resume: Optional[ResumeSchema]  # 解析后的简历
    qualified_urls: List[str]  # 符合条件的 URL 列表
    match_results: List[dict]  # 匹配结果列表
    submitted_urls: List[str]  # 已提交的 URL 列表

    # 日志记录
    logs: List[ApplicationLogSchema]  # 应用日志
    errors: List[str]  # 错误信息

    # 元数据
    created_at: datetime  # 创建时间
    updated_at: datetime  # 更新时间
    interrupted: bool  # 是否中断
    needs_approval: bool  # 是否需要人工审批
    approval_timestamp: Optional[datetime]  # 审批时间
    approved_by: Optional[str]  # 审批人
    approval_notes: Optional[str]  # 审批备注


# 状态常量
class AgentStatus:
    """Agent 状态常量"""
    INITIALIZING = "initializing"
    PARSING_RESUME = "parsing_resume"
    FINDING_JOBS = "finding_jobs"
    MATCHING_JOBS = "matching_jobs"
    FILLING_FORMS = "filling_forms"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


# 预定义的状态转换图
def create_initial_state(pdf_path: str, target_instruction: TargetInstructionSchema) -> AgentState:
    """创建初始状态"""
    return {
        "pdf_path": pdf_path,
        "target_instruction": target_instruction,
        "current_url": None,
        "status": AgentStatus.INITIALIZING,
        "progress": 0.0,
        "parsed_resume": None,
        "qualified_urls": [],
        "match_results": [],
        "submitted_urls": [],
        "logs": [],
        "errors": [],
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
        "interrupted": False,
        "needs_approval": False,
        "approval_timestamp": None,
        "approved_by": None,
        "approval_notes": None
    }


def update_state(
    current_state: AgentState,
    status: str = None,
    progress: float = None,
    current_url: str = None,
    parsed_resume: ResumeSchema = None,
    qualified_urls: List[str] = None,
    match_results: List[dict] = None,
    submitted_urls: List[str] = None,
    logs: List[ApplicationLogSchema] = None,
    errors: List[str] = None,
    needs_approval: bool = None,
    approval_by: str = None,
    approval_notes: str = None
) -> AgentState:
    """更新状态"""
    updated_state = current_state.copy()

    # 更新状态
    if status is not None:
        updated_state["status"] = status
    if progress is not None:
        updated_state["progress"] = progress
    if current_url is not None:
        updated_state["current_url"] = current_url

    # 更新数据
    if parsed_resume is not None:
        updated_state["parsed_resume"] = parsed_resume
    if qualified_urls is not None:
        updated_state["qualified_urls"] = qualified_urls
    if match_results is not None:
        updated_state["match_results"] = match_results
    if submitted_urls is not None:
        updated_state["submitted_urls"] = submitted_urls

    # 更新日志和错误
    if logs is not None:
        updated_state["logs"].extend(logs)
    if errors is not None:
        updated_state["errors"].extend(errors)

    # 更新审批状态
    if needs_approval is not None:
        updated_state["needs_approval"] = needs_approval
    if approval_by is not None:
        updated_state["approved_by"] = approval_by
    if approval_notes is not None:
        updated_state["approval_notes"] = approval_notes

    # 更新时间戳
    updated_state["updated_at"] = datetime.now()

    return updated_state


def add_log(state: AgentState, message: str, level: str = "INFO") -> AgentState:
    """添加日志"""
    from src.models.schemas import ApplicationLogSchema, ApplicationStatus

    log_entry = ApplicationLogSchema(
        job_id="system",
        resume_id="system",
        application_url="https://example.com/system",
        status=ApplicationStatus.PENDING,
        message=message,
        created_at=datetime.now()
    )

    return update_state(
        state,
        logs=[log_entry]
    )


def add_error(state: AgentState, error: str) -> AgentState:
    """添加错误"""
    return update_state(
        state,
        errors=state["errors"] + [error]
    )


def get_progress_message(status: str, progress: float = None) -> str:
    """获取进度消息"""
    messages = {
        AgentStatus.INITIALIZING: "初始化系统...",
        AgentStatus.PARSING_RESUME: "解析简历中...",
        AgentStatus.FINDING_JOBS: "搜索职位中...",
        AgentStatus.MATCHING_JOBS: "匹配职位中...",
        AgentStatus.FILLING_FORMS: "填报表格中...",
        AgentStatus.WAITING_APPROVAL: "等待人工审批...",
        AgentStatus.COMPLETED: "任务完成！",
        AgentStatus.FAILED: "任务失败",
        AgentStatus.INTERRUPTED: "任务中断"
    }

    message = messages.get(status, "未知状态")

    if progress is not None:
        return f"[{progress:.0f}%] {message}"
    else:
        return message


class StateTransitions:
    """状态转换定义"""

    @staticmethod
    def can_transition(from_status: str, to_status: str) -> bool:
        """检查是否可以转换状态"""
        # 定义允许的转换
        valid_transitions = {
            AgentStatus.INITIALIZING: [AgentStatus.PARSING_RESUME, AgentStatus.FAILED],
            AgentStatus.PARSING_RESUME: [AgentStatus.FINDING_JOBS, AgentStatus.FAILED],
            AgentStatus.FINDING_JOBS: [AgentStatus.MATCHING_JOBS, AgentStatus.FAILED],
            AgentStatus.MATCHING_JOBS: [AgentStatus.FILLING_FORMS, AgentStatus.FAILED],
            AgentStatus.FILLING_FORMS: [AgentStatus.WAITING_APPROVAL, AgentStatus.COMPLETED, AgentStatus.FAILED],
            AgentStatus.WAITING_APPROVAL: [AgentStatus.FILLING_FORMS, AgentStatus.COMPLETED, AgentStatus.FAILED],
            AgentStatus.COMPLETED: [],
            AgentStatus.FAILED: [],
            AgentStatus.INTERRUPTED: []
        }

        return to_status in valid_transitions.get(from_status, [])


def validate_state(state: AgentState) -> List[str]:
    """验证状态完整性"""
    errors = []

    # 检查必填字段
    if not state.get("pdf_path"):
        errors.append("pdf_path 不能为空")

    if not state.get("target_instruction"):
        errors.append("target_instruction 不能为空")

    # 检查进度范围
    progress = state.get("progress", 0)
    if not (0 <= progress <= 100):
        errors.append("progress 必须在 0-100 之间")

    # 检查状态一致性
    if state.get("status") and not StateTransitions.can_transition(
        "INITIALIZING", state["status"]
    ):
        errors.append(f"状态 {state['status']} 不合法")

    return errors


# State 效验器
def state_validator(state: AgentState) -> str:
    """状态效验函数，返回错误信息或空字符串"""
    errors = validate_state(state)
    return "; ".join(errors) if errors else ""


# 调试工具
def print_state_summary(state: AgentState):
    """打印状态摘要"""
    print(f"\n=== 状态摘要 ===")
    print(f"当前状态: {state['status']}")
    print(f"进度: {state['progress']:.1f}%")
    print(f"解析的简历: {'已解析' if state['parsed_resume'] else '未解析'}")
    print(f"符合条件的 URL: {len(state['qualified_urls'])}")
    print(f"已提交的 URL: {len(state['submitted_urls'])}")
    print(f"错误数量: {len(state['errors'])}")
    print(f"日志数量: {len(state['logs'])}")

    if state['needs_approval']:
        print(f"需要审批: 是")
        print(f"审批人: {state.get('approved_by', '未指定')}")
        print(f"审批备注: {state.get('approval_notes', '无')}")