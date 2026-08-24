#!/usr/bin/env python3
"""
AI Job Agent v2.0 启动脚本
自动化求职Agent的中央控制台
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path
from loguru import logger
from datetime import datetime
import signal
import traceback

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.orchestrator.agent_orchestrator import AgentOrchestrator


class AgentConsole:
    """Agent控制台"""

    def __init__(self):
        self.agent = None
        self.running = False

    async def initialize(self):
        """初始化控制台"""
        logger.info("🤖 AI Job Agent v2.0 控制台初始化中...")

        try:
            # 创建Agent控制器并初始化各模块
            self.agent = await self._create_agent()
            await self.agent.initialize()

            logger.info("✅ Agent控制台初始化完成")

        except Exception as e:
            logger.error(f"❌ 初始化失败: {e}")
            raise

    async def _create_agent(self):
        """创建Agent实例"""
        # 检查配置文件
        config_file = project_root / "config.json"
        config = {}

        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                logger.info(f"已加载配置文件: {config_file}")
            except Exception as e:
                logger.warning(f"配置文件加载失败: {e}")

        # 创建Agent（构造函数非异步）
        agent = AgentOrchestrator(config)
        return agent

    async def handle_command(self, cmd: str, args: list):
        """处理命令"""
        cmd = cmd.lower()

        if cmd == "help":
            await self._show_help()

        elif cmd == "status":
            await self._show_status()

        elif cmd == "start":
            await self._start_agent()

        elif cmd == "stop":
            await self._stop_agent()

        elif cmd == "search":
            await self._start_search()

        elif cmd == "apply":
            await self._start_apply(args)

        elif cmd == "persona":
            await self._create_persona()

        elif cmd == "dashboard":
            await self._start_dashboard()

        elif cmd == "learn":
            await self._show_learning()

        elif cmd == "emergency":
            await self._emergency_stop()

        elif cmd == "exit":
            await self._exit()

        else:
            print(f"❌ 未知命令: {cmd}")
            print("输入 'help' 查看可用命令")

    async def _show_help(self):
        """显示帮助信息"""
        print("\n" + "=" * 50)
        print("🤖 AI Job Agent v2.0 命令帮助")
        print("=" * 50)
        print()
        print("可用的命令:")
        print("  help              - 显示此帮助信息")
        print("  status            - 显示Agent状态")
        print("  start             - 启动Agent（包含持续监控）")
        print("  stop              - 停止Agent")
        print("  search            - 开始职位搜索")
        print("  apply <urls>      - 申请指定职位的URL")
        print("  persona           - 创建/更新用户画像")
        print("  dashboard         - 启动监控Dashboard")
        print("  learn             - 显示学习洞察")
        print("  emergency         - 紧急停止")
        print("  exit              - 退出程序")
        print()
        print("使用示例:")
        print("  apply https://job1.com/apply https://job2.com/apply")
        print("  search")
        print("  dashboard")
        print()

    async def _show_status(self):
        """显示Agent状态"""
        if not self.agent:
            print("❌ Agent尚未初始化")
            return

        try:
            status = await self.agent.get_agent_status()
            print("\n" + "=" * 50)
            print("📊 Agent状态报告")
            print("=" * 50)
            print(f"运行状态: {'🟢 运行中' if status['is_running'] else '🔴 已停止'}")
            print(f"用户画像: {'✅ 已加载' if status['user_persona_loaded'] else '❌ 未加载'}")
            print()

            # 显示指标
            print("📈 核心指标:")
            metrics = status['agent_metrics']
            print(f"  总搜索次数: {metrics['total_searches']}")
            print(f"  总申请数量: {metrics['total_applications']}")
            print(f"  成功提交: {metrics['successful_submissions']}")
            print(f"  拒信处理: {metrics['rejections_processed']}")
            print(f"  学习周期: {metrics['learning_cycles']}")
            print()

            # 显示当前任务
            if status['current_tasks']:
                print("🔄 当前任务:")
                for task_id, task in status['current_tasks'].items():
                    status_icon = {
                        'running': '🔄 运行中',
                        'completed': '✅ 已完成',
                        'failed': '❌ 失败',
                        'stopped': '⏹️ 已停止'
                    }.get(task['status'], '❓ 未知')

                    print(f"  {task_id}: {status_icon}")
            else:
                print("🔄 当前无任务")
            print()

            # 显示邮箱状态
            if status['email_status']:
                email_status = status['email_status']
                print("📧 邮箱监听状态:")
                print(f"  总邮件数: {email_status.get('total_emails', 0)}")
                print(f"  已处理: {email_status.get('processed_emails', 0)}")
                print(f"  拒信处理: {email_status.get('rejections_processed', 0)}")
                print()

            # 显示学习统计
            print("🧠 学习统计:")
            print(f"  反思记录: {status['reflections_count']}")
            print(f"  激活规则: {status['active_strategy_rules']}")
            print(f"  最后更新: {status['last_update']}")
            print()

        except Exception as e:
            print(f"❌ 获取状态失败: {e}")

    async def _start_agent(self):
        """启动Agent"""
        if self.agent and self.agent.is_running:
            print("⚠️ Agent已在运行中")
            return

        try:
            print("🚀 启动Agent...")
            await self.agent.start()
            print("✅ Agent启动成功")
            print("💡 Agent正在运行，按 Ctrl+C 停止")

            # 等待用户中断
            try:
                while self.agent.is_running:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                print("\n🛑 收到停止信号...")

        except Exception as e:
            print(f"❌ 启动失败: {e}")

    async def _stop_agent(self):
        """停止Agent"""
        if not self.agent or not self.agent.is_running:
            print("⚠️ Agent未运行")
            return

        try:
            print("🛑 停止Agent...")
            await self.agent.stop()
            print("✅ Agent已停止")
        except Exception as e:
            print(f"❌ 停止失败: {e}")

    async def _start_search(self):
        """开始职位搜索"""
        if not self.agent:
            print("❌ Agent未初始化")
            return

        try:
            print("🔍 开始职位搜索...")
            result = await self.agent.start_job_search_workflow()

            print(f"\n📊 搜索结果:")
            print(f"  发现职位总数: {result['total_jobs_found']}")
            print(f"  高匹配职位: {result['high_match_jobs']}")
            print(f"  任务ID: {result['task_id']}")

            # 显示高匹配职位（前5个）
            matching_results = result['matching_results']
            if matching_results:
                print("\n🎯 高匹配职位:")
                for i, match in enumerate(matching_results[:5], 1):
                    print(f"  {i}. {match.job_id}")
                    print(f"     匹配分数: {match.match_score}")
                    if match.strengths_match:
                        print(f"     优势: {'、'.join(match.strengths_match[:3])}")
                    print(f"     建议: {match.recommendation}")
                    print()

        except Exception as e:
            print(f"❌ 搜索失败: {e}")

    async def _start_apply(self, urls):
        """申请职位"""
        if not urls:
            print("❌ 请提供要申请的职位URL")
            print("使用示例: apply https://job1.com/apply https://job2.com/apply")
            return

        if not self.agent:
            print("❌ Agent未初始化")
            return

        try:
            print(f"📝 开始申请 {len(urls)} 个职位...")
            task_id = await self.agent.apply_to_jobs(urls)

            # 显示申请结果
            if task_id in self.agent.current_tasks:
                task_data = self.agent.current_tasks[task_id]['data']
                print(f"\n📊 申请结果:")
                print(f"  成功申请: {len(task_data['applied_jobs'])}")
                print(f"  申请失败: {len(task_data['failed_jobs'])}")

                if task_data['failed_jobs']:
                    print("\n❌ 失败的申请:")
                    for failed in task_data['failed_jobs'][:3]:
                        print(f"  {failed['url']}: {failed['error']}")

        except Exception as e:
            print(f"❌ 申请失败: {e}")

    async def _create_persona(self):
        """创建用户画像"""
        if not self.agent:
            print("❌ Agent未初始化")
            return

        try:
            # 检查简历文件
            resume_paths = [
                project_root / "data" / "resume.pdf",
                project_root / "data" / "resume.docx",
                project_root / "data" / "resume.txt"
            ]

            resume_path = None
            for path in resume_paths:
                if path.exists():
                    resume_path = path
                    break

            if not resume_path:
                print("❌ 未找到简历文件")
                print("请将简历文件放在 data/ 目录下，支持 .pdf, .docx, .txt 格式")
                return

            print("👤 创建用户画像...")
            user_prompt = input("请输入您的职业目标和偏好（如: 我想找React开发工作，薪资15-20K...）: ")
            if not user_prompt.strip():
                print("⚠️ 使用默认描述...")
                user_prompt = "我想找前端开发相关工作"

            await self.agent.generate_user_persona(
                resume_path=str(resume_path),
                user_prompt=user_prompt
            )

            print("✅ 用户画像创建成功")

        except Exception as e:
            print(f"❌ 创建用户画像失败: {e}")

    async def _start_dashboard(self):
        """启动Dashboard"""
        print("📊 启动监控Dashboard...")
        print("将在浏览器中打开Dashboard界面...")
        print("输入 'stop' 关闭Dashboard")

        # 导入并启动Dashboard
        try:
            from src.dashboard.app import main as dashboard_main

            # 在单独的线程中运行Dashboard
            import threading
            dashboard_thread = threading.Thread(target=dashboard_main)
            dashboard_thread.daemon = True
            dashboard_thread.start()

            print("✅ Dashboard已启动，请打开浏览器访问: http://localhost:8501")

        except Exception as e:
            print(f"❌ 启动Dashboard失败: {e}")

    async def _show_learning(self):
        """显示学习洞察"""
        if not self.agent:
            print("❌ Agent未初始化")
            return

        try:
            insights = await self.agent.get_learning_insights()

            print("\n" + "=" * 50)
            print("🧠 Agent学习洞察")
            print("=" * 50)

            # 显示失败原因分析
            if insights['failure_analysis']:
                print("\n📋 失败原因分析:")
                for analysis in insights['failure_analysis'][:5]:
                    print(f"  {analysis['reason']}: {analysis['count']} 次")

            # 显示最近建议
            if insights['recent_advice']:
                print("\n💡 最近反思建议:")
                for i, advice in enumerate(insights['recent_advice'][:3], 1):
                    print(f"  {i}. {advice['advice'][0]}")  # 显示第一个建议

            # 显示规则统计
            if insights['rule_analysis']:
                print("\n🎯 策略规则统计:")
                for rule in insights['rule_analysis']:
                    print(f"  {rule['type']}: {rule['count']} 条 (置信度: {rule['avg_confidence']:.2f})")

            print(f"\n📊 总反思记录: {insights['total_reflections']}")

        except Exception as e:
            print(f"❌ 获取学习洞察失败: {e}")

    async def _emergency_stop(self):
        """紧急停止"""
        print("🚨 紧急停止模式！")
        print("这将停止所有Agent活动...")

        if self.agent and self.agent.is_running:
            try:
                await self.agent.emergency_stop()
                print("✅ Agent已紧急停止")
            except Exception as e:
                print(f"❌ 紧急停止失败: {e}")
        else:
            print("⚠️ Agent未运行")

    async def _exit(self):
        """退出程序"""
        print("\n👋 再见！")

        if self.agent and self.agent.is_running:
            print("正在优雅停止Agent...")
            try:
                await self.agent.stop()
            except Exception as e:
                print(f"停止时出错: {e}")

        self.running = False


async def main():
    """主函数"""
    # 设置日志
    logger.add(
        "logs/agent.log",
        rotation="1 day",
        retention="7 days",
        level="INFO"
    )

    # 创建控制台
    console = AgentConsole()

    try:
        # 初始化
        await console.initialize()

        # 检查命令行参数
        parser = argparse.ArgumentParser(description='AI Job Agent v2.0')
        parser.add_argument('--command', help='直接执行的命令')
        parser.add_argument('--args', nargs='*', help='命令参数')
        args = parser.parse_args()

        if args.command:
            # 直接执行命令
            await console.handle_command(args.command, args.args or [])
        else:
            # 交互式控制台
            print("🤖 AI Job Agent v2.0 - 智能求职助手")
            print("=" * 50)
            print("输入 'help' 查看可用命令")
            print("=" * 50)

            console.running = True

            # 设置信号处理
            def signal_handler(signum, frame):
                print("\n\n收到中断信号...")
                asyncio.create_task(console._emergency_stop())

            signal.signal(signal.SIGINT, signal_handler)

            while console.running:
                try:
                    # 获取用户输入
                    user_input = input("\nagent> ").strip()

                    if not user_input:
                        continue

                    # 解析命令
                    parts = user_input.split()
                    cmd = parts[0]
                    cmd_args = parts[1:] if len(parts) > 1 else []

                    # 执行命令
                    await console.handle_command(cmd, cmd_args)

                except KeyboardInterrupt:
                    print("\n\n收到中断信号...")
                    await console._emergency_stop()
                    break
                except Exception as e:
                    print(f"\n❌ 执行命令时出错: {e}")
                    print("输入 'help' 查看可用命令")

    except Exception as e:
        logger.error(f"程序执行失败: {e}")
        logger.error(traceback.format_exc())
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)