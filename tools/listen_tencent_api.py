"""监听腾讯招聘页面的网络请求，找到岗位列表API。"""
import asyncio
import json
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    browser = await get_browser()
    page = browser.page

    api_responses = []

    async def on_response(response):
        url = response.url
        if any(kw in url for kw in ["post", "job", "position", "list", "search", "query"]):
            if response.request.method in ("POST", "GET"):
                try:
                    body = await response.text()
                    if body and len(body) > 50:
                        api_responses.append({
                            "url": url[:150],
                            "method": response.request.method,
                            "status": response.status,
                            "body_preview": body[:500],
                        })
                except Exception:
                    pass

    page.on("response", lambda r: asyncio.create_task(on_response(r)))

    await page.goto("https://join.qq.com/post.html", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)

    # 尝试点击第2页
    print("尝试点击第2页...")
    try:
        pager = await page.query_selector("ul.el-pager")
        if pager:
            page_numbers = await pager.query_selector_all("li")
            for li in page_numbers:
                text = (await li.inner_text()).strip()
                if text == "2":
                    await li.click()
                    await page.wait_for_timeout(5000)
                    break
    except Exception as e:
        print(f"点击分页失败: {e}")

    print(f"\n=== 捕获到 {len(api_responses)} 个API响应 ===")
    for i, r in enumerate(api_responses):
        print(f"\n--- API {i+1} ---")
        print(f"URL: {r['url']}")
        print(f"Method: {r['method']}, Status: {r['status']}")
        print(f"Body: {r['body_preview'][:400]}")

    # 保存完整结果
    with open(r"D:\x\ai agent\tools\tencent_api_capture.json", "w", encoding="utf-8") as f:
        json.dump(api_responses, f, ensure_ascii=False, indent=2)

    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
