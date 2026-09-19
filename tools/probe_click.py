"""
定向点击探针：在职位列表页点击「标题命中关键词」的卡片，确认真实详情页 URL 长什么样。

用法：
    python tools/probe_click.py <list_url> <keyword> [count]
例：
    python tools/probe_click.py "https://join.qq.com/post.html?query=p_1" 工程师 3
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright  # noqa: E402

from src.search.browser_job_finder import BrowserJobFinder, CARD_SCAN_JS  # noqa: E402


async def main():
    url = sys.argv[1]
    keyword = sys.argv[2]
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    finder = BrowserJobFinder(tavily_api_key="", headless=True, interactive=False)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            locale="zh-CN", viewport={"width": 1366, "height": 900})
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await finder._settle_page(page)
        list_url = page.url

        targets = []
        for round_no in range(count):
            cards = await page.evaluate(CARD_SCAN_JS)
            pool = [c for c in cards
                    if keyword.lower() in c["text"].lower()
                    and c["text"] not in [t["text"] for t in targets]]
            if not pool:
                print(f"[{round_no}] 无更多命中卡片；当前候选={[c['text'][:20] for c in cards[:15]]}")
                break
            card = pool[0]
            targets.append(card)
            before = page.url
            got = ""
            popup = None
            try:
                async with ctx.expect_page(timeout=3500) as pi:
                    await page.click(f'[data-dsh-card="{card["idx"]}"]', timeout=3500)
                popup = await pi.value
            except Exception:
                popup = None
            if popup is not None:
                try:
                    await popup.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass
                await asyncio.sleep(1.2)
                got = f"[popup] {popup.url}"
                await popup.close()
            else:
                await asyncio.sleep(1.5)
                got = page.url if page.url != before else "(URL 未变化)"
            print(f"[{round_no}] 点击「{card['text'][:40]}」 -> {got[:160]}")
            # 回到列表页
            if page.url != list_url:
                try:
                    await page.go_back(wait_until="domcontentloaded", timeout=10000)
                except Exception:
                    pass
                if page.url != list_url:
                    try:
                        await page.goto(list_url, wait_until="domcontentloaded", timeout=30000)
                    except Exception:
                        pass
                await finder._settle_page(page, light=True)

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
