"""
详情页 URL 校验工具：确认「构造/点击得到的职位详情 URL」真能渲染出 JD 正文。

用法：
    python tools/verify_detail_urls.py <url> [url ...]
    python tools/verify_detail_urls.py --file logs/probe/detail_urls.txt
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright  # noqa: E402

JD_WORDS = ("职位描述", "岗位职责", "任职要求", "工作职责", "任职资格", "职责描述",
            "招聘要求", "岗位要求", "job description", "responsibilities",
            "requirements", "qualifications", "我们希望你")


async def check(page, url):
    row = {"url": url}
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
    except Exception as e:
        row["error"] = str(e)[:120]
        return row
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    await asyncio.sleep(3)
    try:
        body = await page.inner_text("body")
    except Exception as e:
        row["error"] = f"inner_text: {e}"
        return row
    row["title"] = (await page.title())[:60]
    row["final_url"] = page.url[:120]
    row["body_len"] = len(body)
    row["jd_words"] = [w for w in JD_WORDS if w in body][:5]
    row["head"] = " ".join(body.split())[:150]
    return row


async def main():
    args = [a for a in sys.argv[1:]]
    urls = []
    if "--file" in args:
        path = args[args.index("--file") + 1]
        with open(path, encoding="utf-8") as f:
            urls = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    else:
        urls = [a for a in args if a.startswith("http")]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            locale="zh-CN", viewport={"width": 1366, "height": 900})
        page = await ctx.new_page()
        for u in urls:
            row = await check(page, u)
            ok = "OK " if row.get("jd_words") else "!! "
            print(f"{ok}{row['url'][:110]}")
            print(f"    final={row.get('final_url','')[:110]} len={row.get('body_len')} "
                  f"jd_words={row.get('jd_words')}")
            print(f"    head={row.get('head','')[:130]}")
            if row.get("error"):
                print(f"    error={row['error']}")
        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
