"""页面结构探测工具。

用于调试招聘网站的 DOM 结构，找出岗位卡片和链接的 selector。
用法：python -m tools.probe_page https://jobs.bytedance.com/campus/position
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser.manager import get_browser, close_browser
from src.browser.navigator import wait_for_load


async def probe(url: str):
    browser = await get_browser()
    page = browser.page

    print(f"正在打开: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)
    await wait_for_load(page, timeout=10000)

    print(f"\n页面标题: {await page.title()}")
    print(f"当前 URL: {page.url}")

    # 统计各种元素
    print("\n=== 页面元素统计 ===")
    for tag in ["a", "li", "div", "h1", "h2", "h3"]:
        count = await page.locator(tag).count()
        print(f"  <{tag}>: {count} 个")

    # 找出所有包含数字 ID 的链接（可能是岗位详情链接）
    print("\n=== 可能的岗位链接（前 20 条）===")
    links = await page.query_selector_all("a[href]")
    job_links = []
    for link in links:
        try:
            href = await link.get_attribute("href")
            text = (await link.inner_text()).strip()
            if href and text and len(text) < 100:
                full = urljoin(url, href)
                # 过滤导航链接
                if any(kw in text for kw in ["首页", "登录", "注册", "关于", "联系"]):
                    continue
                job_links.append((text, full))
        except Exception:
            continue

    for i, (text, href) in enumerate(job_links[:20]):
        print(f"  {i+1}. [{text}] -> {href}")

    print(f"\n共找到 {len(job_links)} 条候选链接")

    # 检查常见岗位卡片 selector
    print("\n=== 常见岗位卡片 selector 检查 ===")
    selectors = [
        "[class*='job-item']", "[class*='position-item']", "[class*='job-card']",
        "[class*='position-card']", "[class*='recruit']", "[class*='job-list']",
        "[class*='position-list']", "li", ".job-item", ".position-item",
    ]
    for sel in selectors:
        try:
            count = await page.locator(sel).count()
            if count > 0:
                print(f"  {sel}: {count} 个")
        except Exception:
            pass

    print("\n探测完成。浏览器保持打开，你可以手动检查页面结构。")
    print("按 Ctrl+C 关闭浏览器。")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await close_browser()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python -m tools.probe_page <URL>")
        sys.exit(1)
    asyncio.run(probe(sys.argv[1]))
