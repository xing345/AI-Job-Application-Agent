"""
智能匹配引擎 (LLM-as-a-Judge)
基于DynamicUserPersona和职位描述进行智能匹配评估
"""

import asyncio
import json
import re
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from loguru import logger
from dataclasses import dataclass
from pathlib import Path

# 添加项目根目录到路径
import sys
import os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.utils.llm_client import get_llm_client
from src.models.schemas import DynamicUserPersona, MatchAnalysisResult
from src.browser.browser_agent import BrowserAgent


@dataclass
class MatchWeight:
    """匹配权重配置"""
    technical_skills: float = 0.4
    experience_level: float = 0.3
    career_alignment: float = 0.2
    salary_expectation: float = 0.1
    location_preference: float = 0.05
    company_culture: float = 0.05


class SmartMatchingEngine:
    """智能匹配引擎"""

    def __init__(self, model: str = "gpt-4-turbo-preview"):
        self.llm_client = get_llm_client()
        self.match_weights = MatchWeight()
        self.threshold_score = 70.0  # 匹配阈值
        self.cache = {}  # 简单的缓存机制

    async def match_persona_with_job(
        self,
        persona: DynamicUserPersona,
        job_description: str,
        job_url: str = None
    ) -> MatchAnalysisResult:
        """
        将用户画像与单个职位进行匹配

        Args:
            persona: 用户画像
            job_description: 职位描述
            job_url: 职位URL（可选）

        Returns:
            匹配分析结果
        """
        logger.info(f"开始匹配评估: {persona.name} vs 职位")

        # 生成匹配分析
        analysis_prompt = self._build_analysis_prompt(persona, job_description)

        try:
            response = await self.llm_client.generate_response(
                analysis_prompt,
                json_output=True
            )

            # 验证和整合结果
            validated_result = self._validate_match_result(response, persona, job_url)

            # 生成推荐
            validated_result.recommendation = self._generate_recommendation(validated_result)
            validated_result.priority_level = self._calculate_priority(validated_result)
            validated_result.estimated_success_rate = self._estimate_success_rate(validated_result)

            return validated_result

        except Exception as e:
            logger.error(f"匹配评估失败: {e}")
            # 返回默认结果
            return MatchAnalysisResult(
                job_id=job_url or "unknown",
                match_score=0.0,
                strengths_match=[],
                weaknesses_mismatch=["评估过程中出现错误"],
                cultural_fit_analysis="无法评估",
                growth_potential="无法评估",
                compensation_evaluation="无法评估",
                recommendation="无法评估",
                priority_level=0,
                estimated_success_rate=0.0,
                analyzed_at=datetime.now()
            )

    def _build_analysis_prompt(
        self,
        persona: DynamicUserPersona,
        job_description: str
    ) -> str:
        """构建分析提示"""
        prompt = f"""
        你是一位专业的职业顾问和人才匹配专家。请全面评估以下用户画像与职位的匹配程度。

        === 用户画像 ===
        姓名: {persona.name}
        邮箱: {persona.email}

        技术技能:
        {self._format_skills(persona.technical_skills)}

        软技能:
        - 沟通能力: {', '.join(persona.soft_skills.communication or [])}
        - 领导力: {', '.join(persona.soft_skills.leadership or [])}
        - 团队协作: {', '.join(persona.soft_skills.teamwork or [])}
        - 问题解决: {', '.join(persona.soft_skills.problem_solving or [])}
        - 创新思维: {', '.join(persona.soft_skills.creativity or [])}
        - 适应能力: {', '.join(persona.soft_skills.adaptability or [])}

        职业目标:
        - 目标职位: {', '.join(persona.career_objective.target_positions)}
        - 偏好行业: {', '.join(persona.career_objective.preferred_industries)}
        - 地点偏好: {', '.join(persona.career_objective.location_preference)}
        - 薪资期望: {persona.career_objective.salary_expectation or '面议'}

        性格特质:
        - 工作风格: {', '.join(persona.personality_traits.work_style)}
        - 激励因素: {', '.join(persona.personality_traits.motivation_factors)}
        - 学习方式: {', '.join(persona.personality_traits.learning_style)}

        约束条件:
        - 排除公司: {', '.join(persona.constraints.excluded_companies)}
        - 排除行业: {', '.join(persona.constraints.excluded_industries)}
        - 薪资底线: {persona.constraints.compensation_floor or '无'}
        - 薪资上限: {persona.constraints.compensation_ceiling or '无'}

        核心优势: {', '.join(persona.strengths)}
        待改进领域: {', '.join(persona.weaknesses)}

        === 职位描述 ===
        {job_description}

        === 匹配评估要求 ===

        请从以下维度进行详细评估，并给出0-100分的匹配分数：

        1. **技能匹配度 (权重40%)**
           - 技术技能是否匹配职位要求
           - 是否具备必要的技术栈
           - 技能等级是否足够

        2. **经验匹配度 (权重30%)**
           - 工作年限是否符合要求
           - 相关项目经验是否丰富
           - 行业经验是否匹配

        3. **职业目标匹配度 (权重20%)**
           - 职位是否符合职业发展方向
           - 公司是否在偏好行业
           - 是否提供成长空间

        4. **薪资期望匹配度 (权重10%)**
           - 薪资要求是否在合理范围内
           - 是否与市场水平相符

        5. **地点偏好匹配度 (权重5%)**
           - 工作地点是否接受
           - 是否考虑远程工作

        6. **公司文化匹配度 (权重5%)**
           - 工作风格是否契合
           - 激励因素是否匹配

        输出严格的JSON格式：
        {{
            "match_score": 0-100,
            "strengths_match": ["匹配点1", "匹配点2"],
            "weaknesses_mismatch": ["不匹配点1", "不匹配点2"],
            "cultural_fit_analysis": "文化匹配分析",
            "growth_potential": "成长潜力评估",
            "compensation_evaluation": "薪资评估",
            "recommendation": "推荐/考虑/不推荐",
            "priority_level": 1-5,
            "estimated_success_rate": 0-1
        }}

        分析请基于专业判断，确保客观公正。
        """

        return prompt

    def _format_skills(self, technical_skills: Dict) -> str:
        """格式化技能信息"""
        formatted = []
        for category, skills in technical_skills.items():
            if skills:
                formatted.append(f"{category}: {', '.join(skills)}")
        return "\n".join(formatted)

    def _validate_match_result(
        self,
        result: Dict,
        persona: DynamicUserPersona,
        job_url: str = None
    ) -> MatchAnalysisResult:
        """验证和整合匹配结果"""
        # 确保必要字段存在
        if "match_score" not in result:
            result["match_score"] = 0

        # 计算加权分数
        weighted_score = self._calculate_weighted_score(result, persona)
        result["match_score"] = weighted_score

        # 创建匹配结果对象
        return MatchAnalysisResult(
            job_id=job_url or "unknown",
            match_score=result["match_score"],
            strengths_match=result.get("strengths_match", []),
            weaknesses_mismatch=result.get("weaknesses_mismatch", []),
            cultural_fit_analysis=result.get("cultural_fit_analysis", "无法评估"),
            growth_potential=result.get("growth_potential", "无法评估"),
            compensation_evaluation=result.get("compensation_evaluation", "无法评估"),
            recommendation=result.get("recommendation", "考虑"),
            priority_level=result.get("priority_level", 3),
            estimated_success_rate=result.get("estimated_success_rate", 0.5),
            analyzed_at=datetime.now()
        )

    def _calculate_weighted_score(self, result: Dict, persona: DynamicUserPersona) -> float:
        """计算加权分数"""
        base_score = result.get("match_score", 0)

        # 根据约束条件调整分数
        adjusted_score = base_score

        # 检查排除条件
        if persona.constraints.excluded_companies:
            adjusted_score *= 0.8

        if persona.constraints.excluded_industries:
            adjusted_score *= 0.8

        # 检查薪资期望
        if persona.constraints.compensation_floor or persona.constraints.compensation_ceiling:
            adjusted_score *= 0.9

        # 确保分数在0-100之间
        return max(0, min(100, adjusted_score))

    def _generate_recommendation(self, result: MatchAnalysisResult) -> str:
        """生成推荐意见"""
        if result.match_score >= 85:
            return "强烈推荐"
        elif result.match_score >= 75:
            return "推荐"
        elif result.match_score >= 60:
            return "考虑"
        else:
            return "不推荐"

    def _calculate_priority(self, result: MatchAnalysisResult) -> int:
        """计算优先级"""
        if result.match_score >= 85:
            return 5
        elif result.match_score >= 75:
            return 4
        elif result.match_score >= 65:
            return 3
        elif result.match_score >= 50:
            return 2
        else:
            return 1

    def _estimate_success_rate(self, result: MatchAnalysisResult) -> float:
        """估计成功率"""
        # 基于匹配分数和优先级计算
        base_rate = result.match_score / 100
        priority_bonus = result.priority_level / 5
        return min(1.0, base_rate * priority_bonus)

    async def batch_match_jobs(
        self,
        persona: DynamicUserPersona,
        jobs: List[Dict],
        max_concurrent: int = 5
    ) -> List[MatchAnalysisResult]:
        """
        批量匹配职位

        Args:
            persona: 用户画像
            jobs: 职位列表
            max_concurrent: 最大并发数

        Returns:
            匹配结果列表
        """
        logger.info(f"开始批量匹配 {len(jobs)} 个职位")

        results = []
        semaphore = asyncio.Semaphore(max_concurrent)

        async def match_single_job(job: Dict) -> MatchAnalysisResult:
            async with semaphore:
                try:
                    job_desc = job.get("description", "")
                    job_url = job.get("url")

                    result = await self.match_persona_with_job(
                        persona,
                        job_desc,
                        job_url
                    )

                    # 添加职位信息
                    result.job_id = job.get("url", f"job_{id(job)}")
                    results.append(result)

                    logger.info(f"匹配完成: {job.get('title', '未知职位')} - {result.match_score:.1f}%")
                    return result

                except Exception as e:
                    logger.error(f"匹配失败: {job.get('title', '未知职位')} - {e}")
                    # 返回失败结果
                    return MatchAnalysisResult(
                        job_id=job.get("url", f"job_{id(job)}"),
                        match_score=0.0,
                        strengths_match=[],
                        weaknesses_mismatch=["评估过程中出现错误"],
                        cultural_fit_analysis="无法评估",
                        growth_potential="无法评估",
                        compensation_evaluation="无法评估",
                        recommendation="无法评估",
                        priority_level=0,
                        estimated_success_rate=0.0,
                        analyzed_at=datetime.now()
                    )

        # 创建并发任务
        tasks = [match_single_job(job) for job in jobs]

        # 等待所有任务完成
        await asyncio.gather(*tasks)

        logger.info(f"批量匹配完成，共处理 {len(results)} 个职位")
        return results

    async def filter_high_quality_jobs(
        self,
        persona: DynamicUserPersona,
        jobs: List[Dict],
        threshold: float = 70.0
    ) -> Tuple[List[MatchAnalysisResult], List[MatchAnalysisResult]]:
        """
        过滤高质量职位

        Args:
            persona: 用户画像
            jobs: 职位列表
            threshold: 匹配阈值

        Returns:
            (高质量职位, 普通职位)
        """
        # 执行批量匹配
        all_results = await self.batch_match_jobs(persona, jobs)

        # 分离高质量和普通职位
        high_quality = [r for r in all_results if r.match_score >= threshold]
        normal_quality = [r for r in all_results if r.match_score < threshold]

        # 按分数排序
        high_quality.sort(key=lambda x: x.match_score, reverse=True)
        normal_quality.sort(key=lambda x: x.match_score, reverse=True)

        logger.info(f"过滤结果: 高质量 {len(high_quality)} 个, 普通 {len(normal_quality)} 个")

        return high_quality, normal_quality

    async def generate_match_report(
        self,
        persona: DynamicUserPersona,
        match_results: List[MatchAnalysisResult]
    ) -> Dict:
        """
        生成匹配报告

        Args:
            persona: 用户画像
            match_results: 匹配结果列表

        Returns:
            匹配报告
        """
        if not match_results:
            return {"error": "没有匹配结果"}

        # 统计信息
        total_jobs = len(match_results)
        high_quality_count = sum(1 for r in match_results if r.match_score >= 70)
        avg_score = sum(r.match_score for r in match_results) / total_jobs

        # 按优先级分组
        by_priority = {i: [] for i in range(1, 6)}
        for result in match_results:
            by_priority[result.priority_level].append(result)

        # 生成建议
        recommendations = []
        if high_quality_count > 0:
            recommendations.append(f"建议优先申请 {high_quality_count} 个高质量职位")

        if avg_score < 50:
            recommendations.append("整体匹配度较低，建议调整求职策略")

        # 保存报告
        report = {
            "persona_name": persona.name,
            "total_jobs_evaluated": total_jobs,
            "high_quality_jobs": high_quality_count,
            "average_match_score": round(avg_score, 1),
            "priority_distribution": {
                str(p): len(jobs) for p, jobs in by_priority.items()
            },
            "recommendations": recommendations,
            "top_jobs": [
                {
                    "job_url": r.job_id,
                    "match_score": r.match_score,
                    "priority": r.priority_level,
                    "recommendation": r.recommendation
                }
                for r in sorted(match_results, key=lambda x: x.match_score, reverse=True)[:10]
            ],
            "generated_at": datetime.now().isoformat()
        }

        # 保存到文件
        output_path = Path(project_root) / "output" / f"match_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"匹配报告已保存到: {output_path}")
        return report


