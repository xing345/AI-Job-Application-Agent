"""验证 mouse.wheel 滚动效果。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.search.adapters.bytedance import BytedanceAdapter
from src.search.site_registry import get_site_config


async def main():
    print("=== mouse.wheel 滚动验证 ===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.bytedance.com/campus/position", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(5000)

    config = get_site_config("bytedance")
    adapter = BytedanceAdapter(config)

    card_sel = adapter.CARD_SELECTOR
    seen_urls = set()

    for i in range(20):
        cards = await page.query_selector_all(card_sel)
        new_count = 0
        for card in cards:
            href = await card.get_attribute("href")
            if href and href not in seen_urls:
                seen_urls.add(href)
                new_count += 1

        print(f"[滚动{i+1:2d}] 可见={len(cards):3d}, 新增={new_count:3d}, 累计唯一={len(seen_urls):4d}")

        # 使用 mouse.wheel 滚动
        await adapter._scroll_page(page)

    print(f"\n滚动20次后累计唯一岗位: {len(seen_urls)}")
    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
