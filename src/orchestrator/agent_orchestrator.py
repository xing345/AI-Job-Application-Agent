"""
Agent Orchestrator - Agent v2.0 中央控制器
协调整个求职Agent的各个模块，实现智能化的求职流程管理
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
import sqlite3
from loguru import logger

# 添加项目根目录到路径
import sys
import os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# 导入各个模块
from src.reflection.self_reflection_system import SelfReflectionSystem
from src.email.email_listener import EmailListener
from src.models.dynamic_persona_generator import DynamicUserPersonaGenerator
from src.search.job_searcher import JobSearcher
from src.matching.matching_engine import SmartMatchingEngine
from src.browser.browser_agent import BrowserAgent
from src.automation.smart_form_filler import SmartFormFiller


class AgentOrchestrator:
    """Agent中央控制器"""

    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化Agent Orchestrator

        Args:
            config: 配置信息
        """
        self.config = config or self._get_default_config()
        self.db_path = str(Path(project_root) / "data" / "agent_state.db")

        # 初始化各个模块
        self.user_persona = None
        self.job_searcher = None
        self.matching_engine = None
        self.browser_agent = None
        self.form_filler = None
        self.reflection_system = None
        self.email_listener = None

        # 状态控制
        self.is_running = False
        self.current_tasks = {}
        self.agent_metrics = {
            'total_searches': 0,
            'total_applications': 0,
            'successful_submissions': 0,
            'rejections_processed': 0,
            'learning_cycles': 0,
            'last_update': datetime.now().isoformat()
        }

    def _get_default_config(self) -> Dict:
        """获取默认配置"""
        return {
            'search': {
                'interval_hours': 24,
                'max_results_per_search': 50,
                'sources': ['linkedin', 'indeed', 'bosszhipin']
            },
            'matching': {
                'threshold_score': 70,
                'auto_apply': False,
                'dry_run': True
            },
            'browser': {
                'headless': True,
                'timeout': 30000,
                'max_retries': 3
            },
            'reflection': {
                'enabled': True,
                'learning_mode': 'active'
            },
            'email': {
                'enabled': True,
                'check_interval_minutes': 300,
                'server': 'imap.gmail.com',
                'username': '',
                'password': ''
            }
        }

    async def initialize(self):
        """初始化所有模块"""
        logger.info("初始化Agent Orchestrator...")

        try:
            # 确保数据目录存在
            data_dir = Path(self.db_path).parent
            data_dir.mkdir(parents=True, exist_ok=True)

            # 初始化各模块
            await self._initialize_modules()

            # 加载之前的用户画像（如果存在）
            await self._load_user_persona()

            logger.info("Agent Orchestrator初始化完成")

        except Exception as e:
            logger.error(f"初始化失败: {e}")
            raise

    async def _initialize_modules(self):
        """初始化各个功能模块"""
        # 初始化自反思系统
        self.reflection_system = SelfReflectionSystem(self.db_path)
        logger.info("✅ 自反思系统已初始化")

        # 初始化邮箱监听器
        if self.config['email']['enabled']:
            await self._initialize_email_listener()
            logger.info("✅ 邮箱监听器已初始化")

        # 初始化搜索引擎
        self.job_searcher = JobSearcher(self.config)
        logger.info("✅ 搜索引擎已初始化")

        # 初始化匹配引擎
        self.matching_engine = SmartMatchingEngine()
        logger.info("✅ 匹配引擎已初始化")

        # 初始化浏览器Agent
        self.browser_agent = BrowserAgent(
            headless=self.config['browser']['headless'],
            timeout=self.config['browser']['timeout']
        )
        logger.info("✅ 浏览器Agent已初始化")

        # 初始化智能表单填充器
        self.form_filler = SmartFormFiller(
            headless=self.config['browser']['headless'],
            timeout=self.config['browser']['timeout']
        )
        logger.info("✅ 智能表单填充器已初始化")

    async def _initialize_email_listener(self):
        """初始化邮箱监听器"""
        if not self.user_persona:
            logger.warning("用户画像尚未初始化，跳过邮箱监听器初始化")
            return

        email_config = self.config['email']
        self.email_listener = await self._create_email_listener(
            user_persona=self.user_persona,
            config=email_config
        )

    async def _create_email_listener(self, user_persona: Dict, config: Dict):
        """创建邮箱监听器"""
        # 这里需要真实的邮箱配置
        if not config.get('username') or not config.get('password'):
            logger.warning("邮箱配置不完整，邮箱监听器将使用测试模式")
            # 使用测试配置
            config['username'] = 'test@example.com'
            config['password'] = 'test_password'

        from src.email.email_listener import create_email_listener
        return await create_email_listener(user_persona, config)

    async def _load_user_persona(self):
        """加载用户画像"""
        try:
            db_path = Path(project_root) / "data" / "user_persona.json"
            if db_path.exists():
                with open(db_path, 'r', encoding='utf-8') as f:
                    self.user_persona = json.load(f)
                logger.info(f"已加载用户画像: {self.user_persona.get('name', 'Unknown')}")
            else:
                # 如果没有现有画像，需要先生成
                logger.info("未找到现有用户画像，需要先生成")
        except Exception as e:
            logger.error(f"加载用户画像失败: {e}")

    async def generate_user_persona(self, resume_path: str, user_prompt: str):
        """
        生成用户画像

        Args:
            resume_path: 简历文件路径
            user_prompt: 用户自定义描述
        """
        logger.info("开始生成用户画像...")

        try:
            # 初始化动态用户画像生成器
            generator = DynamicUserPersonaGenerator()

            # 生成画像
            self.user_persona = await generator.generate_persona(
                resume_path=resume_path,
                user_prompt=user_prompt
            )

            # 保存画像
            await self._save_user_persona()

            logger.info("用户画像生成完成")

            # 如果邮箱监听器已初始化，更新监听器
            if self.email_listener and self.user_persona:
                await self.email_listener.initialize(self.user_persona)

        except Exception as e:
            logger.error(f"生成用户画像失败: {e}")
            raise

    async def _save_user_persona(self):
        """保存用户画像"""
        try:
            db_dir = Path(self.db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)

            db_path = db_dir / "user_persona.json"
            with open(db_path, 'w', encoding='utf-8') as f:
                json.dump(self.user_persona, f, ensure_ascii=False, indent=2)

            logger.info("用户画像已保存")

        except Exception as e:
            logger.error(f"保存用户画像失败: {e}")

    async def start_job_search_workflow(self):
        """启动求职工作流"""
        logger.info("启动求职工作流...")

        if not self.user_persona:
            logger.error("用户画像尚未生成")
            return

        try:
            # 创建任务ID
            task_id = f"job_search_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.current_tasks[task_id] = {
                'type': 'job_search',
                'status': 'running',
                'start_time': datetime.now().isoformat(),
                'data': {}
            }

            # 执行搜索
            logger.info("开始搜索职位...")
            jobs = await self.job_searcher.search_jobs(self.user_persona)

            # 更新任务状态
            self.current_tasks[task_id]['data']['found_jobs'] = len(jobs)
            self.agent_metrics['total_searches'] += 1

            # 执行匹配分析
            logger.info("开始职位匹配分析...")
            matching_results = []
            for job in jobs:
                match_result = await self.matching_engine.match_persona_with_job(
                    persona=self.user_persona,
                    job_description=job.get("description", "") if isinstance(job, dict) else str(job),
                    job_url=job.get("url") if isinstance(job, dict) else None
                )
                matching_results.append(match_result)

            # 过滤高匹配度职位
            high_match_jobs = [
                job for job, match_result in zip(jobs, matching_results)
                if match_result.match_score >= self.config['matching']['threshold_score']
            ]

            logger.info(f"找到 {len(high_match_jobs)} 个高匹配度职位")

            # 更新任务完成状态
            self.current_tasks[task_id]['status'] = 'completed'
            self.current_tasks[task_id]['end_time'] = datetime.now().isoformat()
            self.current_tasks[task_id]['data']['high_match_jobs'] = len(high_match_jobs)

            # 返回结果
            return {
                'task_id': task_id,
                'total_jobs_found': len(jobs),
                'high_match_jobs': len(high_match_jobs),
                'matching_results': matching_results
            }

        except Exception as e:
            logger.error(f"求职工作流执行失败: {e}")
            # 更新任务状态为失败
            if task_id in self.current_tasks:
                self.current_tasks[task_id]['status'] = 'failed'
                self.current_tasks[task_id]['error'] = str(e)
            raise

    async def apply_to_jobs(self, job_urls: List[str]):
        """
        申请指定职位的链接

        Args:
            job_urls: 职位URL列表
        """
        logger.info(f"开始申请 {len(job_urls)} 个职位...")

        task_id = f"apply_jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.current_tasks[task_id] = {
            'type': 'apply_jobs',
            'status': 'running',
            'start_time': datetime.now().isoformat(),
            'data': {'applied_jobs': [], 'failed_jobs': []}
        }

        try:
            for i, url in enumerate(job_urls):
                logger.info(f"正在申请第 {i+1}/{len(job_urls)} 个职位: {url}")

                try:
                    # 使用智能表单填充器
                    result = await self.form_filler.fill_form(
                        url=url,
                        persona=self.user_persona,
                        storage_path=str(Path(self.db_path).parent / "forms")
                    )

                    if result['success']:
                        # 更新任务数据
                        self.current_tasks[task_id]['data']['applied_jobs'].append({
                            'url': url,
                            'result': result
                        })
                        self.agent_metrics['total_applications'] += 1

                        # 如果提交成功
                        if result.get('submited', False):
                            self.agent_metrics['successful_submissions'] += 1

                        logger.info(f"✅ 成功申请: {url}")
                    else:
                        # 记录失败
                        self.current_tasks[task_id]['data']['failed_jobs'].append({
                            'url': url,
                            'error': result.get('error', '未知错误')
                        })
                        logger.error(f"❌ 申请失败: {url} - {result.get('error')}")

                except Exception as e:
                    logger.error(f"申请职位时出错: {url} - {e}")
                    self.current_tasks[task_id]['data']['failed_jobs'].append({
                        'url': url,
                        'error': str(e)
                    })

                # 添加延迟，避免过于频繁
                await asyncio.sleep(2)

            # 更新任务状态
            self.current_tasks[task_id]['status'] = 'completed'
            self.current_tasks[task_id]['end_time'] = datetime.now().isoformat()

        except Exception as e:
            logger.error(f"批量申请职位失败: {e}")
            if task_id in self.current_tasks:
                self.current_tasks[task_id]['status'] = 'failed'
                self.current_tasks[task_id]['error'] = str(e)
            raise

        return task_id

    async def start_continuous_monitoring(self):
        """启动持续监控模式"""
        logger.info("启动持续监控模式...")

        if not self.email_listener:
            logger.warning("邮箱监听器未初始化，无法持续监控")
            return

        # 启动邮箱监听
        email_task = asyncio.create_task(
            self.email_listener.start_monitoring(
                interval=self.config['email']['check_interval_minutes']
            )
        )

        # 定期执行任务
        search_task = asyncio.create_task(
            self._periodic_job_search()
        )

        # 等待任务完成或手动停止
        try:
            await asyncio.gather(email_task, search_task)
        except asyncio.CancelledError:
            logger.info("监控模式已停止")
        finally:
            # 清理任务
            email_task.cancel()
            search_task.cancel()

    async def _periodic_job_search(self):
        """定期职位搜索"""
        while self.is_running:
            try:
                await asyncio.sleep(self.config['search']['interval_hours'] * 3600)

                if not self.is_running:
                    break

                logger.info("执行定期职位搜索...")
                await self.start_job_search_workflow()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"定期搜索出错: {e}")
                await asyncio.sleep(60)  # 出错后等待1分钟再试

    async def get_agent_status(self) -> Dict:
        """获取Agent状态"""
        try:
            # 获取邮箱监听状态
            email_status = self.email_listener.get_monitoring_status() if self.email_listener else {}

            # 获取反思统计
            reflections_count = await self._get_reflections_count()

            # 获取策略规则
            strategy_rules = (
                await self.reflection_system.get_active_strategy_rules()
                if self.reflection_system else []
            )

            # 返回完整状态
            status = {
                'is_running': self.is_running,
                'user_persona_loaded': self.user_persona is not None,
                'current_tasks': self.current_tasks,
                'agent_metrics': self.agent_metrics,
                'email_status': email_status,
                'reflections_count': reflections_count,
                'active_strategy_rules': len(strategy_rules),
                'last_update': datetime.now().isoformat()
            }

            return status

        except Exception as e:
            logger.error(f"获取Agent状态失败: {e}")
            return {'error': str(e)}

    async def _get_reflections_count(self) -> int:
        """获取反思记录数量"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) FROM reflections')
            count = cursor.fetchone()[0]

            conn.close()
            return count

        except Exception as e:
            logger.error(f"获取反思记录数失败: {e}")
            return 0

    async def get_learning_insights(self) -> Dict:
        """获取学习洞察"""
        try:
            # 获取反思记录
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
            SELECT failure_reason_category, COUNT(*) as count
            FROM reflections
            GROUP BY failure_reason_category
            ORDER BY count DESC
            ''')

            failure_analysis = [
                {'reason': row[0], 'count': row[1]}
                for row in cursor.fetchall()
            ]

            # 获取最近的反思建议
            cursor.execute('''
            SELECT actionable_advice, created_at
            FROM reflections
            ORDER BY created_at DESC
            LIMIT 5
            ''')

            recent_advice = [
                {
                    'advice': json.loads(row[0]) if isinstance(row[0], str) else row[0],
                    'created_at': row[1]
                }
                for row in cursor.fetchall()
            ]

            # 获取策略规则分类
            cursor.execute('''
            SELECT rule_type, COUNT(*) as count, AVG(confidence_score) as avg_confidence
            FROM strategy_rules
            WHERE is_active = 1
            GROUP BY rule_type
            ''')

            rule_analysis = [
                {
                    'type': row[0],
                    'count': row[1],
                    'avg_confidence': row[2]
                }
                for row in cursor.fetchall()
            ]

            conn.close()

            return {
                'failure_analysis': failure_analysis,
                'recent_advice': recent_advice,
                'rule_analysis': rule_analysis,
                'total_reflections': await self._get_reflections_count()
            }

        except Exception as e:
            logger.error(f"获取学习洞察失败: {e}")
            return {'error': str(e)}

    async def start(self):
        """启动Agent"""
        logger.info("启动Agent...")

        try:
            # 设置运行状态
            self.is_running = True

            # 初始化各模块
            await self.initialize()

            logger.info("Agent启动成功")

            # 启动持续监控（如果启用）
            if self.config['reflection']['enabled'] and self.email_listener:
                await self.start_continuous_monitoring()

        except Exception as e:
            logger.error(f"启动Agent失败: {e}")
            self.is_running = False
            raise

    async def stop(self):
        """停止Agent"""
        logger.info("正在停止Agent...")

        try:
            # 停止运行状态
            self.is_running = False

            # 停止邮箱监听器
            if self.email_listener:
                await self.email_listener.stop_monitoring()

            logger.info("Agent已停止")

        except Exception as e:
            logger.error(f"停止Agent时出错: {e}")
            raise

    async def emergency_stop(self):
        """紧急停止"""
        logger.warning("执行紧急停止...")

        try:
            self.is_running = False

            # 停止所有当前任务
            for task_id in self.current_tasks:
                if self.current_tasks[task_id]['status'] == 'running':
                    self.current_tasks[task_id]['status'] = 'stopped'
                    self.current_tasks[task_id]['stop_reason'] = 'emergency_stop'

            # 停止邮箱监听器
            if self.email_listener:
                await self.email_listener.stop_monitoring()

            logger.info("紧急停止完成")

        except Exception as e:
            logger.error(f"紧急停止失败: {e}")
            raise


# 配置示例
DEFAULT_AGENT_CONFIG = {
    'search': {
        'interval_hours': 24,
        'max_results_per_search': 50,
        'sources': ['linkedin', 'indeed', 'bosszhipin']
    },
    'matching': {
        'threshold_score': 70,
        'auto_apply': False,
        'dry_run': False
    },
    'browser': {
        'headless': True,
        'timeout': 30000,
        'max_retries': 3
    },
    'reflection': {
        'enabled': True,
        'learning_mode': 'active'
    },
    'email': {
        'enabled': True,
        'check_interval_minutes': 300,
        'server': 'imap.gmail.com',
        'username': 'your_email@gmail.com',
        'password': 'your_app_password'
    }
}


async def create_agent_orchestrator(config: Dict = None) -> AgentOrchestrator:
    """
    创建Agent Orchestrator实例

    Args:
        config: 配置信息

    Returns:
        AgentOrchestrator: Agent控制器实例
    """
    orchestrator = AgentOrchestrator(config or DEFAULT_AGENT_CONFIG)
    await orchestrator.initialize()
    return orchestrator


# 测试函数
async def test_agent_orchestrator():
    """测试Agent Orchestrator"""
    print("=== 测试Agent Orchestrator ===")

    try:
        # 创建Agent控制器
        orchestrator = await create_agent_orchestrator()

        # 获取状态
        status = await orchestrator.get_agent_status()
        print(f"Agent状态: {status}")

        # 测试用户画像生成（需要有简历文件）
        resume_path = Path(project_root) / "data" / "resume.pdf"
        user_prompt = "我想找前端开发相关的工作，特别是React和Vue方向"

        if resume_path.exists():
            print("生成用户画像...")
            await orchestrator.generate_user_persona(
                resume_path=str(resume_path),
                user_prompt=user_prompt
            )
        else:
            print("简历文件不存在，跳过用户画像生成测试")

        print("✅ 测试完成！")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

    return True


if __name__ == "__main__":
    # 运行测试
    asyncio.run(test_agent_orchestrator())