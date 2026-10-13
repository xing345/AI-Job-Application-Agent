"""深入诊断米哈游岗位卡片DOM结构。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 米哈游卡片DOM结构诊断 ===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.mihoyo.com/#/campus/position", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(5000)

    # 找到包含"Golang后端开发工程师"的元素，向上追溯其容器结构
    print("\n--- 岗位卡片容器结构 ---")
    card_structure = await page.evaluate("""() => {
        // 找到包含岗位标题的元素
        const allElements = document.querySelectorAll('*');
        let titleEl = null;
        for (const el of allElements) {
            if (el.children.length === 0 && el.textContent.trim() === 'Golang后端开发工程师') {
                titleEl = el;
                break;
            }
        }
        if (!titleEl) return { error: 'title not found' };

        // 向上追溯5层，记录每层的tag、class、id
        const chain = [];
        let current = titleEl;
        for (let i = 0; i < 6 && current; i++) {
            chain.push({
                tag: current.tagName,
                className: (current.className || '').toString().slice(0, 80),
                id: current.id,
                childCount: current.children.length,
                text: (current.textContent || '').trim().slice(0, 60),
            });
            current = current.parentElement;
        }

        // 找到最可能的卡片容器（包含标题、地点、类型等信息的最小容器）
        let cardContainer = null;
        current = titleEl;
        while (current) {
            const text = current.textContent || '';
            if (text.includes('上海') && text.includes('程序&技术类') && text.includes('全职')) {
                cardContainer = current;
                break;
            }
            current = current.parentElement;
        }

        return {
            titleChain: chain,
            cardContainer: cardContainer ? {
                tag: cardContainer.tagName,
                className: (cardContainer.className || '').toString().slice(0, 100),
                childCount: cardContainer.children.length,
                outerHTML: cardContainer.outerHTML.slice(0, 500),
            } : null,
        };
    }""")

    if "error" in card_structure:
        print(f"  错误: {card_structure['error']}")
    else:
        print("  标题元素向上追溯:")
        for i, layer in enumerate(card_structure['titleChain']):
            print(f"    层{i}: <{layer['tag']}> class='{layer['className'][:50]}' children={layer['childCount']}")
            print(f"         text: {layer['text'][:50]}")

        if card_structure['cardContainer']:
            cc = card_structure['cardContainer']
            print(f"\n  卡片容器: <{cc['tag']}> class='{cc['className'][:60]}' children={cc['childCount']}")
            print(f"  outerHTML前500字符:")
            print(f"    {cc['outerHTML'][:500]}")

    # 检查所有可点击元素（有cursor:pointer或onclick的）
    print("\n--- 可点击元素检测 ---")
    clickable = await page.evaluate("""() => {
        const results = [];
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const style = window.getComputedStyle(el);
            const hasOnClick = el.onclick || el.getAttribute('onclick');
            const hasCursorPointer = style.cursor === 'pointer';
            const hasRoleButton = el.getAttribute('role') === 'button';
            if ((hasCursorPointer || hasOnClick || hasRoleButton) && el.textContent.trim().length > 5) {
                results.push({
                    tag: el.tagName,
                    className: (el.className || '').toString().slice(0, 60),
                    text: (el.textContent || '').trim().slice(0, 40),
                    cursor: style.cursor,
                    onclick: !!hasOnClick,
                });
            }
        }
        return results.slice(0, 20);
    }""")
    for c in clickable[:15]:
        print(f"  <{c['tag']}> class='{c['className'][:40]}' cursor={c['cursor']} onclick={c['onclick']}")
        print(f"    text: {c['text']}")

    # 检查分页控件
    print("\n--- 分页控件 ---")
    pagination = await page.evaluate("""() => {
        const results = [];
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const text = (el.textContent || '').trim();
            if (text === 'Previous' || text === 'Next' || (text === '1' && el.children.length === 0)) {
                results.push({
                    tag: el.tagName,
                    className: (el.className || '').toString().slice(0, 60),
                    text: text,
                    parentClass: (el.parentElement?.className || '').toString().slice(0, 60),
                });
            }
        }
        return results;
    }""")
    for p in pagination[:10]:
        print(f"  <{p['tag']}> class='{p['className'][:40]}' text='{p['text']}' parent='{p['parentClass'][:40]}'")

    await close_browser()
    print("\n诊断完成")


if __name__ == "__main__":
    asyncio.run(main())
