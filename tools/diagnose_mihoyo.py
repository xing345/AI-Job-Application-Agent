"""诊断米哈游校招页面结构。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 米哈游页面诊断 ===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.mihoyo.com/#/campus/position", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(5000)

    print(f"页面标题: {await page.title()}")
    print(f"当前URL: {page.url}")

    # 检查是否有弹窗
    print("\n--- 弹窗检测 ---")
    popup_selectors = [".modal", ".dialog", ".popup", "[class*='mask']", "[class*='Modal']", "[class*='Dialog']"]
    for sel in popup_selectors:
        try:
            count = await page.locator(sel).count()
            if count > 0:
                visible = await page.locator(sel).first.is_visible()
                print(f"  {sel}: {count}个, 可见={visible}")
        except Exception:
            continue

    # 列出所有a标签的href
    print("\n--- 所有链接（前30个）---")
    links = await page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a')).map(a => ({
            href: a.getAttribute('href') || '',
            text: (a.innerText || '').trim().slice(0, 50)
        })).filter(l => l.href);
    }""")
    for i, link in enumerate(links[:30]):
        print(f"  [{i}] href={link['href'][:60]} text={link['text'][:30]}")

    # 检查CARD_SELECTORS
    print("\n--- CARD_SELECTORS 匹配检测 ---")
    card_selectors = [
        "a[href*='/campus/position/']",
        "a[href*='/position/']",
        "a[href*='/job/']",
        "a[href*='#/campus/position/']",
        "a[href*='#/position/']",
        ".position-list .position-item a",
        ".job-list .job-item a",
        "[class*='position-item']",
        "[class*='job-item']",
        "[class*='position-card']",
    ]
    for sel in card_selectors:
        try:
            count = await page.locator(sel).count()
            print(f"  {sel}: {count}个")
        except Exception as e:
            print(f"  {sel}: 错误 {e}")

    # 打印页面文本前50行
    print("\n--- 页面文本（前50行）---")
    body_text = await page.locator("body").inner_text()
    lines = body_text.split("\n")
    for i, line in enumerate(lines[:50]):
        if line.strip():
            print(f"  {i}: {line.strip()[:80]}")

    await close_browser()
    print("\n诊断完成")


if __name__ == "__main__":
    asyncio.run(main())
