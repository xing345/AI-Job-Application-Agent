"""直接访问米哈游详情页，检查结构。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 米哈游详情页检查 ===")
    browser = await get_browser()
    page = browser.page

    # 直接访问清单中的岗位详情页
    url = "https://jobs.mihoyo.com/#/campus/position/8925"
    print(f"访问: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(5000)

    print(f"页面标题: {await page.title()}")
    print(f"当前URL: {page.url}")

    # 检查是否重定向到列表页
    if "position/8925" not in page.url:
        print("⚠️ 被重定向了，详情页可能不存在或需要登录")
    else:
        print("✅ 成功进入详情页")

    # 打印页面文本
    print(f"\n页面文本前60行:")
    body = await page.locator("body").inner_text()
    for i, line in enumerate(body.split("\n")[:60]):
        if line.strip():
            print(f"  {i}: {line.strip()[:80]}")

    # 检查是否有登录提示
    if "登录" in body or "login" in body.lower():
        print("\n⚠️ 页面包含登录提示，可能需要登录才能查看详情")

    await close_browser()
    print("\n完成")


if __name__ == "__main__":
    asyncio.run(main())
