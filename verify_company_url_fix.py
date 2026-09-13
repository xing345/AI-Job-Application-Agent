"""
修复验证脚本（可重复运行）：复现 2026-09-12 的输入，验证用户显式 URL 不再被丢弃。

阶段 A：只走候选发现（Tavily 联网，不起浏览器），打印候选顺序
阶段 B：真实公司通道（Playwright 浏览器），确认进入用户给的 URL 并抽取职位
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from src.models.instruction_schemas import TargetInstructionSchema
from src.search.browser_job_finder import BrowserJobFinder
from src.search.query_expander import expand_role_variants

KNOWN = [
    "哔哩哔哩",
    "https://jobs.bilibili.com/campus/positions?type=3",
    "京东",
    "https://campus.jd.com/home#/jobs?to=present&type=present",
]


def make_target():
    role = "AI应用开发工程师"
    return TargetInstructionSchema(
        company="", role=role, location="",
        keywords=["Python"],
        role_variants=expand_role_variants(role, ["Python"]),
    )


async def main():
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        print("ERROR: .env 中未配置 TAVILY_API_KEY")
        return
    finder = BrowserJobFinder(
        tavily_api_key=api_key,
        headless=False,       # 与 config.json 的生产配置一致
        interactive=False,    # 验证脚本不等待终端输入
        max_companies=5,
    )

    print("=" * 70)
    print("阶段 A：候选发现（不起浏览器）")
    print("=" * 70)
    candidates = await finder._discover_company_candidates(make_target(), KNOWN)
    for i, c in enumerate(candidates, 1):
        print(f"{i}. name={c.get('name')} | url={c.get('url')}")
        print(f"   career_url={c.get('career_url')} | trusted={c.get('trusted')}")

    print("=" * 70)
    print("阶段 B：真实公司通道（浏览器逐个进入招聘页）")
    print("=" * 70)
    jobs = await finder.discover_company_careers(make_target(), known_companies=KNOWN)
    print(f"公司通道共抽取 {len(jobs)} 个职位：")
    for j in jobs[:30]:
        print(f"- [{j.get('company')}] {j.get('title')} -> {j.get('url')}")


if __name__ == "__main__":
    asyncio.run(main())
