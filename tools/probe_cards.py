"""
职位卡片（非 <a href>）诊断探针：验证「点击卡片能否拿到真实详情页 URL」

用法：
    python tools/probe_cards.py <url> [url ...]
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright  # noqa: E402

from src.search.browser_job_finder import BrowserJobFinder, CARD_SCAN_JS  # noqa: E402

DEFAULT = [
    "https://join.qq.com/post.html?query=p_1",
    "https://sokon.zhiye.com/campus/jobs?4=%5B%7B%22id%22%3A%229%22%2C%22label%22%3A%22%E7%A0%94%E5%8F%91%E7%B1%BB%22%7D%5D",
    "https://jobs.mihoyo.com/#/campus/position?projectIds%5B0%5D=13",
    "https://app.mokahr.com/campus-recruitment/zte/46903#/jobs?page=1&anchorName=jobsList",
    "https://campus.jd.com/home#/jobs?to=present&type=present",
    "https://jobs.bilibili.com/campus/positions?type=3",
]


async def probe(url, headless=True, clicks=3):
    finder = BrowserJobFinder(tavily_api_key="", headless=headless, interactive=False)
    rep = {"url": url}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            locale="zh-CN", viewport={"width": 1366, "height": 900})
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            rep["goto_error"] = str(e)
        await finder._settle_page(page)
        rep["final_url"] = page.url
        try:
            cards = await page.evaluate(CARD_SCAN_JS)
        except Exception as e:
            cards = []
            rep["scan_error"] = str(e)
        rep["cards"] = len(cards)
        rep["card_sample"] = [
            {k: c.get(k) for k in ("idx", "text", "href", "tag", "cls")} for c in cards[:10]
        ]
        rep["click_results"] = []
        for c in cards[:clicks]:
            sel = f'[data-dsh-card="{c["idx"]}"]'
            before = page.url
            got, how = "", ""
            popup = None
            try:
                async with ctx.expect_page(timeout=3500) as pi:
                    await page.click(sel, timeout=3500)
                popup = await pi.value
            except Exception:
                popup = None
            if popup is not None:
                try:
                    await popup.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass
                await asyncio.sleep(1.5)
                got, how = popup.url, "popup"
                try:
                    await popup.close()
                except Exception:
                    pass
            else:
                await asyncio.sleep(1.5)
                if page.url != before:
                    got, how = page.url, "same_page"
                    try:
                        await page.go_back(wait_until="domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    await finder._settle_page(page, light=True)
            rep["click_results"].append(
                {"card": c["text"][:40], "how": how, "url": got[:160],
                 "before": before[:100]})
        await ctx.close()
        await browser.close()
    return rep


async def main():
    urls = [a for a in sys.argv[1:] if not a.startswith("--")] or DEFAULT
    headless = "--headed" not in sys.argv
    out = []
    for u in urls:
        print(f"\n=== 卡片探针: {u} ===", flush=True)
        try:
            r = await probe(u, headless=headless)
        except Exception as e:
            r = {"url": u, "probe_error": repr(e)}
        out.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=2)[:3500], flush=True)
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "logs", "probe", "cards_report.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
