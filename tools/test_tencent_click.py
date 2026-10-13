"""检查腾讯岗位卡片点击后的URL和详情页。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 腾讯岗位卡片点击测试 ===\n")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://join.qq.com/post.html", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(6000)

    # 获取前3个岗位卡片
    cards = await page.query_selector_all("li.post_box")
    print(f"岗位卡片数量: {len(cards)}")

    for i in range(min(3, len(cards))):
        card = cards[i]
        full_text = (await card.inner_text()).strip()
        lines = [l.strip() for l in full_text.split("\n") if l.strip()]
        title = lines[0] if lines else "N/A"
        print(f"\n--- 卡片 {i+1}: {title} ---")

        url_before = page.url
        print(f"点击前URL: {url_before}")

        # 点击卡片
        await card.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)
        await card.click()
        await page.wait_for_timeout(3000)

        url_after = page.url
        print(f"点击后URL: {url_after}")
        print(f"URL变化: {url_before != url_after}")
        print(f"页面标题: {await page.title()}")

        # 如果跳转了，检查详情页内容
        if url_before != url_after:
            body = await page.locator("body").inner_text()
            detail_lines = [l.strip() for l in body.split("\n") if l.strip()]
            print(f"详情页文本前20行:")
            for j, line in enumerate(detail_lines[:20]):
                print(f"  {j}: {line[:80]}")

            # 后退
            await page.go_back()
            await page.wait_for_timeout(2000)
            print(f"后退后URL: {page.url}")
        else:
            # 可能在新标签页打开
            print("URL没变化，检查是否有新标签页...")
            for ctx in browser._context.browser.contexts:
                for p in ctx.pages:
                    if p != page:
                        print(f"  新标签页: {p.url}")

    await close_browser()
    print("\n完成")


if __name__ == "__main__":
    asyncio.run(main())
