"""确认米哈游详情页主标题和主JD内容容器的精确selector。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    browser = await get_browser()
    page = browser.page

    target = "https://jobs.mihoyo.com/#/campus/position/8925"
    await page.goto("about:blank")
    await page.wait_for_timeout(400)
    await page.goto(target, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(4000)

    # 1. 用"工作职责"锚点向上定位主容器
    info = await page.evaluate("""() => {
        let anchor = null;
        for (const el of document.querySelectorAll('*')) {
            if (el.children.length === 0 && el.textContent.trim() === '工作职责') {
                anchor = el; break;
            }
        }
        if (!anchor) return {found:false};
        let cur = anchor;
        const chain = [];
        for (let i=0;i<7;i++){
            cur = cur.parentElement;
            if(!cur) break;
            const rect = cur.getBoundingClientRect();
            chain.push({tag:cur.tagName, cls:(cur.className||'').toString().slice(0,60),
                        len:cur.textContent.length, x:Math.round(rect.x), w:Math.round(rect.width)});
        }
        return {found:true, chain};
    }""")
    print("=== '工作职责'锚点向上容器链 ===")
    if info.get("found"):
        for c in info["chain"]:
            print(f"  <{c['tag']}> x={c['x']} w={c['w']} class='{c['cls']}' len={c['len']}")

    # 2. 主标题元素
    print("\n=== [class*='jobTitle'] 元素 ===")
    titles = await page.evaluate("""() => {
        const out=[];
        document.querySelectorAll("[class*='jobTitle'],[class*='titleLine']").forEach(el=>{
            const r=el.getBoundingClientRect();
            out.push({cls:(el.className||'').toString().slice(0,50), text:el.textContent.trim().slice(0,40), x:Math.round(r.x)});
        });
        return out;
    }""")
    for t in titles:
        print(f"  x={t['x']} class='{t['cls']}' text='{t['text']}'")

    # 3. 验证主内容容器文本是否只含主JD（不含侧栏相关岗位）
    print("\n=== 主内容容器候选 ===")
    cands = await page.evaluate("""() => {
        const out=[];
        const sels=["[class*='jobDetail']","[class*='positionDetail']","[class*='job-detail']",
                    "[class*='detailContent']","[class*='content']","main"];
        for(const sel of sels){
            document.querySelectorAll(sel).forEach(el=>{
                const t=el.textContent;
                const r=el.getBoundingClientRect();
                out.push({sel, cls:(el.className||'').toString().slice(0,45), len:t.length,
                          x:Math.round(r.x), hasSidebar: t.includes('相关岗位')});
            });
        }
        return out;
    }""")
    for c in cands:
        print(f"  sel='{c['sel']}' x={c['x']} len={c['len']} sidebar={c['hasSidebar']} class='{c['cls']}'")

    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
