"""阶段5环境验证脚本：浏览器启动 + 字节跳动页面访问 + 岗位卡片提取。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def test():
    print("=== 阶段5环境验证 ===")

    # 1. 启动浏览器
    browser = await get_browser()
    page = browser.page
    print(f"[1] Browser launched OK")

    # 2. 访问字节跳动校招页
    try:
        await page.goto(
            "https://jobs.bytedance.com/campus/position",
            wait_until="domcontentloaded",
            timeout=20000,
        )
        await page.wait_for_timeout(4000)  # 等待 SPA 加载
        title = await page.title()
        print(f"[2] Page loaded: title={title}, url={page.url}")
    except Exception as e:
        print(f"[2] Page load FAILED: {e}")
        await close_browser()
        return

    # 3. 检查岗位卡片
    card_selector = "a[href*='/campus/position/'][href*='/detail']"
    try:
        cards = await page.query_selector_all(card_selector)
        print(f"[3] Job cards found: {len(cards)} (selector={card_selector})")

        if cards:
            # 提取前3个卡片的信息
            for i, card in enumerate(cards[:3]):
                try:
                    text = (await card.inner_text()).strip()
                    href = await card.get_attribute("href")
                    print(f"    Card {i}: href={href}")
                    print(f"           text={text[:80]}")
                except Exception as e:
                    print(f"    Card {i} extract error: {e}")
        else:
            print("    No cards found with selector, trying alternative selectors...")
            # 尝试其他可能的 selector
            for alt_sel in ["a[href*='/position/']", ".position-item", ".job-item", "[class*='position']"]:
                try:
                    alt_cards = await page.query_selector_all(alt_sel)
                    if alt_cards:
                        print(f"    Alternative selector found: {alt_sel} -> {len(alt_cards)} elements")
                        text = await alt_cards[0].inner_text()
                        print(f"    First element text: {text[:100]}")
                        break
                except Exception:
                    continue
    except Exception as e:
        print(f"[3] Card query FAILED: {e}")

    # 4. 检查页面中可能的 JD 详情容器
    print("[4] Page structure check:")
    try:
        body_text = await page.locator("body").inner_text()
        print(f"    Body text length: {len(body_text)}")
        # 检查是否包含岗位相关关键词
        for kw in ["前端", "后端", "算法", "工程师", "实习", "校招"]:
            if kw in body_text:
                print(f"    Found keyword: {kw}")
    except Exception as e:
        print(f"    Body text error: {e}")

    await close_browser()
    print("\n=== 环境验证完成 ===")


if __name__ == "__main__":
    asyncio.run(test())
