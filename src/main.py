"""
求职自动化助手主入口
基于 LangGraph 状态机的端到端自动化系统
"""

import asyncio
import argparse
import os
from datetime import datetime
from loguru import logger

# 添加项目根目录到 Python 路径
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.orchestrator.graph import ApplicationOrchestrator
from src.orchestrator.state import AgentStatus, print_state_summary
from src.models.instruction_schemas import TargetInstructionSchema
from src.parsers.resume_parser import parse_pdf


def setup_logging(verbose: bool = False):
    """设置日志"""
    level = "DEBUG" if verbose else "INFO"

    # 移除默认处理器
    logger.remove()

    # 添加控制台输出
    logger.add(
        sink=sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{module}</cyan>: <level>{message}</level>",
        level=level,
        colorize=True
    )

    # 添加文件输出
    logger.add(
        sink="application.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module} | {message}",
        level=level,
        rotation="10 MB",
        retention="30 days"
    )


def validate_inputs(pdf_path: str, job_title: str) -> tuple[bool, str]:
    """验证输入参数"""
    errors = []

    if not pdf_path or not os.path.exists(pdf_path):
        errors.append(f"简历文件不存在: {pdf_path}")

    if not job_title:
        errors.append("职位名称不能为空")

    return len(errors) == 0, "; ".join(errors)


def create_target_instruction(args) -> TargetInstructionSchema:
    """创建目标指令"""
    return TargetInstructionSchema(
        job_title=args.job_title,
        company_names=args.companies.split(",") if args.companies else [],
        location=args.location,
        salary_range=args.salary,
        experience=args.experience,
        keywords=args.keywords.split(",") if args.keywords else [],
        exclude_keywords=args.exclude.split(",") if args.exclude else [],
        application_count=args.max_applications,
        priority_sites=args.sites.split(",") if args.sites else []
    )


def print_banner():
    """打印启动横幅"""
    banner = """
    ╔════════════════════════════════════════════════════╗
    ║                                                    ║
    ║              🤖 求职自动化助手                     ║
    ║        AI-Powered Job Application Assistant         ║
    ║                                                    ║
    ║      Powered by LangGraph + Playwright + AI         ║
    ║                                                    ║
    ╚════════════════════════════════════════════════════╝
    """
    print(banner)


def print_usage_examples():
    """打印使用示例"""
    examples = """
    📖 使用示例:

    # 基本用法
    python main.py -r resume.pdf -j "前端开发工程师"

    # 完整参数
    python main.py \\
        --resume resume.pdf \\
        --job "前端开发工程师" \\
        --companies "字节跳动,腾讯,阿里巴巴" \\
        --location "北京" \\
        --salary "15-25K" \\
        --experience "3-5年" \\
        --keywords "React,Vue,TypeScript" \\
        --exclude "管理,销售" \\
        --max-applications 10 \\
        --sites "boss,zhipin" \\
        --verbose

    # 简历信息查看
    python main.py --info resume.pdf

    # 使用配置文件
    python main.py --config config.json
    """
    print(examples)


async def run_interactive_mode():
    """运行交互模式"""
    print("\n🎯 交互模式 - 请输入您的求职需求")

    # 获取简历文件
    while True:
        pdf_path = input("\n📄 请输入简历 PDF 文件路径: ").strip()
        if os.path.exists(pdf_path):
            break
        print("❌ 文件不存在，请重新输入")

    # 获取求职信息
    print("\n📋 求职信息配置:")
    job_title = input("🎯 目标职位: ").strip()

    print("\n🏢 公司偏好 (用逗号分隔，留空则不限):")
    companies = input("   例如: 字节跳动,腾讯,阿里巴巴: ").strip()

    print("\n📍 工作地点 (留空则不限):")
    location = input("   例如: 北京,上海,深圳: ").strip()

    print("\n💰 期望薪资 (留空则不限):")
    salary = input("   例如: 15-25K: ").strip()

    print("\n📅 工作经验 (留空则不限):")
    experience = input("   例如: 3-5年: ").strip()

    print("\n🔑 技能关键词 (用逗号分隔):")
    keywords = input("   例如: React,Vue,TypeScript: ").strip()

    print("\n🚫 排除关键词 (用逗号分隔):")
    exclude = input("   例如: 管理,销售: ").strip()

    print("\n⚙️ 其他设置:")
    max_apps = input("   最多申请数 (留空默认10): ").strip() or "10"
    sites = input("   优先招聘网站 (用逗号分隔): ").strip()

    # 创建指令
    instruction = TargetInstructionSchema(
        job_title=job_title,
        company_names=companies.split(",") if companies else [],
        location=location,
        salary_range=salary,
        experience=experience,
        keywords=keywords.split(",") if keywords else [],
        exclude_keywords=exclude.split(",") if exclude else [],
        application_count=int(max_apps),
        priority_sites=sites.split(",") if sites else []
    )

    return pdf_path, instruction


