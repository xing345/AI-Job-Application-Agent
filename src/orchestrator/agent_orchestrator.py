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
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# 导入各个模块
from src.reflection.self_reflection_system import SelfReflectionSystem
from src.email.email_listener import EmailListener
from src.models.dynamic_persona_generator import DynamicUserPersonaGenerator
from src.models.schemas import DynamicUserPersona
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
                'use_browser': True,
                'use_company_sites': True,
                'max_companies': 5,
                'target_companies': [],
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

            # 先加载用户画像（邮箱监听器等模块依赖画像存在与否来决定是否启用）
            await self._load_user_persona()

            # 再初始化各模块
            await self._initialize_modules()

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

    async def _create_email_listener(self, user_persona: Any, config: Dict):
        """创建邮箱监听器"""
        # 需要真实的 IMAP 凭据（来自 .env 的 EMAIL_USERNAME / EMAIL_PASSWORD）。
        # 缺失时绝不伪造 test@example.com 去连接真实 IMAP 服务器。
        if not config.get('username') or not config.get('password'):
            logger.warning(
                "邮箱凭据缺失: 请在 .env 中配置 EMAIL_SERVER / EMAIL_USERNAME / EMAIL_PASSWORD "
                "（或 config.json 的 email 段）后重启，以启用邮箱监听"
            )
            return None

        from src.email.email_listener import create_email_listener
        # EmailListener 按 dict 使用画像数据
        if hasattr(user_persona, "model_dump"):
            user_persona = user_persona.model_dump(mode="json")
        return await create_email_listener(user_persona, config)

    async def _load_user_persona(self):
        """加载用户画像（统一为 DynamicUserPersona 模型，损坏/旧版数据给出明确指引）"""
        try:
            db_path = Path(project_root) / "data" / "user_persona.json"
            if db_path.exists():
                with open(db_path, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                # 画像持久化为完整模型数据时可直接还原; 版本不匹配时提示重新生成
                try:
                    self.user_persona = DynamicUserPersona.model_validate(raw)
                    logger.info(f"已加载用户画像: {self.user_persona.name}")
                except Exception as ve:
                    self.user_persona = None
                    logger.error(
                        f"用户画像数据与当前版本不兼容（{ve}）。请先运行 persona 重新生成画像。"
                    )
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

            # 画像就绪后，若邮箱监听未启用则尝试补建（此前因缺少画像被跳过）
            if self.config.get('email', {}).get('enabled') and self.email_listener is None:
                await self._initialize_email_listener()

            # 若邮箱监听器已存在，用新画像更新它
            if self.email_listener and self.user_persona:
                persona_dict = self.user_persona
                if hasattr(persona_dict, "model_dump"):
                    persona_dict = persona_dict.model_dump(mode="json")
                await self.email_listener.initialize(persona_dict)

        except Exception as e:
            logger.error(f"生成用户画像失败: {e}")
            raise

    async def _save_user_persona(self):
        """保存用户画像"""
        try:
            db_dir = Path(self.db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)

            db_path = db_dir / "user_persona.json"
            # pydantic 模型需转 dict 才能 json 序列化
            persona_data = self.user_persona
            if hasattr(persona_data, "model_dump"):
                persona_data = persona_data.model_dump(mode="json")
            with open(db_path, 'w', encoding='utf-8') as f:
                json.dump(persona_data, f, ensure_ascii=False, indent=2)

            logger.info("用户画像已保存")

        except Exception as e:
            logger.error(f"保存用户画像失败: {e}")

    def _save_search_results(self, jobs: List[Dict], matching_results: List) -> None:
        """将搜索结果持久化到 agent_state.db 的 job_search_log 表, 供 Dashboard 展示"""
        try:
            db_path = Path(project_root) / "data" / "agent_state.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_search_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT,
                    title TEXT,
                    company TEXT,
                    description TEXT,
                    match_score REAL,
                    searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            now = datetime.now().isoformat()
            for job, match in zip(jobs, matching_results):
                if isinstance(job, dict):
                    url = job.get("url")
                    title = job.get("title")
                    company = job.get("company") or ""
                    description = job.get("description") or ""
                    score = job.get("match_score")
                else:
                    url, title, company, description, score = None, str(job), "", "", None
                if score is None:
                    score = getattr(match, "match_score", getattr(match, "score", None))
                conn.execute(
                    "INSERT INTO job_search_log (url, title, company, description, match_score, searched_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (url, title, company, description, score, now),
                )
            conn.commit()
            conn.close()
            logger.info(f"已保存 {len(jobs)} 条搜索结果到 Dashboard 数据库")
        except Exception as e:
            logger.warning(f"保存搜索结果失败: {e}")

    async def start_job_search_workflow(self):
        """启动求职工作流"""
        logger.info("启动求职工作流...")

        # 画像统一为 DynamicUserPersona 模型（搜索器/匹配引擎均按模型属性读取）
        persona = self.user_persona
        if isinstance(persona, dict):
            try:
                persona = DynamicUserPersona.model_validate(persona)
                self.user_persona = persona
            except Exception as e:
                logger.error(f"用户画像数据不完整，无法用于搜索: {e}")
                return

        if not persona:
            logger.error("用户画像尚未生成，请先运行 persona")
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
            jobs = await self.job_searcher.search_jobs(persona)

            # 更新任务状态
            self.current_tasks[task_id]['data']['found_jobs'] = len(jobs)
            self.agent_metrics['total_searches'] += 1

            # 执行匹配分析
            logger.info("开始职位匹配分析...")
            matching_results = []
            for job in jobs:
                match_result = await self.matching_engine.match_persona_with_job(
                    persona=persona,
                    job_description=job.get("description", "") if isinstance(job, dict) else str(job),
                    job_url=job.get("url") if isinstance(job, dict) else None
                )
                matching_results.append(match_result)

            # 持久化搜索结果 (供 Dashboard 展示找到的岗位)
            self._save_search_results(jobs, matching_results)

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

    async def apply_to_jobs(self, job_urls: List[str], resume_path: str = None):
        """
        申请指定职位的链接

        Args:
            job_urls: 职位URL列表
            resume_path: 简历文件路径 (用于上传, 默认取 config paths.resume)
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
                        storage_path=str(Path(self.db_path).parent / "forms"),
                        resume_path=resume_path
                    )

                    if result['success']:
                        # 区分"已填写待人工提交"与"真正提交"：绝不在未提交时虚报申请数
                        submitted = bool(result.get('submitted', False))
                        record = {'url': url, 'result': result, 'submitted': submitted}
                        if submitted:
                            self.current_tasks[task_id]['data']['applied_jobs'].append(record)
                            self.agent_metrics['total_applications'] += 1
                            self.agent_metrics['successful_submissions'] += 1
                            logger.info(f"✅ 已提交申请: {url}")
                        else:
                            filled_list = self.current_tasks[task_id]['data'].setdefault('filled_jobs', [])
                            filled_list.append(record)
                            logger.info(f"✅ 表单已填写完成(待人工核对并手动提交): {url}")
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

    # ------------------------------------------------------------------ #
    # 岗位诊断模式: 智能访谈 → 方向诊断 → 按方向搜索 → 挑目标岗 → 针对性简历 → 投递
    # ------------------------------------------------------------------ #
    async def run_career_discovery_workflow(self, ask_func=None):
        """
        岗位诊断模式 - 不依赖简历, 根据求职者实际情况找岗并给建议, 再针对性做简历

        Args:
            ask_func: 提问函数 (默认终端 input, 测试时可注入)

        Returns:
            dict: 诊断结果 (画像/方向/目标岗位/简历路径) 或 None
        """
        from src.career.interviewer import CareerInterviewer
        from src.career.analyzer import CareerDirectionAnalyzer
        from src.career.resume_builder import TargetedResumeGenerator

        ask = ask_func or input
        print("\n" + "=" * 60)
        print("🧭 岗位诊断模式")
        print("=" * 60)
        print("第1步 智能访谈: 让我先了解你的实际情况\n")
        print("   (会的东西多而杂没关系, 我会帮你梳理; 不知道怎么答就说\"跳过\")")

        # 1. 智能访谈
        interviewer = CareerInterviewer()
        profile = await interviewer.run_interview(ask_func=ask)
        self._save_user_profile(profile)
        self._print_profile_summary(profile)

        # 2. 方向诊断
        print("\n🧠 正在分析你的技能与经历, 梳理可行的岗位方向...")
        analyzer = CareerDirectionAnalyzer()
        analysis = await analyzer.analyze(profile)
        self._save_career_directions(analysis)
        self._print_directions(analysis)

        # 3. 选择主攻方向
        chosen = self._choose_directions(analysis, ask)
        if not chosen:
            print("未选择任何方向, 诊断模式结束。")
            return None
        direction = chosen[0]

        # 4. 从实际情况 + 目标方向构建画像
        print(f"\n👤 正在根据你的实际情况与方向「{direction.title}」构建用户画像...")
        self.user_persona = await self._build_persona_from_profile(profile, direction, ask)
        if self.user_persona is None:
            print("缺少投递所需的基本信息, 诊断模式结束。")
            return None
        await self._save_user_persona()

        # 5. 按方向关键词搜索 + 匹配
        print(f"\n🔍 正在按方向「{direction.title}」搜索岗位...")
        jobs, matching_results = await self._search_by_direction(direction)
        if not jobs:
            print("❌ 未搜索到岗位。可换一个方向重试, 或稍后再试。")
            return None
        self._save_search_results(jobs, matching_results)
        self._print_matched_jobs(jobs)

        # 6. 选择目标岗位
        target_jobs = self._choose_target_jobs(jobs, ask)
        if not target_jobs:
            print("未选择目标岗位, 诊断模式结束。")
            return None

        # 7. 针对目标岗位生成简历
        print("\n📄 正在根据目标岗位 JD 生成针对性简历...")
        resume_builder = TargetedResumeGenerator()
        draft = await resume_builder.generate_draft(profile, self.user_persona, direction, target_jobs)
        resume_path = resume_builder.render_docx(
            draft, str(Path(project_root) / "data" / "resume.docx")
        )
        print(f"\n✅ 针对性简历已生成: {resume_path}")
        print("   ⚠️ 请先打开 Word 检查并修改简历, 确认无误后再投递。")

        # 8. 确认后投递
        confirm = ask(f"\n是否立即投递这 {len(target_jobs)} 个岗位? (y/n): ").strip().lower()
        if confirm in ("y", "yes", "是"):
            await self.apply_to_jobs([j["url"] for j in target_jobs], resume_path=resume_path)
        else:
            print("已跳过投递。岗位结果已保存到 Dashboard, 简历已生成, 之后可用 `apply` 命令投递。")

        return {
            "profile": profile.model_dump(mode="json"),
            "directions": analysis.model_dump(mode="json"),
            "chosen_direction": direction.model_dump(mode="json"),
            "target_jobs": target_jobs,
            "resume_path": resume_path,
        }

    def _save_user_profile(self, profile):
        """保存访谈产出的实际情况"""
        try:
            path = Path(project_root) / "data" / "user_profile.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.info(f"用户实际情况已保存: {path}")
        except Exception as e:
            logger.error(f"保存用户实际情况失败: {e}")

    def _save_career_directions(self, analysis):
        """保存岗位方向诊断结果 (供 Dashboard 展示)"""
        try:
            path = Path(project_root) / "data" / "career_directions.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.info(f"岗位方向诊断已保存: {path}")
        except Exception as e:
            logger.error(f"保存岗位方向诊断失败: {e}")

    def _print_profile_summary(self, profile):
        """打印访谈结果摘要"""
        print("\n" + "=" * 60)
        print("📋 已收集到你的实际情况 (保存于 data/user_profile.json)")
        print("=" * 60)
        print(f"姓名: {profile.name or '未提供'} | 邮箱: {profile.email or '未提供'} | 电话: {profile.phone or '未提供'}")
        if profile.all_skills:
            print(f"技能: {'、'.join(profile.all_skills)}")
        if profile.work_experience:
            exp = "、".join(f"{e.company}({e.role})" for e in profile.work_experience if e.company)
            print(f"经历: {exp}")
        if profile.locations:
            print(f"期望地点: {'、'.join(profile.locations)}")
        if profile.salary_expectation:
            print(f"期望薪资: {profile.salary_expectation}")
        if profile.target_hint:
            print(f"职业想法: {profile.target_hint}")

    def _print_directions(self, analysis):
        """打印岗位方向诊断结果"""
        print("\n" + "=" * 60)
        print("🧭 为你梳理的岗位方向")
        print("=" * 60)
        for i, d in enumerate(analysis.directions, 1):
            stars = "★" * d.priority + "☆" * (5 - d.priority)
            print(f"\n[{i}] {d.title}  推荐度 {stars}")
            print(f"    为什么适合: {d.summary}")
            print(f"    目标职位: {'、'.join(d.target_positions)}")
            print(f"    搜索关键词: {'、'.join(d.keywords)}")
            print(f"    你的亮点: {'、'.join(d.skill_highlights)}")
            print(f"    需要补: {'、'.join(d.skill_gaps) if d.skill_gaps else '暂无明显短板'}")
            print(f"    市场情况: {d.market_note}")
            print(f"    建议: {d.advice}")
        print(f"\n💡 总体建议: {analysis.overall_advice}")

    def _choose_directions(self, analysis, ask=None) -> List:
        """让用户选择主攻方向 (支持多选, 取第一个为主攻)"""
        ask = ask or input
        while True:
            inp = ask("\n请输入要主攻的方向序号 (可多选, 空格分隔; 直接回车选推荐第1个): ").strip()
            if not inp:
                return [analysis.directions[0]]
            try:
                idxs = [int(x) - 1 for x in inp.split()]
                chosen = [analysis.directions[i] for i in idxs if 0 <= i < len(analysis.directions)]
                if chosen:
                    return chosen
            except ValueError:
                pass
            print("输入无效, 请重新输入。")

    async def _build_persona_from_profile(self, profile, direction, ask=None):
        """
        从实际情况 + 目标方向构建用户画像 dict
        technical_skills 按 dict 约定 (匹配引擎与表单填充都按 dict 读取)
        """
        ask = ask or input
        name = profile.name or ""
        email = profile.email or ""
        phone = profile.phone or ""

        if not name or not email:
            print("\n⚠️ 投递需要基本联系方式:")
            if not name:
                name = ask("姓名: ").strip()
            if not email:
                email = ask("邮箱: ").strip()
            if not phone:
                phone = ask("电话: ").strip()
        if not email:
            print("❌ 缺少邮箱, 无法投递。")
            return None

        skills = list(dict.fromkeys(profile.all_skills))
        return {
            "name": name,
            "email": email,
            "phone": phone,
            "technical_skills": {"all": skills},
            "soft_skills": {},
            "domain_knowledge": {},
            "career_objective": {
                "target_positions": direction.target_positions,
                "preferred_industries": direction.preferred_industries,
                "location_preference": profile.locations or [],
                "salary_expectation": profile.salary_expectation or "面议",
                "work_type_preference": profile.work_type or "",
                "career_growth_focus": direction.keywords[:5],
            },
            "constraints": {
                "excluded_companies": [], "excluded_industries": [],
                "excluded_positions": [], "compensation_floor": None,
                "compensation_ceiling": None, "location_constraints": [],
                "travel_requirements": None, "work_schedule": None,
            },
            "personality_traits": {},
            "work_preferences": {},
            "motivators": [],
            "deal_breakers": profile.deal_breakers,
            "strengths": direction.skill_highlights,
            "weaknesses": direction.skill_gaps,
            "ideal_work_environment": [],
            "version": "career-discovery",
        }

    async def _search_by_direction(self, direction) -> tuple:
        """
        按方向关键词搜索岗位 (复用已配置的搜索管道, 直接传方向关键词)
        Returns:
            (jobs, matching_results) 与 start_job_search_workflow 同构
        """
        from src.models.instruction_schemas import TargetInstructionSchema
        from src.models.schemas import ResumeSchema

        locations = []
        if isinstance(self.user_persona, dict):
            obj = self.user_persona.get("career_objective", {}) or {}
            locations = obj.get("location_preference") or []

        target_info = TargetInstructionSchema(
            company="",
            role=(direction.target_positions[0] if direction.target_positions else direction.title),
            location=(locations[0] if locations else None),
            keywords=direction.keywords,
        )
        resume = ResumeSchema(
            name=(self.user_persona or {}).get("name", ""),
            email=(self.user_persona or {}).get("email", "candidate@example.com"),
            phone=(self.user_persona or {}).get("phone", ""),
            summary=f"求职目标: {direction.title}",
            skills=direction.keywords,
            work_experience=[],
            education=[],
            projects=[],
        )

        results = await self.job_searcher.pipeline.run_search_pipeline(
            target_info, resume, min_score=50, max_results=10
        )
        jobs = [{
            "url": r.url,
            "title": r.title,
            "description": r.match_result.match_summary or r.title,
            "match_result": r.match_result,
            "match_score": r.match_result.score,
        } for r in results]
        matching_results = [j["match_result"] for j in jobs]
        logger.info(f"按方向搜索完成: {direction.title}, 共 {len(jobs)} 个岗位")
        return jobs, matching_results

    def _print_matched_jobs(self, jobs):
        """打印搜索到的岗位"""
        print("\n" + "=" * 60)
        print(f"🎯 搜索到的岗位 ({len(jobs)} 个)")
        print("=" * 60)
        for i, job in enumerate(jobs, 1):
            mr = job.get("match_result")
            score = job.get("match_score", 0)
            reasons = []
            if mr is not None and hasattr(mr, "reasons") and mr.reasons:
                reasons = mr.reasons[:3]
            print(f"\n[{i}] {job.get('title', '未知职位')}  匹配 {score}/100")
            print(f"    {job.get('url')}")
            if reasons:
                print(f"    匹配点: {'、'.join(reasons)}")

    def _choose_target_jobs(self, jobs, ask=None) -> List:
        """让用户选择目标岗位"""
        ask = ask or input
        while True:
            inp = ask("\n选择要投递的岗位序号 (可多选, 空格分隔; 直接回车选匹配分≥60的岗位): ").strip()
            try:
                if not inp:
                    chosen = [j for j in jobs if j.get("match_score", 0) >= 60]
                    return chosen or [jobs[0]]
                idxs = [int(x) - 1 for x in inp.split()]
                chosen = [jobs[i] for i in idxs if 0 <= i < len(jobs)]
                if chosen:
                    return chosen
            except ValueError:
                pass
            print("输入无效, 请重新输入。")

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
        'use_browser': True,
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