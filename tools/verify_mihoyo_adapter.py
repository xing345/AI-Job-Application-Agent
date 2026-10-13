"""验证米哈游适配器（第一页前3个岗位）。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.search.adapters.mihoyo import MihoyoAdapter
from src.search.site_registry import get_site_config


async def main():
    print("=== 米哈游适配器验证（第一页前3个）===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.mihoyo.com/#/campus/position", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(5000)

    config = get_site_config("mihoyo")
    adapter = MihoyoAdapter(config)
    # 只翻1页
    adapter.max_pages = 1
    adapter.max_jobs_hard_limit = 3

    jobs = await adapter.discover_jobs(page)

    print(f"\n=== 验证结果 ===")
    print(f"发现岗位数: {len(jobs)}")
    for i, job in enumerate(jobs):
        print(f"\n[{i+1}] {job.title}")
        print(f"    地点: {job.location}")
        print(f"    分类: {job.category_path}")
        print(f"    URL: {job.detail_url[:80]}")

    await close_browser()
    print("\n验证完成")


if __name__ == "__main__":
    asyncio.run(main())
