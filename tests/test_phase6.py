"""
Phase 6 测试脚本
测试动态用户画像生成功能
"""

import asyncio
import os
from pathlib import Path

# 添加项目根目录到路径
import sys
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.models.dynamic_persona_generator import DynamicUserPersonaGenerator
from src.utils.llm_client import get_llm_client


async def test_basic_llm_client():
    """测试基础LLM客户端"""
    print("\n=== 测试基础LLM客户端 ===")

    try:
        client = get_llm_client()

        # 简单测试
        response = await client.generate_response(
            "请用一句话介绍你自己",
            system_prompt="你是一个专业的职业顾问"
        )

        print(f"✅ LLM客户端测试成功: {response[:50]}...")

    except Exception as e:
        print(f"❌ LLM客户端测试失败: {e}")
        return False

    return True


async def test_persona_generation():
    """测试动态用户画像生成"""
    print("\n=== 测试动态用户画像生成 ===")

    try:
        # 创建一个模拟的简历文件
        sample_resume_path = project_root / "output" / "sample_resume.pdf"
        sample_resume_path.parent.mkdir(parents=True, exist_ok=True)

        # 创建一个简单的文本文件模拟简历
        with open(sample_resume_path, "w", encoding="utf-8") as f:
            f.write("""张三
zhangsan@email.com
13800138000

资深前端开发工程师，5年React和Vue开发经验，专注于Web应用开发和性能优化。

工作经历：
阿里巴巴 - 前端开发工程师 (2020-01 至 2023-06)
- 负责电商平台前端架构设计
- 使用React开发多个核心业务模块
- 优化页面性能，提升加载速度40%

腾讯 - 高级前端开发工程师 (2023-07 至 至今)
- 负责社交应用前端开发
- 使用Vue 3重构核心组件
- 带领3人前端小组完成项目交付

技能：
JavaScript, React, Vue, TypeScript, Node.js, Webpack, Docker, Git

项目经验：
电商平台前端重构
- 使用React和Redux重构整个电商前端
- 实现微前端架构
- 性能优化：首屏加载速度提升50%

社交应用开发
- 使用Vue 3开发社交应用前端
- 实现实时聊天功能
- 支持多端适配

教育背景：
清华大学 - 计算机科学与技术 - 本科 (2016-2020)""")

        # 用户描述
        user_prompt = """
        我是一名有5年经验的前端开发工程师，专注于React和Vue生态系统。
        我希望在上海寻找一个Senior Frontend Engineer的职位，薪资期望25-35K。
        我偏好技术驱动、注重产品质量的互联网公司，特别是有良好技术氛围的团队。
        我对管理岗位不感兴趣，希望专注于技术深耕。
        我能接受偶尔的加班，但希望有良好的工作生活平衡。
        """

        # 生成用户画像
        generator = DynamicUserPersonaGenerator()
        persona = await generator.generate_persona(
            str(sample_resume_path),
            user_prompt
        )

        print(f"✅ 用户画像生成成功！")
        print(f"   姓名: {persona.name}")
        print(f"   邮箱: {persona.email}")
        print(f"   核心技能: {list(persona.technical_skills.keys())}")
        print(f"   目标职位: {persona.career_objective.target_positions}")
        print(f"   偏好行业: {persona.career_objective.preferred_industries}")
        print(f"   置信度: {persona.confidence_score:.2f}")

        # 保存结果
        output_path = project_root / "output" / "user_persona.json"
        import json
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(persona.model_dump(), f, ensure_ascii=False, indent=2, default=str)

        print(f"📁 用户画像已保存到: {output_path}")

        return True

    except Exception as e:
        print(f"❌ 用户画像生成测试失败: {e}")
        return False


async def test_skill_extraction():
    """测试技能提取功能"""
    print("\n=== 测试技能提取功能 ===")

    try:
        client = get_llm_client()

        resume_info = """
        张三 - 资深前端开发工程师
        技能: JavaScript, React, Vue, TypeScript, Node.js, Webpack
        工作: 阿里巴巴、腾讯
        项目: 电商平台、社交应用
        """

        skill_extraction = await client.generate_response(
            client.prompt_templates["skill_extraction"].format(
                resume_info=resume_info
            ),
            json_output=True
        )

        print(f"✅ 技能提取成功！")
        print(f"   技术技能: {list(skill_extraction['technical_skills'].keys())}")
        print(f"   软技能: {list(skill_extraction['soft_skills'].keys())}")

        return True

    except Exception as e:
        print(f"❌ 技能提取测试失败: {e}")
        return False


async def main():
    """主测试函数"""
    print("🚀 开始 Phase 6 功能测试...")

    results = []

    # 测试1: 基础LLM客户端
    results.append(await test_basic_llm_client())

    # 测试2: 技能提取
    results.append(await test_skill_extraction())

    # 测试3: 动态用户画像生成
    results.append(await test_persona_generation())

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