# 工具函数
async def create_matcher(model: str = "gpt-4-turbo-preview") -> SmartMatchingEngine:
    """创建匹配引擎实例"""
    return SmartMatchingEngine(model=model)


async def match_persona_with_jobs(
    persona: DynamicUserPersona,
    jobs: List[Dict],
    threshold: float = 70.0,
    model: str = "gpt-4-turbo-preview"
) -> Tuple[List[MatchAnalysisResult], List[MatchAnalysisResult]]:
    """
    用户画像与职位匹配的快捷函数

    Args:
        persona: 用户画像
        jobs: 职位列表
        threshold: 匹配阈值
        model: 使用的模型

    Returns:
        (高质量职位, 普通职位)
    """
    matcher = SmartMatchingEngine(model=model)
    return await matcher.filter_high_quality_jobs(persona, jobs, threshold)


# 测试函数
async def test_smart_matching():
    """测试智能匹配引擎"""
    print("=== 测试智能匹配引擎 ===")

    try:
        # 创建模拟的用户画像
        from src.models.schemas import DynamicUserPersona, CareerObjective, SoftSkills, PersonalityTraits, CareerConstraints

        persona = DynamicUserPersona(
            name="张三",
            email="zhangsan@email.com",
            phone="13800138000",
            technical_skills={
                "programming_languages": ["JavaScript", "TypeScript", "Python"],
                "frameworks": ["React", "Vue", "Node.js"],
                "tools": ["Git", "Docker", "Webpack"],
                "databases": ["MySQL", "MongoDB"]
            },
            soft_skills=SoftSkills(
                communication=["清晰表达", "文档编写"],
                teamwork=["团队协作", "代码审查"],
                problem_solving=["问题分析", "解决方案设计"]
            ),
            domain_knowledge={
                "web_development": 5,
                "frontend": 4,
                "backend": 3
            },
            career_objective=CareerObjective(
                target_positions=["前端开发工程师", "全栈工程师"],
                preferred_industries=["互联网", "科技"],
                location_preference=["北京", "上海", "杭州"],
                salary_expectation="20-35K"
            ),
            personality_traits=PersonalityTraits(
                work_style=["专注", "高效"],
                motivation_factors=["技术挑战", "团队成长"],
                learning_style=["实践学习", "项目驱动"]
            ),
            constraints=CareerConstraints(
                excluded_companies=["某些特定公司"],
                compensation_floor="20K",
                compensation_ceiling="40K"
            ),
            strengths=["React开发", "性能优化", "团队协作"],
            weaknesses=["管理经验", "架构设计"],
            work_preferences={"remote": "支持远程"}
        )

        # 创建模拟的职位列表
        mock_jobs = [
            {
                "title": "高级前端开发工程师",
                "company": "阿里巴巴",
                "description": """
                职位要求：
                - 5年以上前端开发经验
                - 精通React、Vue等主流框架
                - 熟悉TypeScript
                - 有大型项目经验
                - 良好的团队协作能力

                职位描述：
                负责电商平台前端架构设计和开发，与后端团队紧密合作。
                """,
                "url": "https://job.alibaba.com/frontend",
                "location": "杭州"
            },
            {
                "title": "Java开发工程师",
                "company": "腾讯",
                "description": """
                职位要求：
                - 3年以上Java开发经验
                - 熟悉Spring Boot
                - 有微服务架构经验
                - 数据库设计能力

                职位描述：
                负责后端服务开发和维护。
                """,
                "url": "https://job.tencent.com/java",
                "location": "深圳"
            },
            {
                "title": "前端开发工程师",
                "company": "字节跳动",
                "description": """
                职位要求：
                - 2年以上前端开发经验
                - 熟悉JavaScript、HTML、CSS
                - 有React经验优先
                - 良好的学习能力和沟通能力

                职位描述：
                参与社交产品前端开发，快速迭代。
                """,
                "url": "https://job.bytedance.com/frontend",
                "location": "北京"
            }
        ]

        print(f"开始匹配 {persona.name} 的简历与 {len(mock_jobs)} 个职位...")

        # 执行匹配
        high_quality, normal_quality = await match_persona_with_jobs(
            persona,
            mock_jobs,
            threshold=70.0
        )

        # 输出结果
        print(f"\n{'='*60}")
        print("🎯 匹配结果")
        print(f"{'='*60}")

        if high_quality:
            print(f"\n✅ 高质量职位 ({len(high_quality)} 个):")
            for i, result in enumerate(high_quality, 1):
                job_title = next((j["title"] for j in mock_jobs if j["url"] == result.job_id), "未知职位")
                print(f"\n   {i}. {job_title}")
                print(f"      匹配度: {result.match_score:.1f}%")
                print(f"      优先级: {result.priority_level}/5")
                print(f"      推荐: {result.recommendation}")
                print(f"      成功率: {result.estimated_success_rate:.1%}")
        else:
            print("\n❌ 未找到高质量职位")

        if normal_quality:
            print(f"\n📊 普通职位 ({len(normal_quality)} 个):")
            for i, result in enumerate(normal_quality[:3], 1):
                job_title = next((j["title"] for j in mock_jobs if j["url"] == result.job_id), "未知职位")
                print(f"\n   {i}. {job_title}")
                print(f"      匹配度: {result.match_score:.1f}%")

        # 生成报告
        all_results = high_quality + normal_quality
        report = await create_matcher().generate_match_report(persona, all_results)

        print(f"\n📋 匹配报告已生成")
        print(f"   总评估职位数: {report['total_jobs_evaluated']}")
        print(f"   高质量职位数: {report['high_quality_jobs']}")
        print(f"   平均匹配度: {report['average_match_score']}%")
        print(f"   建议: {', '.join(report['recommendations'])}")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(test_smart_matching())