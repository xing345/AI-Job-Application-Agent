"""
XHR JSON 结构探针：把招聘站职位列表接口的响应结构打出来，
用来补齐 _walk_jobs_json 认识的字段名。

用法：python tools/probe_api_json.py <list_url> [keyword_in_url]
"""

import asyncio
import json
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright  # noqa: E402

from src.search.browser_job_finder import BrowserJobFinder  # noqa: E402


def summarize(node, depth=0, path="$"):
    """打印 JSON 结构骨架（每层最多 3 个元素）"""
    lines = []
    if depth > 4:
        return lines
    if isinstance(node, dict):
        keys = list(node.keys())[:40]
        lines.append(f"{'  ' * depth}{path} dict keys={keys}")
        for k in keys[:12]:
            lines += summarize(node[k], depth + 1, f"{path}.{k}")
    elif isinstance(node, list):
        lines.append(f"{'  ' * depth}{path} list len={len(node)}")
        if node:
            lines += summarize(node[0], depth + 1, f"{path}[0]")
    else:
        lines.append(f"{'  ' * depth}{path} = {str(node)[:60]}")
    return lines


async def main():
    url = sys.argv[1]
    kw = sys.argv[2] if len(sys.argv) > 2 else ""
    finder = BrowserJobFinder(tavily_api_key="", headless=True, interactive=False)
    bodies = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            locale="zh-CN", viewport={"width": 1366, "height": 900})
        page = await ctx.new_page()

        async def on_resp(resp):
            try:
                ct = (resp.headers or {}).get("content-type", "")
                if "json" not in ct:
                    return
                if kw and kw.lower() not in resp.url.lower():
                    return
                data = await resp.json()
            except Exception:
                return
            bodies.append((resp.url, data))

        page.on("response", on_resp)
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await finder._settle_page(page)
        await asyncio.sleep(3)
        await ctx.close()
        await browser.close()

    for u, data in bodies:
        host_path = urlparse(u).netloc + urlparse(u).path
        print(f"\n=== {host_path} ===")
        for line in summarize(data)[:40]:
            print(line)
        found = []
        finder._walk_jobs_json(data, found)
        print(f"--> _walk_jobs_json 认出 {len(found)} 个: "
              f"{[f['title'][:24] for f in found[:5]]}")


if __name__ == "__main__":
    asyncio.run(main())
