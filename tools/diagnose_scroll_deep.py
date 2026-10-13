"""深度诊断字节跳动滚动：找到真正的滚动容器，验证滚动效果。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 深度诊断字节跳动滚动 ===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.bytedance.com/campus/position", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(5000)

    # 1. 列出所有可滚动元素及其层级关系
    print("\n[1] 所有可滚动元素（按层级）:")
    scroll_elements = await page.evaluate("""() => {
        const results = [];
        function traverse(el, depth) {
            const style = window.getComputedStyle(el);
            const isScrollable = (style.overflowY === 'auto' || style.overflowY === 'scroll')
                && el.scrollHeight > el.clientHeight + 20;
            if (isScrollable) {
                results.push({
                    depth: depth,
                    tag: el.tagName,
                    className: (el.className || '').toString().slice(0, 80),
                    id: el.id,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    scrollTop: el.scrollTop,
                    childElementCount: el.childElementCount,
                });
            }
            for (const child of el.children) {
                traverse(child, depth + 1);
            }
        }
        traverse(document.body, 0);
        return results;
    }""")

    for i, el in enumerate(scroll_elements):
        indent = "  " * el['depth']
        print(f"  [{i}] {indent}<{el['tag']}> class='{el['className'][:60]}'")
        print(f"        scrollH={el['scrollHeight']}, clientH={el['clientHeight']}, scrollTop={el['scrollTop']}, children={el['childElementCount']}")

    # 2. 尝试滚动每个可滚动元素，看哪个能让卡片数变化
    card_selector = "a[href*='/campus/position/'][href*='/detail']"
    initial_cards = await page.evaluate(f"document.querySelectorAll('{card_selector}').length")
    print(f"\n[2] 初始卡片数: {initial_cards}")

    if scroll_elements:
        # 尝试滚动最深的可滚动元素（通常是真正的列表容器）
        for idx in range(len(scroll_elements) - 1, -1, -1):
            el_info = scroll_elements[idx]
            print(f"\n  尝试滚动元素 [{idx}]: <{el_info['tag']}> class='{el_info['className'][:40]}'")

            # 构造唯一标识
            if el_info['id']:
                ident = f"id='{el_info['id']}'"
            elif el_info['className']:
                classes = el_info['className'].split()[0]
                ident = f"class='{classes}'"
            else:
                ident = f"tag='{el_info['tag'].lower()}'"

            # 滚动并检查 scrollTop 变化和卡片数变化
            result = await page.evaluate(f"""() => {{
                const el = document.querySelector({ident!r});
                if (!el) return {{ found: false }};
                const before = {{ scrollTop: el.scrollTop, scrollHeight: el.scrollHeight }};
                el.scrollTop = el.scrollHeight;  // 滚到底
                const after = {{ scrollTop: el.scrollTop, scrollHeight: el.scrollHeight }};
                return {{ found: true, before, after, changed: before.scrollTop !== after.scrollTop }};
            }}""")

            if result.get('found'):
                print(f"    scrollTop: {result['before']['scrollTop']} -> {result['after']['scrollTop']} (changed={result['changed']})")
                await page.wait_for_timeout(2000)
                cards_after = await page.evaluate(f"document.querySelectorAll('{card_selector}').length")
                print(f"    滚动后卡片数: {cards_after}")
                if cards_after > initial_cards:
                    print(f"    ✅ 这个元素是真正的滚动容器！")
                    break
            else:
                print(f"    未找到元素")

    # 3. 检查是否有 shadow DOM 或 iframe
    print("\n[3] 检查 shadow DOM 和 iframe:")
    shadow_info = await page.evaluate("""() => {
        const shadows = [];
        const iframes = document.querySelectorAll('iframe');
        function findShadows(el) {
            if (el.shadowRoot) shadows.push(el.tagName);
            for (const child of el.children) findShadows(child);
        }
        findShadows(document.body);
        return { shadowHosts: shadows, iframeCount: iframes.length, iframes: Array.from(iframes).map(f => f.src) };
    }""")
    print(f"  Shadow DOM hosts: {shadow_info['shadowHosts']}")
    print(f"  iframes: {shadow_info['iframeCount']}")
    if shadow_info['iframes']:
        print(f"  iframe srcs: {shadow_info['iframes'][:3]}")

    await close_browser()
    print("\n诊断完成")


if __name__ == "__main__":
    asyncio.run(main())
