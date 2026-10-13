"""验证字节跳动分页模式：翻5页，统计岗位数量。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.search.adapters.bytedance import BytedanceAdapter
from src.search.site_registry import get_site_config


async def main():
    print("=== 字节跳动分页模式验证（5页）===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.bytedance.com/campus/position", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(5000)

    config = get_site_config("bytedance")
    adapter = BytedanceAdapter(config)
    # 限制只翻5页用于验证
    adapter.max_pages = 5
    adapter.max_jobs_hard_limit = 100

    jobs = await adapter.discover_jobs(page)

    print(f"\n=== 验证结果 ===")
    print(f"发现岗位总数: {len(jobs)}")
    print(f"平均每页: {len(jobs) / 5:.1f} 个")
    print(f"\n前15个岗位:")
    for i, job in enumerate(jobs[:15]):
        print(f"  [{i+1:2d}] {job.title[:50]}")
        print(f"        地点: {job.location}, 公司: {job.company}")

    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
