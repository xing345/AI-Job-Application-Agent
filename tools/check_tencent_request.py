"""获取腾讯searchPosition API的请求参数。"""
import asyncio
import json
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    browser = await get_browser()
    page = browser.page

    requests_captured = []

    async def on_request(request):
        if "searchPosition" in request.url:
            requests_captured.append({
                "url": request.url,
                "method": request.method,
                "post_data": request.post_data,
                "headers": {k: v for k, v in request.headers.items()
                           if k.lower() in ("content-type", "accept", "origin", "referer")},
            })

    page.on("request", lambda r: asyncio.create_task(on_request(r)))

    await page.goto("https://join.qq.com/post.html", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)

    # 点击第2页
    pager = await page.query_selector("ul.el-pager")
    if pager:
        lis = await pager.query_selector_all("li")
        for li in lis:
            if (await li.inner_text()).strip() == "2":
                await li.click()
                await page.wait_for_timeout(5000)
                break

    # 点击第3页
    pager = await page.query_selector("ul.el-pager")
    if pager:
        lis = await pager.query_selector_all("li")
        for li in lis:
            if (await li.inner_text()).strip() == "3":
                await li.click()
                await page.wait_for_timeout(5000)
                break

    print(f"捕获 {len(requests_captured)} 个searchPosition请求\n")
    for i, r in enumerate(requests_captured):
        print(f"--- 请求 {i+1} ---")
        print(f"URL: {r['url']}")
        print(f"POST data: {r['post_data']}")
        print()

    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
