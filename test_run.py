"""
简单的功能测试脚本
"""

import asyncio
import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from src.orchestrator.graph import create_application_graph
from src.orchestrator.state import AgentStatus, print_state_summary
from src.models.instruction_schemas import TargetInstructionSchema

async def test_state_machine():
    """测试状态机功能"""
    print("=== 测试 LangGraph 状态机 ===\n")

    # 创建目标指令
    instruction = TargetInstructionSchema(
        company="字节跳动",
        role="前端开发工程师",
        location="北京",
        keywords=["React", "Vue", "TypeScript"],
        exclude_keywords=["管理", "销售"]
    )

    # 创建初始状态
    from src.orchestrator.state import create_initial_state
    initial_state = create_initial_state("test_resume.pdf", instruction)

    print("✅ 初始状态创建成功")
    print(f"   状态: {initial_state['status']}")
    print(f"   进度: {initial_state['progress']}%")
    print(f"   PDF路径: {initial_state['pdf_path']}")
    print(f"   目标职位: {initial_state['target_instruction'].role}")

    # 测试状态更新
    from src.orchestrator.state import update_state
    updated_state = update_state(
        initial_state,
        status=AgentStatus.PARSING_RESUME,
        progress=20.0
    )

    print("\n✅ 状态更新成功")
    print(f"   新状态: {updated_state['status']}")
    print(f"   新进度: {updated_state['progress']}%")

    # 测试添加日志
    from src.orchestrator.state import add_log
    state_with_log = add_log(updated_state, "开始解析简历")

    print("\n✅ 添加日志成功")
    print(f"   日志数量: {len(state_with_log['logs'])}")
    if state_with_log['logs']:
        log = state_with_log['logs'][-1]
        print(f"   最新日志 - ID: {log.job_id}, 状态: {log.status}")

    # 创建图
    print("\n✅ 创建 LangGraph 成功")
    graph = create_application_graph()
    print(f"   图节点: {len(graph.nodes)}")
    print(f"   图边数: {len(graph.edges)}")

    print("\n🎉 状态机测试完成！")

async def test_mock_data():
    """测试模拟数据生成"""
    print("\n=== 测试模拟数据生成 ===\n")

    from src.parsers.resume_parser import parse_pdf

    # 解析模拟简历（mock 模式，路径仅作存在性检查）
    resume = await parse_pdf("resumes/test_resume.pdf")

    if resume:
        print("✅ 简历解析成功")
        print(f"   姓名: {resume.name}")
        print(f"   电话: {resume.phone}")
        print(f"   邮箱: {resume.email}")
        print(f"   技能数量: {len(resume.skills)}")
        print(f"   工作经历: {len(resume.work_experience)}")
        print(f"   项目经验: {len(resume.projects)}")
    else:
        print("❌ 简历解析失败")

async def main():
    """主测试函数"""
    print("🚀 开始功能测试\n")

    await test_state_machine()
    await test_mock_data()

    print("\n" + "="*60)
    print("✅ 所有功能测试完成！")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())