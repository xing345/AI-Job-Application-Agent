"""检查字节跳动分页机制：页面底部控件、URL参数、下一页按钮。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 字节跳动分页机制诊断 ===")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://jobs.bytedance.com/campus/position", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(5000)

    # 1. 滚动到底部
    print("\n[1] 滚动到底部...")
    await page.evaluate("""() => {
        const sections = document.querySelectorAll('section');
        for (const sec of sections) {
            if (sec.scrollHeight > sec.clientHeight) {
                sec.scrollTop = sec.scrollHeight;
            }
        }
        window.scrollTo(0, document.body.scrollHeight);
    }""")
    await page.wait_for_timeout(3000)

    # 2. 检查页面底部的所有按钮和链接
    print("\n[2] 页面底部的按钮/链接:")
    bottom_elements = await page.evaluate("""() => {
        const results = [];
        // 获取页面底部 30% 区域的所有可点击元素
        const viewportHeight = window.innerHeight;
        const all = document.querySelectorAll('button, a, [role="button"], [class*="page"], [class*="pagination"]');
        for (const el of all) {
            const rect = el.getBoundingClientRect();
            // 只看在视口内或页面底部的元素
            if (rect.top > viewportHeight * 0.5 || rect.bottom > viewportHeight * 0.8) {
                const text = (el.innerText || el.textContent || '').trim().slice(0, 50);
                if (text) {
                    results.push({
                        tag: el.tagName,
                        text: text,
                        className: (el.className || '').toString().slice(0, 60),
                        href: el.href || '',
                        visible: rect.width > 0 && rect.height > 0,
                    });
                }
            }
        }
        return results.slice(0, 30);
    }""")

    for el in bottom_elements:
        visible = "可见" if el['visible'] else "隐藏"
        print(f"  <{el['tag']}> '{el['text']}' class='{el['className'][:40]}' [{visible}]")
        if el['href']:
            print(f"    href: {el['href'][:80]}")

    # 3. 检查分页相关的 DOM 元素
    print("\n[3] 分页相关元素:")
    pagination = await page.evaluate("""() => {
        const selectors = [
            '[class*="pagination"]', '[class*="pager"]', '[class*="page-nav"]',
            '[class*="page-btn"]', '[class*="next-page"]', '[class*="prev-page"]',
            '[class*="load-more"]', '[class*="more-btn"]',
            'ul[class*="page"]', 'div[class*="page"]',
        ];
        const results = [];
        for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
                results.push({
                    selector: sel,
                    tag: el.tagName,
                    className: (el.className || '').toString().slice(0, 80),
                    text: (el.innerText || '').trim().slice(0, 100),
                    childCount: el.children.length,
                });
            }
        }
        return results;
    }""")

    if pagination:
        for p in pagination:
            print(f"  {p['selector']} -> <{p['tag']}> class='{p['className'][:50]}'")
            print(f"    text: '{p['text'][:80]}', children: {p['childCount']}")
    else:
        print("  未找到分页元素")

    # 4. 检查 URL 格式和可能的分页参数
    print("\n[4] URL 分析:")
    print(f"  当前 URL: {page.url}")
    print(f"  页面标题: {await page.title()}")

    # 5. 检查页面中是否有页码文本
    print("\n[5] 页码文本搜索:")
    page_text = await page.evaluate("document.body.innerText")
    import re
    page_matches = re.findall(r'第\s*\d+\s*页|共\s*\d+\s*页|页码|page\s*\d+|/\s*\d+', page_text, re.IGNORECASE)
    if page_matches:
        print(f"  找到页码相关文本: {page_matches[:10]}")
    else:
        print("  未找到页码文本")

    # 6. 检查是否有数字导航（1, 2, 3...）
    print("\n[6] 数字导航按钮:")
    number_buttons = await page.evaluate("""() => {
        const results = [];
        const all = document.querySelectorAll('button, a, span, div');
        for (const el of all) {
            const text = (el.innerText || '').trim();
            if (/^\d+$/.test(text) && text.length <= 3) {
                const rect = el.getBoundingClientRect();
                if (rect.width > 10 && rect.height > 10) {
                    results.push({
                        tag: el.tagName,
                        text: text,
                        className: (el.className || '').toString().slice(0, 50),
                    });
                }
            }
        }
        return results.slice(0, 20);
    }""")
    if number_buttons:
        for nb in number_buttons[:10]:
            print(f"  <{nb['tag']}> '{nb['text']}' class='{nb['className'][:40]}'")
    else:
        print("  未找到数字导航")

    await close_browser()
    print("\n诊断完成")


if __name__ == "__main__":
    asyncio.run(main())
