"""调试米哈游卡片点击后的弹窗/抽屉。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 米哈游弹窗调试 ===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.mihoyo.com/#/campus/position", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(5000)

    # 点击第一个卡片
    cards = await page.query_selector_all("div[class*='jobItem']")
    print(f"卡片数量: {len(cards)}")
    if cards:
        await cards[0].scroll_into_view_if_needed()
        await page.wait_for_timeout(500)
        await cards[0].click()
        await page.wait_for_timeout(3000)

    print(f"点击后URL: {page.url}")

    # 检查弹窗/抽屉/模态框
    print("\n--- 弹窗检测 ---")
    modal_selectors = [
        ".ant-modal", ".ant-drawer", ".ant-modal-wrap", ".ant-drawer-wrap",
        "[class*='modal']", "[class*='drawer']", "[class*='Modal']", "[class*='Drawer']",
        "[class*='popup']", "[class*='Popup']", "[class*='dialog']", "[class*='Dialog']",
        "[role='dialog']", "[role='document']",
    ]
    for sel in modal_selectors:
        try:
            count = await page.locator(sel).count()
            if count > 0:
                visible = await page.locator(sel).first.is_visible()
                text = (await page.locator(sel).first.inner_text()).strip()[:100]
                print(f"  {sel}: {count}个, 可见={visible}")
                print(f"    文本: {text}")
        except Exception:
            continue

    # 检查所有可见的大容器（可能是详情面板）
    print("\n--- 大容器检测 ---")
    containers = await page.evaluate("""() => {
        const results = [];
        const all = document.querySelectorAll('div');
        for (const el of all) {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            // 找宽度大于400，高度大于300，且z-index较高的元素（可能是弹窗）
            if (rect.width > 400 && rect.height > 300 && rect.top >= 0 && rect.left >= 0) {
                const zIndex = style.zIndex;
                const position = style.position;
                const text = (el.textContent || '').trim().slice(0, 80);
                if (text.length > 20) {
                    results.push({
                        className: (el.className || '').toString().slice(0, 60),
                        width: rect.width,
                        height: rect.height,
                        top: rect.top,
                        left: rect.left,
                        zIndex: zIndex,
                        position: position,
                        text: text,
                    });
                }
            }
        }
        // 按z-index排序，取前10
        results.sort((a, b) => (parseInt(b.zIndex) || 0) - (parseInt(a.zIndex) || 0));
        return results.slice(0, 10);
    }""")
    for c in containers:
        print(f"  class='{c['className'][:40]}' {c['width']}x{c['height']} top={c['top']} zIndex={c['zIndex']} pos={c['position']}")
        print(f"    text: {c['text'][:60]}")

    # 检查是否有关闭按钮
    print("\n--- 关闭按钮检测 ---")
    close_selectors = [
        ".ant-modal-close", ".ant-drawer-close", "[class*='close']",
        "button[aria-label='Close']", ".anticon-close",
    ]
    for sel in close_selectors:
        try:
            count = await page.locator(sel).count()
            if count > 0:
                visible = await page.locator(sel).first.is_visible()
                print(f"  {sel}: {count}个, 可见={visible}")
        except Exception:
            continue

    # 打印页面完整文本（看看详情内容在哪里）
    print("\n--- 页面文本（含详情）---")
    body_text = await page.locator("body").inner_text()
    lines = [l.strip() for l in body_text.split("\n") if l.strip()]
    for i, line in enumerate(lines[:80]):
        print(f"  {i}: {line[:80]}")

    await close_browser()
    print("\n调试完成")


if __name__ == "__main__":
    asyncio.run(main())