async def resume_info_mode(pdf_path: str):
    """简历信息查看模式"""
    print(f"\n📄 正在解析简历: {pdf_path}")

    try:
        # 解析简历
        resume = await parse_pdf(pdf_path)

        if not resume:
            print("❌ 简历解析失败")
            return

        # 打印简历信息
        print(f"\n{'='*60}")
        print("👤 简历信息")
        print(f"{'='*60}")
        print(f"姓名: {resume.name}")
        print(f"电话: {resume.phone}")
        print(f"邮箱: {resume.email}")
        print(f"求职意向: {resume.career_objective}")

        if resume.work_experience:
            print(f"\n💼 工作经历 ({len(resume.work_experience)} 条):")
            for i, work in enumerate(resume.work_experience[:3], 1):
                print(f"\n  {i}. {work.company_name} - {work.position}")
                print(f"     时间: {work.start_date} 至 {work.end_date}")
                print(f"     描述: {work.description[:100]}...")

        if resume.project_experience:
            print(f"\n🚀 项目经验 ({len(resume.project_experience)} 个):")
            for i, project in enumerate(resume.project_experience[:3], 1):
                print(f"\n  {i}. {project.project_name}")
                print(f"     描述: {project.description[:100]}...")
                print(f"     技术栈: {', '.join(project.technologies[:5])}")

        if resume.skills:
            print(f"\n💡 技能列表:")
            skills = resume.skills[:20]  # 显示前20个技能
            print(f"   {', '.join(skills)}")

        print(f"\n{'='*60}")

    except Exception as e:
        print(f"❌ 解析简历时出错: {e}")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="求职自动化助手 - 基于AI的职位申请自动化工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n使用 --help 查看更多帮助信息"
    )

    # 基本参数
    parser.add_argument(
        "-r", "--resume",
        type=str,
        help="简历 PDF 文件路径"
    )

    parser.add_argument(
        "-j", "--job",
        type=str,
        help="目标职位名称"
    )

    # 可选参数
    parser.add_argument(
        "--companies",
        type=str,
        help="目标公司列表 (用逗号分隔)"
    )

    parser.add_argument(
        "--location",
        type=str,
        help="工作地点"
    )

    parser.add_argument(
        "--salary",
        type=str,
        help="期望薪资范围"
    )

    parser.add_argument(
        "--experience",
        type=str,
        help="工作经验要求"
    )

    parser.add_argument(
        "--keywords",
        type=str,
        help="技能关键词 (用逗号分隔)"
    )

    parser.add_argument(
        "--exclude",
        type=str,
        help="排除关键词 (用逗号分隔)"
    )

    parser.add_argument(
        "--max-applications",
        type=int,
        default=10,
        help="最大申请数量 (默认: 10)"
    )

    parser.add_argument(
        "--sites",
        type=str,
        help="优先招聘网站 (用逗号分隔)"
    )

    # 模式选择
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="启用交互模式"
    )

    parser.add_argument(
        "--info",
        type=str,
        help="查看简历信息模式"
    )

    parser.add_argument(
        "--config",
        type=str,
        help="使用配置文件"
    )

    # 输出选项
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="详细输出"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预运行模式（只显示将要执行的操作，不实际执行）"
    )

    args = parser.parse_args()

    # 设置日志
    setup_logging(args.verbose)

    # 打印横幅
    print_banner()

    # 处理不同模式
    if args.info:
        # 简历信息模式
        await resume_info_mode(args.info)
        return

    if args.interactive or not (args.resume and args.job):
        # 交互模式
        pdf_path, instruction = await run_interactive_mode()
    else:
        # 命令行模式
        # 验证输入
        valid, error_msg = validate_inputs(args.resume, args.job)
        if not valid:
            print(f"❌ 输入错误: {error_msg}")
            return

        # 创建指令
        instruction = create_target_instruction(args)
        pdf_path = args.resume

    print(f"\n🚀 开始执行求职流程...")
    print(f"📄 简历文件: {pdf_path}")
    print(f"🎯 目标职位: {instruction.job_title}")

    if instruction.company_names:
        print(f"🏢 目标公司: {', '.join(instruction.company_names)}")

    # 创建编排器
    orchestrator = ApplicationOrchestrator()

    # 如果是预运行模式
    if args.dry_run:
        print("\n🔍 预运行模式 - 显示将要执行的操作:")
        print("\n1. 解析简历 PDF")
        print("2. 搜索匹配的职位")
        print("3. 筛选高匹配度职位")
        print("4. 自动填写申请表单")
        print("5. 发送通知（可选）")
        print("\n💡 提示: 实际运行时会显示更详细的进度信息")
        return

    # 执行流程
    try:
        start_time = datetime.now()

        # 运行自动化流程
        result = await orchestrator.run_application(
            pdf_path=pdf_path,
            target_instruction=instruction
        )

        end_time = datetime.now()
        duration = end_time - start_time

        # 打印执行结果
        print(f"\n{'='*60}")
        print("📊 执行报告")
        print(f"{'='*60}")
        print(f"⏱️  执行时间: {duration}")
        print(f"✅ 最终状态: {result['status']}")
        print(f"📈 总进度: {result['progress']:.1f}%")

        if result['status'] == AgentStatus.COMPLETED:
            print(f"🎉 成功完成！")
            print(f"📋 提交申请: {len(result['submitted_urls'])} 个")
            print(f"🔍 找到职位: {len(result['qualified_urls'])} 个")
        else:
            print(f"❌ 执行失败")
            if result['errors']:
                print(f"🚨 错误信息:")
                for error in result['errors'][-3:]:
                    print(f"   - {error}")

        # 保存日志
        log_file = f"job_application_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        print(f"\n📝 详细日志已保存到: {log_file}")

    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断执行")
    except Exception as e:
        logger.error(f"执行过程中发生错误: {e}")
        print(f"\n❌ 执行失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())