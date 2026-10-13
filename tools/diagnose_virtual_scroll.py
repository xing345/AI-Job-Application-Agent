"""诊断字节跳动虚拟滚动容器，找出正确的滚动方式。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 字节跳动虚拟滚动诊断 ===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.bytedance.com/campus/position", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(4000)

    # 1. 检查页面整体高度和滚动
    print("\n[1] 页面整体信息:")
    info = await page.evaluate("""() => {
        return {
            bodyScrollHeight: document.body.scrollHeight,
            bodyClientHeight: document.body.clientHeight,
            windowInnerHeight: window.innerHeight,
            documentScrollHeight: document.documentElement.scrollHeight,
        };
    }""")
    print(f"  {info}")

    # 2. 查找可滚动容器
    print("\n[2] 查找可滚动容器:")
    containers = await page.evaluate("""() => {
        const results = [];
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const style = window.getComputedStyle(el);
            if ((style.overflowY === 'auto' || style.overflowY === 'scroll')
                && el.scrollHeight > el.clientHeight + 50) {
                results.push({
                    tag: el.tagName,
                    className: el.className,
                    id: el.id,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    scrollTop: el.scrollTop,
                    childCount: el.children.length,
                });
            }
        }
        return results.slice(0, 10);
    }""")
    for i, c in enumerate(containers):
        print(f"  [{i}] <{c['tag']}> class='{c['className'][:50]}' id='{c['id']}'")
        print(f"      scrollHeight={c['scrollHeight']}, clientHeight={c['clientHeight']}, scrollTop={c['scrollTop']}, children={c['childCount']}")

    # 3. 检查岗位卡片数量
    card_selector = "a[href*='/campus/position/'][href*='/detail']"
    initial_count = await page.evaluate(f"document.querySelectorAll('{card_selector}').length")
    print(f"\n[3] 初始岗位卡片数: {initial_count}")

    # 4. 尝试滚动 window，看卡片数是否变化
    print("\n[4] 测试 window.scrollTo 效果:")
    for i in range(3):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        count = await page.evaluate(f"document.querySelectorAll('{card_selector}').length")
        scroll_y = await page.evaluate("window.scrollY")
        print(f"  滚动{i+1}后: cards={count}, scrollY={scroll_y}")

    # 5. 如果有可滚动容器，尝试滚动容器
    if containers:
        print("\n[5] 测试滚动第一个可滚动容器:")
        first_container = containers[0]
        # 构造 selector
        if first_container['id']:
            container_sel = f"#{first_container['id']}"
        elif first_container['className']:
            classes = first_container['className'].split()[0]
            container_sel = f".{classes}"
        else:
            container_sel = first_container['tag'].lower()

        print(f"  使用 selector: {container_sel}")
        for i in range(5):
            result = await page.evaluate(f"""() => {{
                const el = document.querySelector('{container_sel}');
                if (el) {{
                    el.scrollTop = el.scrollHeight;
                    return {{ scrollTop: el.scrollTop, scrollHeight: el.scrollHeight }};
                }}
                return null;
            }}""")
            await page.wait_for_timeout(2000)
            count = await page.evaluate(f"document.querySelectorAll('{card_selector}').length")
            print(f"  容器滚动{i+1}后: cards={count}, result={result}")

    # 6. 最终卡片数
    final_count = await page.evaluate(f"document.querySelectorAll('{card_selector}').length")
    print(f"\n[6] 最终岗位卡片数: {final_count}")

    await close_browser()
    print("\n诊断完成")


if __name__ == "__main__":
    asyncio.run(main())
