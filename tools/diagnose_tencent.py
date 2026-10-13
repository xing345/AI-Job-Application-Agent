"""诊断腾讯招聘页面结构。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 腾讯招聘页面结构诊断 ===\n")
    browser = await get_browser()
    page = browser.page

    await page.goto("https://join.qq.com/post.html", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(6000)

    print(f"页面标题: {await page.title()}")
    print(f"当前URL: {page.url}\n")

    # 1. 检查所有a标签
    links = await page.query_selector_all("a")
    print(f"=== a标签数量: {len(links)} ===")
    for i, link in enumerate(links[:20]):
        href = await link.get_attribute("href")
        text = (await link.inner_text()).strip()[:40]
        if href:
            print(f"  [{i}] href={href[:60]} text={text}")

    # 2. 检查可能的岗位卡片元素
    print(f"\n=== 岗位卡片候选元素 ===")
    card_candidates = await page.evaluate("""() => {
        const results = [];
        const selectors = [
            '[class*="job"]', '[class*="post"]', '[class*="position"]',
            '[class*="recruit"]', '[class*="card"]', '[class*="item"]',
            '[class*="list"] > div', '[class*="list"] > li',
        ];
        for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            if (els.length > 0 && els.length < 200) {
                const samples = [];
                for (let i = 0; i < Math.min(3, els.length); i++) {
                    samples.push({
                        className: (els[i].className || '').toString().slice(0, 60),
                        tag: els[i].tagName,
                        text: (els[i].textContent || '').trim().slice(0, 80),
                    });
                }
                results.push({selector: sel, count: els.length, samples: samples});
            }
        }
        return results;
    }""")
    for c in card_candidates:
        print(f"\n  selector='{c['selector']}' count={c['count']}")
        for s in c['samples']:
            print(f"    <{s['tag']}> class='{s['className'][:40]}' text={s['text'][:60]}")

    # 3. 打印页面文本前50行
    print(f"\n=== 页面文本前50行 ===")
    body = await page.locator("body").inner_text()
    lines = [l.strip() for l in body.split("\n") if l.strip()]
    for i, line in enumerate(lines[:50]):
        print(f"  {i}: {line[:80]}")

    await close_browser()
    print("\n诊断完成")


if __name__ == "__main__":
    asyncio.run(main())
