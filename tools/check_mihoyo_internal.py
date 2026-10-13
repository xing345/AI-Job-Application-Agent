"""检查米哈游卡片内部结构和JS数据。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 米哈游卡片内部结构检查 ===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.mihoyo.com/#/campus/position", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(6000)

    # 清除筛选（点击清除按钮）
    try:
        clear_btn = page.locator("button:has-text('清除'), span:has-text('清除')").first
        if await clear_btn.count() > 0:
            await clear_btn.click()
            await page.wait_for_timeout(2000)
            print("已清除筛选")
    except Exception:
        pass

    print(f"当前URL: {page.url}")

    # 检查第一个卡片的完整内部HTML
    cards = await page.query_selector_all("div[class*='jobItem']")
    print(f"卡片数量: {len(cards)}")

    if cards:
        first = cards[0]
        inner_html = await first.inner_html()
        print(f"\n第一个卡片内部HTML（前1000字符）:")
        print(inner_html[:1000])

        # 检查卡片内是否有a标签
        links = await first.query_selector_all("a")
        print(f"\n卡片内a标签数量: {len(links)}")
        for link in links:
            href = await link.get_attribute("href")
            text = (await link.inner_text()).strip()[:30]
            print(f"  href={href} text={text}")

        # 检查卡片内所有可点击元素
        clickable = await first.evaluate("""el => {
            const results = [];
            const all = el.querySelectorAll('*');
            for (const e of all) {
                const style = window.getComputedStyle(e);
                if (style.cursor === 'pointer' || e.onclick || e.getAttribute('onclick')) {
                    results.push({
                        tag: e.tagName,
                        className: (e.className || '').toString().slice(0, 50),
                        text: (e.textContent || '').trim().slice(0, 30),
                        cursor: style.cursor,
                    });
                }
            }
            return results;
        }""")
        print(f"\n卡片内可点击元素:")
        for c in clickable:
            print(f"  <{c['tag']}> class='{c['className'][:30]}' cursor={c['cursor']} text={c['text']}")

    # 检查页面JS变量中是否有岗位数据
    print("\n--- 检查页面JS变量 ---")
    js_data = await page.evaluate("""() => {
        const results = {};
        // 检查常见的全局变量
        const keys = Object.keys(window).filter(k => 
            k.toLowerCase().includes('job') || 
            k.toLowerCase().includes('position') || 
            k.toLowerCase().includes('list') ||
            k.toLowerCase().includes('data') ||
            k.toLowerCase().includes('store') ||
            k.toLowerCase().includes('state')
        );
        results.windowKeys = keys.slice(0, 20);
        
        // 检查React fiber
        const root = document.getElementById('root') || document.querySelector('#app');
        if (root) {
            const fiberKey = Object.keys(root).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
            results.hasReactFiber = !!fiberKey;
        }
        
        return results;
    }""")
    print(f"  相关window变量: {js_data.get('windowKeys', [])}")
    print(f"  有React Fiber: {js_data.get('hasReactFiber', False)}")

    # 尝试拦截网络请求，看看岗位列表API
    print("\n--- 检查网络请求 ---")
    # 刷新页面并监听请求
    async with page.expect_request("**/api/**") as req_info:
        await page.reload(wait_until="domcontentloaded")
    try:
        request = await req_info.value
        print(f"  API请求: {request.url[:100]}")
        print(f"  方法: {request.method}")
    except Exception as e:
        print(f"  未捕获到API请求: {e}")

    await page.wait_for_timeout(3000)

    await close_browser()
    print("\n完成")


if __name__ == "__main__":
    asyncio.run(main())
