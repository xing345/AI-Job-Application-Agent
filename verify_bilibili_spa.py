# -*- coding: utf-8 -*-
"""真实验证：B站 SPA 校招列表能否被遍历、按 AI 方向筛出、并带回 JD。"""
import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.search.browser_job_finder import BrowserJobFinder
from src.models.instruction_schemas import TargetInstructionSchema
from src.search.query_expander import expand_role_variants, infer_direction

URL = "https://jobs.bilibili.com/campus/positions?type=3"


async def main():
    role = "AI应用开发工程师"
    d = infer_direction(role, ["Python", "PyTorch", "LangChain"])
    print("方向推断:", d["category"], d["label"], "词族", len(d["title_keywords"]), "个")
    ti = TargetInstructionSchema(
        company="哔哩哔哩", role=role,
        keywords=["Python", "PyTorch", "LangChain"],
        role_variants=expand_role_variants(role),
        direction_category=d["category"], direction_family=d["key"],
        title_keywords=d["title_keywords"],
    )
    finder = BrowserJobFinder(tavily_api_key="", headless=True, interactive=False)
    await finder._start_browser()
    try:
        jobs = await finder._extract_company_jobs("哔哩哔哩", URL, ti)
    finally:
        await finder._stop_browser()

    print(f"\n=== 最终抽取 {len(jobs)} 个 AI 相关职位 ===")
    for j in jobs:
        print(f"- {j['title']} | {j['location']} | 来源={j['source']} | "
              f"JD={len(j.get('description') or '')}字\n  {j['url']}")


asyncio.run(main())
