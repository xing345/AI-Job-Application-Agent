"""尝试多种滚动方式：键盘PageDown、点击+wheel、直接scrollTop+dispatchEvent。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 多方式滚动测试 ===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.bytedance.com/campus/position", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(5000)

    card_sel = "a[href*='/campus/position/'][href*='/detail']"

    def count_cards():
        return page.evaluate("document.querySelectorAll(\"" + card_sel + "\").length")

    initial = await count_cards()
    print(f"初始卡片数: {initial}")

    # 方式1：点击第一个卡片，然后按 PageDown
    print("\n[方式1] 点击卡片 + PageDown")
    try:
        first_card = page.locator(card_sel).first
        await first_card.click()
        await page.wait_for_timeout(1000)
        # 按 Escape 关闭可能的弹窗
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

        for i in range(5):
            await page.keyboard.press("PageDown")
            await page.wait_for_timeout(1500)
            c = await count_cards()
            print(f"  PageDown {i+1}: cards={c}")
    except Exception as e:
        print(f"  失败: {e}")

    # 方式2：hover 在卡片上 + mouse.wheel
    print("\n[方式2] hover卡片 + mouse.wheel")
    try:
        first_card = page.locator(card_sel).first
        await first_card.hover()
        await page.wait_for_timeout(500)
        for i in range(5):
            await page.mouse.wheel(0, 800)
            await page.wait_for_timeout(1500)
            c = await count_cards()
            print(f"  wheel {i+1}: cards={c}")
    except Exception as e:
        print(f"  失败: {e}")

    # 方式3：找到 section 容器，直接设置 scrollTop 并触发 scroll 事件
    print("\n[方式3] section scrollTop + dispatchEvent")
    try:
        result = await page.evaluate("""() => {
            // 找到可滚动的 section
            const sections = document.querySelectorAll('section');
            for (const sec of sections) {
                if (sec.scrollHeight > sec.clientHeight + 50) {
                    const before = sec.scrollTop;
                    sec.scrollTop = sec.scrollHeight;
                    // 触发 scroll 事件
                    sec.dispatchEvent(new Event('scroll', { bubbles: true }));
                    window.dispatchEvent(new Event('scroll', { bubbles: true }));
                    return { found: true, before: before, after: sec.scrollTop, scrollHeight: sec.scrollHeight };
                }
            }
            return { found: false };
        }""")
        print(f"  结果: {result}")
        await page.wait_for_timeout(2000)
        c = await count_cards()
        print(f"  滚动后卡片数: {c}")
    except Exception as e:
        print(f"  失败: {e}")

    # 方式4：用 Playwright 的 locator.scroll_into_view_if_needed 滚动最后一个卡片
    print("\n[方式4] 滚动最后一个卡片到可视区域")
    try:
        cards = page.locator(card_sel)
        count = await cards.count()
        if count > 0:
            last_card = cards.nth(count - 1)
            await last_card.scroll_into_view_if_needed()
            await page.wait_for_timeout(2000)
            c = await count_cards()
            print(f"  滚动后卡片数: {c}")
    except Exception as e:
        print(f"  失败: {e}")

    # 方式5：检查是否有"加载更多"按钮
    print("\n[方式5] 检查加载更多按钮")
    try:
        load_more_selectors = [
            "button:has-text('加载更多')", "button:has-text('更多')",
            "button:has-text('查看更多')", ".load-more", ".more-button",
            "[class*='loadMore']", "[class*='load-more']",
        ]
        for sel in load_more_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    text = await btn.inner_text()
                    print(f"  找到按钮: {sel} -> '{text[:30]}'")
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    c = await count_cards()
                    print(f"  点击后卡片数: {c}")
                    break
            except Exception:
                continue
        else:
            print("  未找到加载更多按钮")
    except Exception as e:
        print(f"  失败: {e}")

    await close_browser()
    print("\n测试完成")


if __name__ == "__main__":
    asyncio.run(main())
