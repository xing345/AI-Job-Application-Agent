"""检查米哈游卡片的data属性和点击标题行为。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 米哈游卡片属性检查 ===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.mihoyo.com/#/campus/position", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(6000)

    cards = await page.query_selector_all("div[class*='jobItem']")
    print(f"卡片数量: {len(cards)}")

    if not cards:
        print("没有卡片！")
        await close_browser()
        return

    # 检查第一个卡片的所有属性
    first = cards[0]
    all_attrs = await first.evaluate("""el => {
        const attrs = {};
        for (const attr of el.attributes) {
            attrs[attr.name] = attr.value;
        }
        return attrs;
    }""")
    print(f"\n第一个卡片所有属性:")
    for k, v in all_attrs.items():
        print(f"  {k} = {v}")

    # 检查标题元素的属性
    title_el = await first.query_selector("span[class*='jobName']")
    if title_el:
        title_attrs = await title_el.evaluate("""el => {
            const attrs = {};
            for (const attr of el.attributes) {
                attrs[attr.name] = attr.value;
            }
            return attrs;
        }""")
        print(f"\n标题元素所有属性:")
        for k, v in title_attrs.items():
            print(f"  {k} = {v}")

    # 点击标题（而不是整个卡片）
    print(f"\n点击标题前URL: {page.url}")
    print("点击标题...")
    await title_el.click()
    await page.wait_for_timeout(3000)
    print(f"点击标题后URL: {page.url}")
    print(f"URL变化: {page.url != 'https://jobs.mihoyo.com/#/campus/position'}")

    # 检查是否有弹窗
    modal = await page.locator(".ant-modal, .ant-drawer, [role='dialog']").count()
    print(f"弹窗数量: {modal}")

    # 打印页面文本前40行
    print(f"\n页面文本前40行:")
    body = await page.locator("body").inner_text()
    for i, line in enumerate(body.split("\n")[:40]):
        if line.strip():
            print(f"  {i}: {line.strip()[:80]}")

    await close_browser()
    print("\n完成")


if __name__ == "__main__":
    asyncio.run(main())
