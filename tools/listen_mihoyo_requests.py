"""监听米哈游页面所有网络请求，找岗位列表API。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 米哈游网络请求监听 ===")
    browser = await get_browser()
    page = browser.page

    # 记录所有请求
    requests = []

    async def on_request(request):
        url = request.url
        # 过滤掉静态资源和sentry
        if any(ext in url for ext in ['.js', '.css', '.png', '.jpg', '.svg', '.woff', '.ico', 'sentry', 'hm.baidu', 'google-analytics']):
            return
        requests.append({
            'url': url[:120],
            'method': request.method,
            'type': request.resource_type,
        })

    page.on("request", on_request)

    # 刷新页面
    await page.goto("https://jobs.mihoyo.com/#/campus/position", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)

    print(f"\n共捕获 {len(requests)} 个非静态请求:")
    for i, req in enumerate(requests):
        print(f"  [{i}] {req['method']} {req['type']} {req['url']}")

    # 尝试点击分页，看看有没有API请求
    print("\n--- 点击第2页 ---")
    requests.clear()
    try:
        page2 = page.locator("li.ant-pagination-item:nth-child(3) a, li.ant-pagination-item-2 a")
        if await page2.count() > 0:
            await page2.click()
            await page.wait_for_timeout(5000)
    except Exception as e:
        print(f"  点击失败: {e}")

    print(f"翻页后捕获 {len(requests)} 个请求:")
    for i, req in enumerate(requests):
        print(f"  [{i}] {req['method']} {req['type']} {req['url']}")

    # 检查页面的script标签中是否有内联数据
    print("\n--- 检查内联script数据 ---")
    inline_data = await page.evaluate("""() => {
        const scripts = document.querySelectorAll('script');
        const results = [];
        for (const s of scripts) {
            const text = s.textContent || '';
            if (text.length > 100 && (text.includes('job') || text.includes('position') || text.includes('list') || text.includes('data'))) {
                results.push({
                    length: text.length,
                    preview: text.slice(0, 200),
                });
            }
        }
        return results.slice(0, 5);
    }""")
    for i, d in enumerate(inline_data):
        print(f"  script[{i}] length={d['length']}")
        print(f"    preview: {d['preview'][:150]}")

    await close_browser()
    print("\n完成")


if __name__ == "__main__":
    asyncio.run(main())
