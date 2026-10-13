"""深度诊断米哈游8925详情页DOM，区分主JD与相关岗位侧栏。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    browser = await get_browser()
    page = browser.page

    # 最强导航：about:blank 完全脱离文档 -> 目标URL 完整加载
    target = "https://jobs.mihoyo.com/#/campus/position/8925"
    print("=== 方式1: about:blank -> 目标 ===")
    await page.goto("about:blank")
    await page.wait_for_timeout(500)
    await page.goto(target, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(4000)
    print(f"page.url = {page.url}")

    await diagnose(page)

    await close_browser()


async def diagnose(page):
    # 1. 所有包含"图形研究员"的元素
    print("\n=== 包含'图形研究员'的元素（前8个）===")
    hits = await page.evaluate("""(expected) => {
        const out = [];
        const all = document.querySelectorAll('*');
        for (const el of all) {
            // 只看直接文本
            const direct = Array.from(el.childNodes)
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent).join('');
            if (direct.includes('图形研究员') || direct.includes('游戏AI研发工程师')) {
                const rect = el.getBoundingClientRect();
                out.push({
                    tag: el.tagName,
                    cls: (el.className || '').toString().slice(0, 50),
                    text: direct.trim().slice(0, 40),
                    x: Math.round(rect.x), y: Math.round(rect.y),
                });
            }
        }
        return out.slice(0, 12);
    }""", "游戏AI研发")
    for h in hits:
        print(f"  <{h['tag']}> class='{h['cls']}' pos=({h['x']},{h['y']}) text='{h['text']}'")

    # 2. h1/h2 标签
    print("\n=== h1/h2/h3 标签 ===")
    heads = await page.evaluate("""() => {
        const out = [];
        for (const tag of ['h1','h2','h3']) {
            document.querySelectorAll(tag).forEach(el => {
                const rect = el.getBoundingClientRect();
                out.push({tag, text: el.textContent.trim().slice(0,40),
                          cls:(el.className||'').toString().slice(0,40), x:Math.round(rect.x)});
            });
        }
        return out;
    }""")
    for h in heads:
        print(f"  <{h['tag']}> x={h['x']} class='{h['cls']}' text='{h['text']}'")

    # 3. 主内容区：找包含"岗位职责"的最大容器的结构
    print("\n=== 主JD容器定位 ===")
    main_info = await page.evaluate("""() => {
        let anchor = null;
        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.children.length === 0 && el.textContent.trim() === '岗位职责') {
                anchor = el; break;
            }
        }
        if (!anchor) return {found: false};
        // 向上找3层容器
        let cur = anchor;
        const chain = [];
        for (let i = 0; i < 6; i++) {
            cur = cur.parentElement;
            if (!cur) break;
            chain.push({tag: cur.tagName, cls: (cur.className||'').toString().slice(0,50),
                        len: cur.textContent.length});
        }
        // 主标题：找主内容区顶部的标题
        return {found: true, chain};
    }""")
    if main_info.get("found"):
        for c in main_info["chain"]:
            print(f"  <{c['tag']}> class='{c['cls']}' text_len={c['len']}")
    else:
        print("  未找到'岗位职责'锚点")

    # 4. body文本前25行
    print("\n=== body文本前25行 ===")
    body = await page.locator("body").inner_text()
    for i, line in enumerate([l for l in body.split("\n") if l.strip()][:25]):
        print(f"  {i}: {line.strip()[:75]}")


if __name__ == "__main__":
    asyncio.run(main())
