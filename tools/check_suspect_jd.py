"""检查可疑岗位的JD提取内容。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.search.adapters.mihoyo import MihoyoAdapter
from src.search.site_registry import get_site_config
from src.models.job import JobPosting

# 可疑岗位URL
SUSPECT_JOBS = [
    ("平台研发-推荐算法工程师", "https://jobs.mihoyo.com/#/campus/position/9119"),
    ("大模型-LLM预训练数据算法研究员", "https://jobs.mihoyo.com/#/campus/position/8935"),
    ("国际化生态平台（日本)-崩坏IP", "https://jobs.mihoyo.com/#/campus/position/9368"),
    ("3D生成算法研究员实习生", "https://jobs.mihoyo.com/#/campus/position/5287"),
]

async def main():
    print("=== 检查可疑岗位JD提取 ===\n")
    browser = await get_browser()
    page = browser.page

    config = get_site_config("mihoyo")
    adapter = MihoyoAdapter(config)

    for title, url in SUSPECT_JOBS:
        print(f"{'='*60}")
        print(f"岗位: {title}")
        print(f"URL: {url}")

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)

        posting = JobPosting(title=title, detail_url=url, company="米哈游", site_name="mihoyo")
        detail = await adapter.extract_jd_detail(page, posting)

        if detail:
            print(f"JD长度: {len(detail.full_jd)}")
            print(f"职责长度: {len(detail.responsibilities)}")
            print(f"要求长度: {len(detail.requirements)}")
            print(f"\nJD全文前500字符:")
            print(detail.full_jd[:500])
            print(f"\n... 后200字符:")
            print(detail.full_jd[-200:])
        else:
            print("❌ JD提取失败")

        print()

    await close_browser()
    print("完成")

if __name__ == "__main__":
    asyncio.run(main())
