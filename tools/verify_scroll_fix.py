"""验证字节跳动滚动修复效果：测试滚动后岗位数量增长。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.search.adapters.bytedance import BytedanceAdapter
from src.search.site_registry import get_site_config


async def main():
    print("=== 字节跳动滚动修复验证 ===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.bytedance.com/campus/position", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(4000)

    config = get_site_config("bytedance")
    adapter = BytedanceAdapter(config)

    card_selector = adapter.CARD_SELECTOR
    seen_urls = set()
    all_jobs = []

    # 测试滚动30次
    max_scrolls = 30
    for i in range(max_scrolls):
        # 提取当前卡片
        cards = await page.query_selector_all(card_selector)
        new_count = 0
        for card in cards:
            try:
                href = await card.get_attribute("href")
                if href and href not in seen_urls:
                    seen_urls.add(href)
                    all_jobs.append(href)
                    new_count += 1
            except Exception:
                pass

        total_visible = len(cards)
        print(f"[滚动{i+1:2d}] 可见卡片={total_visible:3d}, 新增={new_count:3d}, 累计唯一={len(all_jobs):4d}")

        # 滚动
        await adapter._scroll_page(page)

    # 最终统计
    print(f"\n=== 验证结果 ===")
    print(f"滚动 {max_scrolls} 次后，累计唯一岗位 URL: {len(all_jobs)}")
    print(f"平均每次滚动新增: {len(all_jobs) / max_scrolls:.1f} 个")
    print(f"预计加载全部7000+岗位需要滚动约: {int(7000 / (len(all_jobs) / max_scrolls))} 次")
    print(f"\n前10个岗位URL:")
    for url in all_jobs[:10]:
        print(f"  {url}")

    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
