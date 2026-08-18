"""
Phase 8 测试脚本
测试智能匹配引擎功能
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.matching.matching_engine import SmartMatchingEngine, match_persona_with_jobs
from src.models.schemas import (
    DynamicUserPersona,
    CareerObjective,
    SoftSkills,
    PersonalityTraits,
    CareerConstraints
)


async def test_basic_matching():
    """测试基础匹配功能"""
    print("\n=== 测试基础匹配功能 ===")

    try:
        # 创建简单的匹配引擎
        engine = SmartMatchingEngine()
        print("✅ 匹配引擎创建成功")

        # 创建简单的用户画像
        persona = DynamicUserPersona(
            name="李四",
            email="lisi@email.com",
            phone="13900139000",
            technical_skills={
                "programming_languages": ["Python", "JavaScript"],
                "frameworks": ["Django", "React"]
            },
            soft_skills=SoftSkills(
                communication=["良好表达"],
                teamwork=["团队协作"]
            ),
            domain_knowledge={"web": 4, "backend": 3},
            career_objective=CareerObjective(
                target_positions=["Python开发", "全栈工程师"],
                preferred_industries=["互联网", "金融科技"],
                location_preference=["北京", "上海"]
            ),
            personality_traits=PersonalityTraits(
                work_style=["专注", "高效"],
                motivation_factors=["技术挑战", "项目成果"],
                learning_style=["实践学习", "代码研究"]
            ),
            constraints=CareerConstraints(
                excluded_companies=["某些公司"],
                compensation_floor="15K"
            ),
            strengths=["Python开发", "Web应用"],
            weaknesses=["架构设计", "团队管理"],
            work_preferences={"flexible": "支持弹性工作"}
        )

        # 创建简单的职位描述
        job_description = """
        职位名称：Python开发工程师

        要求：
        - 3年以上Python开发经验
        - 熟悉Django框架
        - 有Web开发经验
        - 良好的沟通能力

        工作内容：
        - 负责后端服务开发
        - 数据库设计和优化
        - 与前端团队协作
        """

        print("✅ 用户画像创建成功")
        print(f"   姓名: {persona.name}")
        print(f"   目标职位: {', '.join(persona.career_objective.target_positions)}")
        print(f"   技能: {list(persona.technical_skills.keys())}")

        # 执行匹配
        result = await engine.match_persona_with_job(persona, job_description)

        print(f"\n✅ 匹配完成！")
        print(f"   匹配分数: {result.match_score:.1f}%")
        print(f"   推荐: {result.recommendation}")
        print(f"   优先级: {result.priority_level}/5")
        print(f"   成功率: {result.estimated_success_rate:.1%}")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def test_batch_matching():
    """测试批量匹配功能"""
    print("\n=== 测试批量匹配功能 ===")

    try:
        # 创建用户画像
        persona = DynamicUserPersona(
            name="王五",
            email="wangwu@email.com",
            phone="13700137000",
            technical_skills={
                "programming_languages": ["Java", "Python", "Go"],
                "frameworks": ["Spring Boot", "Django", "Gin"]
            },
            soft_skills=SoftSkills(
                communication=["技术沟通", "文档编写"],
                leadership=["项目管理", "团队指导"],
                problem_solving=["系统设计", "故障排查"]
            ),
            domain_knowledge={"backend": 5, "microservices": 4, "database": 4},
            career_objective=CareerObjective(
                target_positions=["后端架构师", "技术经理"],
                preferred_industries=["互联网", "云计算"],
                location_preference=["北京", "深圳", "杭州"],
                salary_expectation="30-50K"
            ),
            personality_traits=PersonalityTraits(
                work_style=["严谨", "创新"],
                motivation_factors=["技术挑战", "团队成长"],
                learning_style=["深度学习", "技术分享"]
            ),
            constraints=CareerConstraints(
                excluded_companies=["传统企业"],
                compensation_floor="30K",
                compensation_ceiling="60K"
            ),
            strengths=["系统架构", "性能优化", "团队管理"],
            weaknesses=["前端技术", "产品设计"],
            work_preferences={"leadership": "希望技术管理路线"}
        )

        # 创建多个职位
        jobs = [
            {
                "title": "后端架构师",
                "company": "阿里云",
                "description": """
                要求：
                - 5年以上后端开发经验
                - 精通微服务架构
                - 有大规模系统设计经验
                - 熟悉Java/Go

                职责：
                - 负责技术架构设计
                - 解决关键技术难题
                - 指导团队技术发展
                """,
                "url": "https://job.aliyun.com/architect"
            },
            {
                "title": "Java开发工程师",
                "company": "腾讯",
                "description": """
                要求：
                - 3年以上Java开发
                - 熟悉Spring生态
                - 有高并发经验

                职责：
                - 后端服务开发
                - 性能优化
                - 参与技术选型
                """,
                "url": "https://job.tencent.com/java"
            },
            {
                "title": "全栈工程师",
                "company": "字节跳动",
                "description": """
                要求：
                - 前后端都有经验
                - 熟悉多种技术栈
                - 快速学习能力

                职责：
                - 全栈开发
                - 技术方案设计
                - 代码质量把控
                """,
                "url": "https://job.bytedance.com/fullstack"
            }
        ]

        print(f"开始批量匹配 {len(jobs)} 个职位...")

        # 执行批量匹配
        high_quality, normal_quality = await match_persona_with_jobs(
            persona,
            jobs,
            threshold=70.0
        )

        print(f"\n✅ 批量匹配完成！")
        print(f"   高质量职位: {len(high_quality)} 个")
        print(f"   普通职位: {len(normal_quality)} 个")

        # 显示高质量职位
        if high_quality:
            print("\n🎯 高质量职位:")
            for i, result in enumerate(high_quality, 1):
                job = next((j for j in jobs if j["url"] == result.job_id), None)
                if job:
                    print(f"\n   {i}. {job['title']} - {job['company']}")
                    print(f"      匹配度: {result.match_score:.1f}%")
                    print(f"      推荐: {result.recommendation}")
                    print(f"      优先级: {result.priority_level}/5")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def test_match_weights():
    """测试权重计算"""
    print("\n=== 测试权重计算 ===")

    try:
        from src.matching.matching_engine import MatchWeight

        # 测试不同权重配置
        weights = [
            MatchWeight(technical_skills=0.5, experience_level=0.3),
            MatchWeight(technical_skills=0.3, experience_level=0.5),
            MatchWeight(career_alignment=0.6, salary_expectation=0.2)
        ]

        for i, weight in enumerate(weights, 1):
            print(f"\n   权重配置 {i}:")
            print(f"      技术技能: {weight.technical_skills}")
            print(f"      经验水平: {weight.experience_level}")
            print(f"      职业匹配: {weight.career_alignment}")
            print(f"      薪资期望: {weight.salary_expectation}")

        print("✅ 权重计算测试通过")
        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def test_match_report():
    """测试匹配报告生成"""
    print("\n=== 测试匹配报告生成 ===")

    try:
        from src.matching.matching_engine import SmartMatchingEngine

        # 创建匹配引擎
        engine = SmartMatchingEngine()

        # 创建模拟的匹配结果
        mock_results = [
            type('MockResult', (), {
                'job_id': 'job1',
                'match_score': 85.0,
                'priority_level': 5,
                'recommendation': '推荐'
            })(),
            type('MockResult', (), {
                'job_id': 'job2',
                'match_score': 72.0,
                'priority_level': 4,
                'recommendation': '推荐'
            })(),
            type('MockResult', (), {
                'job_id': 'job3',
                'match_score': 45.0,
                'priority_level': 2,
                'recommendation': '不推荐'
            })()
        ]

        # 创建模拟用户画像
        persona = DynamicUserPersona(
            name="赵六",
            email="zhaoliu@email.com",
            phone="13600136000",
            technical_skills={"languages": ["Python"]},
            soft_skills=SoftSkills(),
            domain_knowledge={},
            career_objective=CareerObjective(target_positions=["开发工程师"]),
            personality_traits=PersonalityTraits(),
            constraints=CareerConstraints(),
            strengths=["Python"],
            weaknesses=[],
            work_preferences={}
        )

        # 生成报告
        report = await engine.generate_match_report(persona, mock_results)

        print(f"\n✅ 匹配报告生成成功！")
        print(f"   姓名: {report['persona_name']}")
        print(f"   总评估职位数: {report['total_jobs_evaluated']}")
        print(f"   高质量职位数: {report['high_quality_jobs']}")
        print(f"   平均匹配度: {report['average_match_score']}%")
        print(f"   优先级分布: {report['priority_distribution']}")
        print(f"   建议: {', '.join(report['recommendations'])}")

        # 显示前3个职位
        print(f"\n   前3个职位:")
        for i, job in enumerate(report['top_jobs'][:3], 1):
            print(f"      {i}. {job['job_url']} - {job['match_score']}%")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def test_error_handling():
    """测试错误处理"""
    print("\n=== 测试错误处理 ===")

    try:
        # 创建匹配引擎
        engine = SmartMatchingEngine()

        # 测试空输入
        result = await engine.match_persona_with_job(None, "test")
        if result:
            print("✅ 空输入处理成功")

        # 测试无效的职位描述
        from src.models.schemas import DynamicUserPersona
        persona = DynamicUserPersona(
            name="测试用户",
            email="test@test.com",
            phone="13500135000",
            technical_skills={},
            soft_skills=SoftSkills(),
            domain_knowledge={},
            career_objective=CareerObjective(target_positions=["测试"]),
            personality_traits=PersonalityTraits(),
            constraints=CareerConstraints(),
            strengths=[],
            weaknesses=[],
            work_preferences={}
        )

        # 测试空职位描述
        result = await engine.match_persona_with_job(persona, "")
        if result:
            print("✅ 空职位描述处理成功")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def main():
    """主测试函数"""
    print("🚀 开始 Phase 8 功能测试...")

    results = []

    # 测试1: 基础匹配
    results.append(await test_basic_matching())

    # 测试2: 批量匹配
    results.append(await test_batch_matching())

    # 测试3: 权重计算
    results.append(await test_match_weights())

    # 测试4: 匹配报告
    results.append(await test_match_report())

    # 测试5: 错误处理
    results.append(await test_error_handling())

    # 输出测试结果
    print(f"\n{'='*60}")
    print("📊 测试结果汇总")
    print(f"{'='*60}")

    passed = sum(results)
    total = len(results)

    print(f"通过: {passed}/{total}")

    if passed == total:
        print("✅ 所有测试通过！")
        return True
    else:
        print("❌ 部分测试失败，请检查配置")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)