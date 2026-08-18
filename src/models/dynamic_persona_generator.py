"""
动态用户画像生成器
基于简历解析和用户描述文本，生成详尽的用户画像
"""

import asyncio
import json
from typing import Dict, Any, List
from datetime import datetime
from loguru import logger

from src.models.schemas import (
    ResumeSchema,
    DynamicUserPersona,
    CareerObjective,
    SoftSkills,
    CareerConstraints,
    PersonalityTraits,
    ResumePrompt
)
from src.parsers.resume_parser import parse_pdf
from src.utils.llm_client import LLMClient


class DynamicUserPersonaGenerator:
    """动态用户画像生成器"""

    def __init__(self, model: str = "gpt-4"):
        self.llm_client = LLMClient(model=model)
        self.prompt_templates = self._load_prompt_templates()

    def _load_prompt_templates(self) -> Dict[str, str]:
        """加载提示模板"""
        return {
            "persona_generation": """
你是一位专业的职业顾问和人才分析师。基于以下简历信息和用户描述，生成一份详尽的用户画像。

简历信息：
{resume_info}

用户描述：
{user_prompt}

请生成包含以下维度的用户画像：

1. **基本信息**
   - 姓名、邮箱、电话
   - 专业背景概述

2. **核心技能与能力**
   - 技术技能（按熟练程度分类）
   - 软技能（沟通、领导力、团队协作等）
   - 领域知识掌握程度

3. **职业目标**
   - 目标职位
   - 偏好行业
   - 地点偏好
   - 薪资期望
   - 工作类型偏好

4. **性格特质**
   - 工作风格
   - 激励因素
   - 压力应对方式
   - 学习方式
   - 文化匹配倾向

5. **约束条件**
   - 排除的公司/行业/职位
   - 薪资底线和上限
   - 地点限制
   - 出差要求
   - 工作时间要求

6. **隐性特征**
   - 工作偏好
   - 激励因素
   - 绝对拒绝的条件

7. **分析维度**
   - 核心竞争力
   - 待改进领域
   - 理想工作环境

请确保：
- 分析深入，挖掘隐性需求和技能
- 考虑职业发展的连续性
- 识别用户可能没有明确表达的重要偏好
- 评估各项信息的可信度

输出格式必须是JSON，包含所有上述字段。
""",

            "skill_extraction": """
从简历信息中提取技术技能和软技能：

简历信息：
{resume_info}

要求：
1. 技术技能按类别分组（编程语言、框架、工具等）
2. 软技能从工作经历和项目经验中推断
3. 评估每个技能的熟练程度（1-5级）
4. 识别新兴技能和待提升技能

输出JSON格式：
{
    "technical_skills": {
        "programming_languages": [...],
        "frameworks": [...],
        "tools": [...],
        "databases": [...],
        "cloud": [...]
    },
    "soft_skills": {
        "communication": [...],
        "leadership": [...],
        "teamwork": [...],
        "problem_solving": [...],
        "creativity": [...],
        "adaptability": [...]
    },
    "skill_levels": {...}
}
""",

            "career_objective_analysis": """
分析用户的职业目标和偏好：

简历信息：
{resume_info}
用户描述：
{user_prompt}

要求：
1. 分析职业发展轨迹和目标
2. 识别偏好的行业和公司类型
3. 确定工作地点偏好
4. 评估薪资期望的合理性
5. 识别工作类型偏好（远程、混合、 onsite）

输出JSON格式：
{
    "target_positions": [...],
    "preferred_industries": [...],
    "location_preference": [...],
    "salary_expectation": "...",
    "work_type_preference": "...",
    "career_growth_focus": [...]
}
""",

            "constraints_identification": """
识别用户的职业约束条件：

简历信息：
{resume_info}
用户描述：
{user_prompt}

要求：
1. 识别明确排除的条件
2. 分析薪资底线和期望
3. 识别地理限制
4. 考虑工作时间和出差要求
5. 识别文化偏好的反面

输出JSON格式：
{
    "excluded_companies": [...],
    "excluded_industries": [...],
    "excluded_positions": [...],
    "compensation_floor": "...",
    "compensation_ceiling": "...",
    "location_constraints": [...],
    "travel_requirements": "...",
    "work_schedule": "..."
}
""",

            "personality_analysis": """
分析用户的性格特质和工作偏好：

简历信息：
{resume_info}
用户描述：
{user_prompt}

要求：
1. 从职业经历推断工作风格
2. 识别激励因素
3. 分析压力应对方式
4. 确定学习方式偏好
5. 评估文化匹配倾向

输出JSON格式：
{
    "work_style": [...],
    "motivation_factors": [...],
    "stress_response": "...",
    "learning_style": [...],
    "cultural_fit": [...]
}
        }

    async def generate_persona(
        self,
        resume_path: str,
        user_prompt: str,
        model: str = "gpt-4"
    ) -> DynamicUserPersona:
        """生成动态用户画像"""
        logger.info("开始生成动态用户画像...")

        # 1. 解析简历
        logger.info("解析简历文件...")
        resume_data = await parse_pdf(resume_path)
        if not resume_data:
            raise ValueError("简历解析失败")

        # 2. 构建简历信息字符串
        resume_info = self._format_resume_info(resume_data)

        # 3. 创建组合数据
        resume_prompt = ResumePrompt(
            resume_data=resume_data,
            user_prompt=user_prompt,
            generated_persona=None
        )

        # 4. 分步生成画像各部分
        logger.info("分步生成用户画像...")

        # 提取技能
        skill_extraction = await self.llm_client.generate_response(
            self.prompt_templates["skill_extraction"].format(
                resume_info=resume_info
            ),
            json_output=True
        )

        # 分析职业目标
        career_analysis = await self.llm_client.generate_response(
            self.prompt_templates["career_objective_analysis"].format(
                resume_info=resume_info,
                user_prompt=user_prompt
            ),
            json_output=True
        )

        # 识别约束条件
        constraints_analysis = await self.llm_client.generate_response(
            self.prompt_templates["constraints_identification"].format(
                resume_info=resume_info,
                user_prompt=user_prompt
            ),
            json_output=True
        )

        # 分析性格特质
        personality_analysis = await self.llm_client.generate_response(
            self.prompt_templates["personality_analysis"].format(
                resume_info=resume_info,
                user_prompt=user_prompt
            ),
            json_output=True
        )

        # 5. 综合生成完整画像
        logger.info("综合生成完整用户画像...")
        persona_response = await self.llm_client.generate_response(
            self.prompt_templates["persona_generation"].format(
                resume_info=resume_info,
                user_prompt=user_prompt
            ),
            json_output=True
        )

        # 6. 验证和整合结果
        validated_persona = self._validate_and_integrate_results(
            persona_response,
            skill_extraction,
            career_analysis,
            constraints_analysis,
            personality_analysis
        )

        # 7. 创建最终的用户画像对象
        user_persona = DynamicUserPersona(
            name=resume_data.name,
            email=resume_data.email,
            phone=resume_data.phone,
            technical_skills=validated_persona.get("technical_skills", []),
            soft_skills=SoftSkills(**validated_persona.get("soft_skills", {})),
            domain_knowledge=validated_persona.get("domain_knowledge", {}),
            career_objective=CareerObjective(**validated_persona.get("career_objective", {})),
            personality_traits=PersonalityTraits(**validated_persona.get("personality_traits", {})),
            constraints=CareerConstraints(**validatedPersona.get("constraints", {})),
            work_preferences=validated_persona.get("work_preferences", {}),
            motivators=validated_persona.get("motivators", []),
            deal_breakers=validated_persona.get("deal_breakers", []),
            strengths=validated_persona.get("strengths", []),
            weaknesses=validated_persona.get("weaknesses", []),
            ideal_work_environment=validated_persona.get("ideal_work_environment", []),
            confidence_score=validated_persona.get("confidence_score", 0.8),
            version="2.0"
        )

        # 更新简历提示的生成结果
        resume_prompt.generated_persona = user_persona

        logger.info(f"动态用户画像生成完成，置信度: {user_persona.confidence_score:.2f}")
        return user_persona

    def _format_resume_info(self, resume: ResumeSchema) -> str:
        """格式化简历信息为字符串"""
        info = []
        info.append(f"姓名: {resume.name}")
        info.append(f"邮箱: {resume.email}")
        info.append(f"电话: {resume.phone or '未提供'}")
        info.append(f"个人简介: {resume.summary}")

        # 工作经历
        if resume.work_experience:
            info.append("\n工作经历:")
            for work in resume.work_experience:
                info.append(f"- {work.company} - {work.position}")
                info.append(f"  时间: {work.start_date} 至 {work.end_date}")
                info.append(f"  描述: {work.description[:200]}...")
                if work.achievements:
                    info.append(f"  成就: {', '.join(work.achievements[:3])}")

        # 项目经验
        if resume.projects:
            info.append("\n项目经验:")
            for project in resume.projects[:3]:  # 只显示前3个项目
                info.append(f"- {project.name}")
                info.append(f"  描述: {project.description[:200]}...")
                info.append(f"  技术: {', '.join(project.technologies[:5])}")

        # 技能
        info.append(f"\n技能列表: {', '.join(resume.skills[:20])}")

        # 教育背景
        if resume.education:
            info.append("\n教育背景:")
            for edu in resume.education:
                info.append(f"- {edu.school} - {edu.major} ({edu.degree})")

        return "\n".join(info)

    def _validate_and_integrate_results(
        self,
        persona_response: Dict,
        skill_extraction: Dict,
        career_analysis: Dict,
        constraints_analysis: Dict,
        personality_analysis: Dict
    ) -> Dict:
        """验证和整合各个分析结果"""
        # 合并所有分析结果
        integrated = {
            "technical_skills": skill_extraction.get("technical_skills", {}),
            "soft_skills": skill_extraction.get("soft_skills", {}),
            "domain_knowledge": {},
            "career_objective": career_analysis,
            "personality_traits": personality_analysis,
            "constraints": constraints_analysis,
            "work_preferences": persona_response.get("work_preferences", {}),
            "motivators": persona_response.get("motivators", []),
            "deal_breakers": persona_response.get("deal_breakers", []),
            "strengths": persona_response.get("strengths", []),
            "weaknesses": persona_response.get("weaknesses", []),
            "ideal_work_environment": persona_response.get("ideal_work_environment", []),
            "confidence_score": persona_response.get("confidence_score", 0.8)
        }

        # 验证数据完整性
        self._validate_persona_data(integrated)

        return integrated

    def _validate_persona_data(self, persona_data: Dict):
        """验证用户画像数据"""
        required_fields = [
            "technical_skills", "soft_skills", "career_objective",
            "personality_traits", "constraints", "work_preferences",
            "motivators", "deal_breakers", "strengths", "weaknesses",
            "ideal_work_environment"
        ]

        for field in required_fields:
            if field not in persona_data or not persona_data[field]:
                logger.warning(f"用户画像中缺少必要字段: {field}")
                if field not in persona_data:
                    persona_data[field] = []
                elif not isinstance(persona_data[field], dict):
                    persona_data[field] = {}

    async def update_persona(
        self,
        existing_persona: DynamicUserPersona,
        new_resume_path: str = None,
        new_user_prompt: str = None
    ) -> DynamicUserPersona:
        """更新现有的用户画像"""
        logger.info("更新用户画像...")

        # 可以基于新的信息更新画像
        # 这里实现增量更新逻辑
        if new_resume_path and new_user_prompt:
            # 重新生成完整画像
            return await self.generate_persona(new_resume_path, new_user_prompt)

        # 否则返回原有画像
        return existing_persona


# 工具函数
async def create_dynamic_persona(
    resume_path: str,
    user_prompt: str,
    model: str = "gpt-4"
) -> DynamicUserPersona:
    """创建动态用户画像的快捷函数"""
    generator = DynamicUserPersonaGenerator(model=model)
    return await generator.generate_persona(resume_path, user_prompt, model)


# 测试函数
async def test_persona_generation():
    """测试用户画像生成"""
    print("=== 测试动态用户画像生成 ===")

    # 示例数据
    test_resume_path = "tests/data/sample_resume.pdf"
    test_user_prompt = """
    我是一名有5年经验的前端开发工程师，专注于React和Vue生态系统。
    我希望在上海寻找一个Senior Frontend Engineer的职位，薪资期望25-35K。
    我偏好技术驱动、注重产品质量的互联网公司，特别是有良好技术氛围的团队。
    我对管理岗位不感兴趣，希望专注于技术深耕。
    我能接受偶尔的加班，但希望有良好的工作生活平衡。
    """

    try:
        persona = await create_dynamic_persona(test_resume_path, test_user_prompt)
        print(f"\n✅ 用户画像生成成功！")
        print(f"姓名: {persona.name}")
        print(f"邮箱: {persona.email}")
        print(f"核心技能: {list(persona.technical_skills.keys())}")
        print(f"目标职位: {persona.career_objective.target_positions}")
        print(f"偏好行业: {persona.career_objective.preferred_industries}")
        print(f"置信度: {persona.confidence_score:.2f}")

        # 保存到文件
        from pathlib import Path
        output_path = Path("output/user_persona.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 转换为JSON可序列化的格式
        persona_dict = persona.model_dump()

        import json
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(persona_dict, f, ensure_ascii=False, indent=2, default=str)

        print(f"\n📁 用户画像已保存到: {output_path}")

    except Exception as e:
        print(f"❌ 测试失败: {e}")


if __name__ == "__main__":
    asyncio.run(test_persona_generation())