"""诊断字节跳动JD详情页中"403"出现的位置。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 诊断JD详情页中的403 ===")
    browser = await get_browser()
    page = browser.page

    # 打开用户反馈的那个岗位
    url = "https://jobs.bytedance.com/campus/position/7694628337026844933/detail"
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(3000)

    body_text = await page.locator("body").inner_text()

    # 搜索包含403的行
    print("\n包含'403'的文本行:")
    for i, line in enumerate(body_text.split("\n")):
        if "403" in line:
            print(f"  行{i}: {line.strip()[:100]}")

    # 检查页面标题
    print(f"\n页面标题: {await page.title()}")
    print(f"页面URL: {page.url}")

    # 测试新的关键词是否会误报
    BLOCK_TEXT_KEYWORDS = [
        "403 Forbidden", "403 forbidden", "HTTP 403", "http 403",
        "错误代码403", "错误代码：403", "403错误", "403 错误",
        "访问被拒绝", "访问拒绝", "forbidden", "Forbidden",
        "请求过于频繁", "操作频繁", "访问频率受限", "频率限制",
    ]

    print("\n新关键词检测结果:")
    hit = False
    for kw in BLOCK_TEXT_KEYWORDS:
        if kw in body_text:
            print(f"  命中: '{kw}'")
            hit = True
    if not hit:
        print("  无命中（修复成功，不会误报）")

    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
