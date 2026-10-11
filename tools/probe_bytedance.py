"""字节跳动页面深度探测。

打开页面后等待加载，打印所有链接、岗位卡片候选、网络请求特征。
用法：python -m tools.probe_bytedance
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser.manager import get_browser, close_browser
from src.browser.navigator import wait_for_load


async def main():
    browser = await get_browser()
    page = browser.page

    url = "https://jobs.bytedance.com/campus/position"
    print(f"打开: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    print("等待 SPA 加载 8 秒...")
    await page.wait_for_timeout(8000)
    await wait_for_load(page, timeout=10000)

    print(f"\n页面标题: {await page.title()}")
    print(f"当前 URL: {page.url}")

    # 滚动几次加载更多
    print("\n滚动加载...")
    for i in range(3):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)

    # 打印所有链接
    print("\n=== 页面所有链接（文本+URL）===")
    links = await page.query_selector_all("a[href]")
    print(f"共 {len(links)} 个链接")
    for i, link in enumerate(links):
        try:
            href = await link.get_attribute("href")
            text = (await link.inner_text()).strip()
            if text or href:
                print(f"  [{i}] text='{text[:50]}' href='{href[:80]}'")
        except Exception:
            pass

    # 检查常见岗位卡片
    print("\n=== 岗位卡片候选 ===")
    selectors = [
        "[class*='job']", "[class*='position']", "[class*='recruit']",
        "[class*='item']", "[class*='card']", "[class*='list']",
        "li", "tr",
    ]
    for sel in selectors:
        try:
            count = await page.locator(sel).count()
            if count > 0 and count < 500:
                # 取第一个看看内容
                first = page.locator(sel).first
                text = (await first.inner_text()).strip()[:100]
                print(f"  {sel}: {count} 个, 首个内容: '{text}'")
        except Exception as e:
            print(f"  {sel}: error - {e}")

    # 检查是否有 iframe
    print("\n=== iframe 检查 ===")
    iframes = await page.query_selector_all("iframe")
    print(f"共 {len(iframes)} 个 iframe")
    for i, iframe in enumerate(iframes):
        src = await iframe.get_attribute("src")
        print(f"  [{i}] src='{src}'")

    # 检查 body 文本长度
    body_text = await page.locator("body").inner_text()
    print(f"\n=== body 文本长度: {len(body_text)} 字符 ===")
    print("前 500 字符:")
    print(body_text[:500])

    print("\n探测完成，浏览器保持打开。按 Ctrl+C 退出。")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
