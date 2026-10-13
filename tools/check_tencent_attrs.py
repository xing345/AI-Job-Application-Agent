"""检查腾讯岗位卡片的属性和data字段。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    browser = await get_browser()
    page = browser.page

    await page.goto("https://join.qq.com/post.html", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(6000)

    # 检查第一个卡片的所有属性和内部HTML
    result = await page.evaluate("""() => {
        const card = document.querySelector('li.post_box');
        if (!card) return null;

        // 所有属性
        const attrs = {};
        for (const attr of card.attributes) {
            attrs[attr.name] = attr.value.slice(0, 100);
        }

        // 内部HTML
        const innerHTML = card.innerHTML.slice(0, 1500);

        // 内部元素
        const children = [];
        for (const child of card.querySelectorAll('*')) {
            const childAttrs = {};
            for (const attr of child.attributes) {
                childAttrs[attr.name] = attr.value.slice(0, 80);
            }
            children.push({
                tag: child.tagName,
                className: (child.className || '').toString().slice(0, 60),
                attrs: childAttrs,
                text: (child.textContent || '').trim().slice(0, 60),
            });
        }

        return {attrs, innerHTML, children: children.slice(0, 15)};
    }""")

    if result:
        print("=== 卡片属性 ===")
        for k, v in result['attrs'].items():
            print(f"  {k} = {v}")

        print("\n=== 内部HTML ===")
        print(result['innerHTML'])

        print("\n=== 内部元素 ===")
        for c in result['children']:
            print(f"  <{c['tag']}> class='{c['className']}' text={c['text']}")
            for k, v in c['attrs'].items():
                print(f"    {k}={v}")

    # 检查分页元素
    print("\n=== 分页/加载更多元素 ===")
    pagination = await page.evaluate("""() => {
        const results = [];
        const sels = ['.pagination', '[class*="page"]', '[class*="load"]', '[class*="more"]', 'button'];
        for (const sel of sels) {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
                const text = (el.textContent || '').trim().slice(0, 50);
                if (text && (text.includes('页') || text.includes('加载') || text.includes('更多') ||
                    text.includes('下一页') || text.match(/^\\d+$/))) {
                    results.push({
                        tag: el.tagName,
                        className: (el.className || '').toString().slice(0, 60),
                        text: text,
                    });
                }
            }
        }
        return results;
    }""")
    for p in pagination[:10]:
        print(f"  <{p['tag']}> class='{p['className']}' text={p['text']}")

    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
