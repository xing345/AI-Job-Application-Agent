"""
自反思系统 - Agent智能学习模块
当收到拒信时进行深度分析，生成改进策略
"""

import asyncio
import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
from loguru import logger

# 添加项目根目录到路径
import sys
import os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.utils.llm_client import get_llm_client
from src.models.schemas import ReflectionResult, StrategyRule, ApplicationWithReflection


class SelfReflectionSystem:
    """自反思系统"""

    def __init__(self, db_path: str = None):
        self.llm_client = get_llm_client()
        self.db_path = db_path or self._get_default_db_path()
        self._init_database()

    def _get_default_db_path(self) -> str:
        """获取默认数据库路径"""
        return str(Path(project_root) / "data" / "agent_state.db")

    def _init_database(self):
        """初始化数据库"""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 创建应用表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS job_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            company_name TEXT NOT NULL,
            job_title TEXT NOT NULL,
            match_score REAL,
            status TEXT DEFAULT 'PENDING',
            url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            error_message TEXT,
            search_source TEXT,
            original_jd TEXT,
            user_persona_snapshot TEXT
        )
        ''')

        # 创建反思表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER,
            failure_reason_category TEXT,
            root_cause_analysis TEXT,
            actionable_advice TEXT,
            should_update_persona BOOLEAN,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (application_id) REFERENCES job_applications (id)
        )
        ''')

        # 创建策略规则表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS strategy_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_type TEXT,
            rule_content TEXT,
            confidence_score REAL DEFAULT 1.0,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP,
            category TEXT,
            examples_count INTEGER DEFAULT 0
        )
        ''')

        conn.commit()
        conn.close()

    async def process_rejection(
        self,
        application_data: Dict[str, Any],
        rejection_email: str,
        user_persona: Dict[str, Any]
    ) -> ReflectionResult:
        """
        处理拒信，进行反思分析

        Args:
            application_data: 申请数据
            rejection_email: 拒信内容
            user_persona: 用户画像

        Returns:
            反思结果
        """
        logger.info(f"开始处理拒信: {application_data.get('company_name', 'Unknown')} - {application_data.get('job_title', 'Unknown')}")

        try:
            # 构建反思提示
            reflection_prompt = self._build_reflection_prompt(
                application_data=application_data,
                rejection_email=rejection_email,
                user_persona=user_persona
            )

            # 调用LLM进行反思分析
            response = await self.llm_client.generate_response(
                reflection_prompt,
                json_output=True
            )

            # 验证和解析结果
            reflection_result = ReflectionResult(**response)

            logger.info(f"反思完成 - 原因: {reflection_result.failure_reason_category}")
            logger.info(f"建议: {len(reflection_result.actionable_advice)}条")

            return reflection_result

        except Exception as e:
            logger.error(f"反思处理失败: {e}")
            # 返回默认的反思结果
            return ReflectionResult(
                failure_reason_category="未知原因",
                root_cause_analysis="反思分析过程中出现错误",
                actionable_advice=["请检查日志并重试"],
                should_update_persona=False
            )

    def _build_reflection_prompt(
        self,
        application_data: Dict[str, Any],
        rejection_email: str,
        user_persona: Dict[str, Any]
    ) -> str:
        """
        构建反思提示词
        """
        # 获取原始JD（如果有的话）
        original_jd = application_data.get('original_jd', '')
        previous_match_score = application_data.get('match_score', 0)
        previous_match_reason = application_data.get('match_reasons', [])

        prompt = f"""
你是一位资深的AI技术猎头与数据分析师。你的任务是对Agent的一次"失败投递"进行深度复盘。

【输入信息】
1. 岗位描述 (JD):
{original_jd[:2000]}

2. 候选人画像 (DynamicUserPersona):
{json.dumps(user_persona, ensure_ascii=False, indent=2)[:2000]}

3. 之前Agent给出的匹配打分及理由:
匹配分数: {previous_match_score}
匹配原因: {', '.join(previous_match_reason)}

4. HR回复的拒信原文:
{rejection_email[:2000]}

【分析任务】
请对比JD的硬性要求与候选人的真实画像，分析此次被拒的根本原因。
注意：拒信通常是客套的模板回复，你需要透过现象看本质。

**关键分析维度**：
1. **经验年限不匹配**: JD要求X年经验，候选人实际经验不足或过度
2. **技术栈不对口**: JD要求的技术A/B/C，候选人擅长X/Y/Z，存在根本性差异
3. **学历/身份限制**: JD隐含对学历、工作地点、身份的要求与候选人不匹配
4. **职位层级错位**: JD实际要的是Senior/Staff级别，候选人投递Junior级别
5. **公司文化/业务不匹配**: JD描述的业务方向与候选人的经验背景不符
6. **简历匹配度低**: 简历中与JD要求的关键词匹配度低
7. **竞聘过于激烈**: 虽然匹配度高，但竞争者更优秀

【输出要求】
请以严格的JSON格式输出，遵守ReflectionResult Schema：
1. failure_reason_category: 从上述维度中选择最合适的分类
2. root_cause_analysis: 给出具体的失败逻辑链路（1-2句话）
3. actionable_advice: 给出3-5条具体的操作建议，包括：
   - 搜索时如何过滤（如：过滤掉带有'Senior'且要求5+年经验的岗位）
   - 投递时如何调整（如：优先寻找接受Cocos生态的公司）
   - 画像如何更新（如：补充某些技能描述）
   - 匹配策略如何优化（如：某些类型岗位的匹配分数调整）
4. should_update_persona: 如果是候选人画像信息不足或错误导致的误判，返回true；否则返回false

输出格式：
{{
    "failure_reason_category": "具体分类",
    "root_cause_analysis": "深度分析总结",
    "actionable_advice": ["建议1", "建议2", "建议3"],
    "should_update_persona": true/false
}}
        """

        return prompt

    async def save_reflection(
        self,
        application_data: Dict[str, Any],
        reflection_result: ReflectionResult
    ) -> int:
        """
        保存反思结果到数据库

        Args:
            application_data: 申请数据
            reflection_result: 反思结果

        Returns:
            反思记录ID
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 先确保应用记录存在，不存在则创建
            cursor.execute('''
            SELECT id FROM job_applications
            WHERE job_id = ? AND company_name = ? AND job_title = ?
            ''', (application_data['job_id'], application_data['company_name'], application_data['job_title']))

            result = cursor.fetchone()
            if result:
                application_id = result[0]
            else:
                # 创建新的应用记录
                cursor.execute('''
                INSERT INTO job_applications (
                    job_id, company_name, job_title, match_score, status,
                    url, original_jd, user_persona_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    application_data['job_id'],
                    application_data['company_name'],
                    application_data['job_title'],
                    application_data.get('match_score', 0),
                    'REJECTED',
                    application_data.get('url', ''),
                    application_data.get('original_jd', ''),
                    json.dumps(application_data.get('user_persona', {}), ensure_ascii=False)
                ))
                application_id = cursor.lastrowid

            # 保存反思结果
            cursor.execute('''
            INSERT INTO reflections (
                application_id, failure_reason_category, root_cause_analysis,
                actionable_advice, should_update_persona
            ) VALUES (?, ?, ?, ?, ?)
            ''', (
                application_id,
                reflection_result.failure_reason_category,
                reflection_result.root_cause_analysis,
                json.dumps(reflection_result.actionable_advice, ensure_ascii=False),
                reflection_result.should_update_persona
            ))

            reflection_id = cursor.lastrowid

            # 生成策略规则
            await self._generate_strategy_rules(reflection_result)

            conn.commit()
            conn.close()

            logger.info(f"反思结果已保存，ID: {reflection_id}")
            return reflection_id

        except Exception as e:
            logger.error(f"保存反思结果失败: {e}")
            return None

    async def _generate_strategy_rules(self, reflection_result: ReflectionResult):
        """
        根据反思结果生成策略规则
        """
        try:
            # 分析建议并生成规则
            for advice in reflection_result.actionable_advice:
                # 根据建议内容推断规则类型
                rule_type, rule_content = self._parse_advice_to_rule(advice)

                if rule_type and rule_content:
                    # 计算置信度（基于建议的明确性和可操作性）
                    confidence = self._calculate_rule_confidence(advice)

                    # 保存策略规则
                    await self._save_strategy_rule(
                        rule_type=rule_type,
                        rule_content=rule_content,
                        confidence=confidence,
                        category=reflection_result.failure_reason_category
                    )

        except Exception as e:
            logger.error(f"生成策略规则失败: {e}")

    def _parse_advice_to_rule(self, advice: str) -> tuple:
        """
        将建议转换为策略规则
        """
        advice_lower = advice.lower()

        # 搜索过滤规则
        if any(keyword in advice_lower for keyword in ['过滤', '排除', '跳过']):
            if 'senior' in advice_lower or '高级' in advice_lower:
                return 'search_filter', '过滤包含"Senior"或"高级"且要求5年以上经验的岗位'
            elif '管理' in advice_lower or 'manager' in advice_lower:
                return 'search_filter', '过滤包含管理相关字眼的岗位（除非明确要求技术管理）'
            elif '学历' in advice_lower or '学历' in advice_lower:
                return 'search_filter', '过滤明确要求特定学历（如硕士以上）且不符合的岗位'
            else:
                return 'search_filter', advice

        # 匹配调整规则
        elif any(keyword in advice_lower for keyword in ['调整', '修改', '优化']):
            if '匹配分数' in advice_lower:
                return 'matching_adjustment', advice
            else:
                return 'matching_adjustment', f'根据经验调整匹配算法: {advice}'

        # 应用策略规则
        elif any(keyword in advice_lower for keyword in ['优先', '重点', '关注']):
            return 'application_strategy', advice

        # 画像更新规则
        elif any(keyword in advice_lower for keyword in ['补充', '添加', '更新']):
            return 'persona_update', advice

        # 默认为搜索规则
        return 'search_filter', advice

    def _calculate_rule_confidence(self, advice: str) -> float:
        """
        计算规则的置信度
        """
        confidence = 0.5  # 基础置信度

        # 检查建议的明确性
        if len(advice.split()) > 10:  # 较长的建议通常更具体
            confidence += 0.2

        # 检查是否包含可操作的关键词
        actionable_keywords = ['过滤', '排除', '优先', '调整', '修改', '补充']
        if any(keyword in advice.lower() for keyword in actionable_keywords):
            confidence += 0.2

        # 检查是否包含具体的数值或标准
        if any(char.isdigit() for char in advice):
            confidence += 0.1

        return min(confidence, 1.0)

    async def _save_strategy_rule(
        self,
        rule_type: str,
        rule_content: str,
        confidence: float,
        category: str
    ):
        """
        保存策略规则到数据库
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 检查是否已存在类似的规则
            cursor.execute('''
            SELECT id, examples_count FROM strategy_rules
            WHERE rule_type = ? AND rule_content = ? AND category = ?
            ''', (rule_type, rule_content, category))

            result = cursor.fetchone()
            if result:
                # 更新现有规则
                rule_id, examples_count = result
                cursor.execute('''
                UPDATE strategy_rules
                SET confidence_score = ?, examples_count = ?, last_used = CURRENT_TIMESTAMP
                WHERE id = ?
                ''', (confidence, examples_count + 1, rule_id))
            else:
                # 创建新规则
                cursor.execute('''
                INSERT INTO strategy_rules (
                    rule_type, rule_content, confidence_score, category, examples_count
                ) VALUES (?, ?, ?, ?, 1)
                ''', (rule_type, rule_content, confidence, category))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"保存策略规则失败: {e}")

    async def get_active_strategy_rules(self) -> List[Dict]:
        """
        获取激活的策略规则
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
            SELECT rule_type, rule_content, confidence_score, category, last_used
            FROM strategy_rules
            WHERE is_active = 1
            ORDER BY last_used DESC, confidence_score DESC
            ''')

            rules = cursor.fetchall()
            conn.close()

            return [
                {
                    'type': rule[0],
                    'content': rule[1],
                    'confidence': rule[2],
                    'category': rule[3],
                    'last_used': rule[4]
                }
                for rule in rules
            ]

        except Exception as e:
            logger.error(f"获取策略规则失败: {e}")
            return []

    async def update_user_persona_from_reflection(
        self,
        user_persona: Dict,
        reflection_result: ReflectionResult
    ) -> Dict:
        """
        根据反思结果更新用户画像
        """
        if not reflection_result.should_update_persona:
            return user_persona

        try:
            # 构建更新提示
            update_prompt = f"""
你是一个专业的职业顾问。根据以下反思结果，优化用户的职业画像。

【当前画像】
{json.dumps(user_persona, ensure_ascii=False, indent=2)}

【反思结果】
失败原因分类: {reflection_result.failure_reason_category}
根因分析: {reflection_result.root_cause_analysis}
改进建议: {json.dumps(reflection_result.actionable_advice, ensure_ascii=False)}

【更新任务】
根据反思建议，对用户画像进行以下调整：
1. 强化相关技能描述
2. 调整职业目标
3. 优化偏好设置
4. 补充缺失的经验描述

请返回更新后的完整用户画像，保持原有结构不变。
"""

            # 调用LLM更新画像
            response = await self.llm_client.generate_response(
                update_prompt,
                json_output=True
            )

            updated_persona = response
            logger.info("用户画像已根据反思结果更新")
            return updated_persona

        except Exception as e:
            logger.error(f"更新用户画像失败: {e}")
            return user_persona


# 工具函数
async def create_reflection_system(db_path: str = None) -> SelfReflectionSystem:
    """创建自反思系统实例"""
    return SelfReflectionSystem(db_path)


async def process_rejection_workflow(
    application_data: Dict,
    rejection_email: str,
    user_persona: Dict,
    db_path: str = None
) -> Dict:
    """
    完整的拒信处理工作流

    Args:
        application_data: 申请数据
        rejection_email: 拒信内容
        user_persona: 用户画像
        db_path: 数据库路径

    Returns:
        处理结果
    """
    try:
        # 创建反思系统
        reflection_system = await create_reflection_system(db_path)

        # 执行反思分析
        reflection_result = await reflection_system.process_rejection(
            application_data=application_data,
            rejection_email=rejection_email,
            user_persona=user_persona
        )

        # 保存反思结果
        reflection_id = await reflection_system.save_reflection(
            application_data=application_data,
            reflection_result=reflection_result
        )

        # 更新用户画像（如果需要）
        if reflection_result.should_update_persona:
            updated_persona = await reflection_system.update_user_persona_from_reflection(
                user_persona=user_persona,
                reflection_result=reflection_result
            )
        else:
            updated_persona = None

        return {
            'success': True,
            'reflection_id': reflection_id,
            'reflection_result': reflection_result.model_dump(),
            'updated_persona': updated_persona,
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"拒信处理工作流失败: {e}")
        return {
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }


# 测试函数
async def test_reflection_system():
    """测试自反思系统"""
    print("=== 测试自反思系统 ===")

    # 模拟数据
    application_data = {
        'job_id': 'test_job_001',
        'company_name': '测试公司',
        'job_title': '高级前端工程师',
        'match_score': 85,
        'match_reasons': ['React技能匹配', '项目经验相关'],
        'original_jd': '要求5年以上前端开发经验，熟悉React、Vue等框架，有大型项目经验...',
        'url': 'https://example.com/job/001'
    }

    rejection_email = """
    尊敬的候选人：

    感谢您对我们公司的关注和申请。经过综合评估，我们认为您目前的经验和技能与我们的需求存在一定差距，因此无法进入下一轮面试。

    祝您求职顺利！
    """

    user_persona = {
        'name': '测试用户',
        'technical_skills': {
            'programming_languages': ['JavaScript', 'TypeScript'],
            'frameworks': ['React', 'Vue']
        },
        'experience_years': 3  # 实际只有3年经验
    }

    try:
        # 执行完整工作流
        result = await process_rejection_workflow(
            application_data=application_data,
            rejection_email=rejection_email,
            user_persona=user_persona
        )

        print(f"✅ 测试成功！")
        print(f"   反思ID: {result['reflection_id']}")
        print(f"   原因分类: {result['reflection_result']['failure_reason_category']}")
        print(f"   建议数量: {len(result['reflection_result']['actionable_advice'])}")
        print(f"   更新画像: {'是' if result['updated_persona'] else '否'}")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(test_reflection_system())