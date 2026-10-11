"""Step 1 验收脚本：验证 LLM 客户端 structured output。

调用 LLM 把自然语言简历转成 UserProfile JSON。
用法：python -m tools.verify_llm_client
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm import client as llm
from src.llm.prompts import text_to_profile_prompt
from src.models.profile import UserProfile


SAMPLE_RESUME = """
我叫张三，电话 13800138000，邮箱 zhangsan@example.com。
重庆移通学院软件工程专业本科，2022-2026 年在读。
技能：Python, JavaScript, Node.js, Playwright, LangGraph, FISCO BCOS, IPFS。
项目经历：基于 FISCO BCOS 和 IPFS 的分布式存储系统，负责后端开发和智能合约编写。
目标方向：AI Agent 开发、后端开发。目标城市：北京、深圳、成都。
可到岗时间：2026年7月。
"""


async def main():
    print("=" * 60)
    print("LLM 客户端验证：自然语言 → UserProfile JSON")
    print("=" * 60)
    print(f"模型: {llm.get_model_name()}")
    print()

    messages = text_to_profile_prompt(SAMPLE_RESUME)

    try:
        profile = await llm.chat_structured(messages, UserProfile, temperature=0.1)
        print("解析成功！")
        print()
        print(json.dumps(profile.model_dump(), ensure_ascii=False, indent=2))
        print()
        print(f"姓名: {profile.name}")
        print(f"电话: {profile.phone}")
        print(f"邮箱: {profile.email}")
        print(f"技能: {', '.join(profile.skills)}")
        print(f"目标方向: {', '.join(profile.target_directions)}")
        print(f"目标城市: {', '.join(profile.target_cities)}")
        print()
        print("生成的简历文本预览：")
        print(profile.to_resume_text()[:300])
        print()
        print("[PASS] LLM structured output 验证通过")
    except Exception as e:
        print(f"[FAIL] 验证失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
