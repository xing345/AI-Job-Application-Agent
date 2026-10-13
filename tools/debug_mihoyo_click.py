"""调试米哈游卡片点击行为。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 米哈游卡片点击调试 ===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.mihoyo.com/#/campus/position", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(5000)

    # 检查卡片数量
    cards = await page.query_selector_all("div[class*='jobItem']")
    print(f"卡片数量: {len(cards)}")

    if not cards:
        print("没有找到卡片！")
        await close_browser()
        return

    # 检查第一个卡片的onclick属性
    first_card = cards[0]
    onclick = await first_card.get_attribute("onclick")
    print(f"第一个卡片 onclick: {onclick}")

    # 检查卡片的所有属性
    attrs = await first_card.evaluate("el => Object.assign({}, el.attributes)")
    print(f"第一个卡片属性: {attrs}")

    # 提取标题
    title_el = await first_card.query_selector("span[class*='jobName']")
    title = (await title_el.inner_text()).strip() if title_el else "N/A"
    print(f"第一个卡片标题: {title}")

    # 记录点击前URL
    url_before = page.url
    print(f"点击前URL: {url_before}")

    # 点击第一个卡片
    print("\n点击第一个卡片...")
    await first_card.scroll_into_view_if_needed()
    await page.wait_for_timeout(500)
    await first_card.click()
    await page.wait_for_timeout(3000)

    # 检查点击后URL
    url_after = page.url
    print(f"点击后URL: {url_after}")
    print(f"URL变化: {url_before != url_after}")

    # 检查页面标题
    print(f"页面标题: {await page.title()}")

    # 检查是否打开了新标签页
    contexts = browser.browser.contexts
    for i, ctx in enumerate(contexts):
        pages = ctx.pages
        print(f"Context {i}: {len(pages)} 个页面")
        for j, p in enumerate(pages):
            print(f"  页面 {j}: {p.url[:80]}")

    # 检查页面内容
    body_text = await page.locator("body").inner_text()
    print(f"\n页面文本前30行:")
    for i, line in enumerate(body_text.split("\n")[:30]):
        if line.strip():
            print(f"  {i}: {line.strip()[:80]}")

    # 尝试后退
    print("\n尝试后退...")
    try:
        await page.go_back()
        await page.wait_for_timeout(2000)
        print(f"后退后URL: {page.url}")
        cards_after = await page.query_selector_all("div[class*='jobItem']")
        print(f"后退后卡片数量: {len(cards_after)}")
    except Exception as e:
        print(f"后退失败: {e}")

    await close_browser()
    print("\n调试完成")


if __name__ == "__main__":
    asyncio.run(main())
