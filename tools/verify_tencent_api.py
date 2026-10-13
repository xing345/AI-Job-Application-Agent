"""验证腾讯API并检查完整响应结构。"""
import asyncio
import json
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    browser = await get_browser()
    page = browser.page

    # 先打开页面建立session
    await page.goto("https://join.qq.com/post.html", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    api_url = "https://join.qq.com/api/v1/position/searchPosition"
    payload = {
        "projectIdList": [],
        "projectMappingIdList": [1, 2, 104, 14, 20],
        "keyword": "",
        "bgList": [],
        "workCountryType": 0,
        "workCityList": [],
        "recruitCityList": [],
        "positionFidList": [],
        "pageIndex": 1,
        "pageSize": 10,
    }

    resp = await page.request.post(api_url, data=payload)
    data = await resp.json()

    print("=== 顶层字段 ===")
    print(f"status={data.get('status')}, message={data.get('message')}")
    print(f"data字段keys: {list(data.get('data', {}).keys())}")

    inner = data["data"]
    for k, v in inner.items():
        if k != "positionList":
            print(f"  {k} = {v}")

    positions = inner.get("positionList", [])
    print(f"\n=== 第1页 {len(positions)} 个岗位 ===")
    for p in positions:
        print(f"  postId={p['postId']} | {p['positionTitle']} | {p['workCities'].strip()[:30]} | family={p['positionFamily']}")

    # 获取第2页确认分页
    payload["pageIndex"] = 2
    resp2 = await page.request.post(api_url, data=payload)
    data2 = await resp2.json()
    positions2 = data2["data"]["positionList"]
    print(f"\n=== 第2页 {len(positions2)} 个岗位 ===")
    for p in positions2[:3]:
        print(f"  postId={p['postId']} | {p['positionTitle']}")

    # 测试详情页JD提取
    if positions:
        test_p = positions[1]  # Agent开发工程师
        detail_url = f"https://join.qq.com/post_detail.html?postid={test_p['postId']}"
        print(f"\n=== 测试详情页: {test_p['positionTitle']} ===")
        print(f"URL: {detail_url}")
        detail_page = await browser._context.new_page()
        await detail_page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
        await detail_page.wait_for_timeout(4000)

        body = await detail_page.locator("body").inner_text()
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        print(f"详情页文本 {len(lines)} 行:")
        for i, line in enumerate(lines[:30]):
            print(f"  {i}: {line[:80]}")
        await detail_page.close()

    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
