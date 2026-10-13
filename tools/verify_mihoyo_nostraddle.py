"""验证米哈游连续抓取（走真实 fetch_single_jd 路径），确认不再串岗。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.agent.nodes.fetch_jd import fetch_single_jd


async def main():
    browser = await get_browser()
    page = browser.page

    test_jobs = [
        ("8337", "游戏AI研发实习生（Agent方向）"),
        ("8925", "基础研究-游戏AI研发工程师（Agent方向）"),
        ("8919", "基础研究-Agent 算法研究员"),
        ("9560", "平台研发-Agent开发工程师"),
    ]

    for job_id, title in test_jobs:
        url = f"https://jobs.mihoyo.com/#/campus/position/{job_id}"
        detail = await fetch_single_jd(page, url, "mihoyo", title)
        if detail:
            got = detail.posting.title
            consistent = got == title or title in got or got in title
            print(f"[OK] 期望='{title}'")
            print(f"     实际='{got}' 一致={consistent}")
            print(f"     职责={len(detail.responsibilities)} 要求={len(detail.requirements)} 全文={len(detail.full_jd)}")
        else:
            print(f"[FAIL] {title} 提取失败")
        print()

    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
