"""打开腾讯 resumeedit，截图并打印页面结构，判断表单是否分步/折叠、为何字段不可见。"""
import asyncio
import os
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser

URL = "https://join.qq.com/resumeedit.html?postid=1284634302709277696&subDirectionId="
OUT = r"D:\x\ai agent\tools\_resume_form_shot.png"


async def main():
    os.environ["BROWSER_PROFILE_SUFFIX"] = "tencent"
    browser = await get_browser()
    page = browser.page
    await page.wait_for_timeout(800)
    for _ in range(3):
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            break
        except Exception:
            await page.wait_for_timeout(500)
    await page.wait_for_timeout(5000)

    await page.screenshot(path=OUT, full_page=True)
    print("截图已保存:", OUT)

    body = await page.locator("body").inner_text()
    print("=== body 文本前 1800 字 ===")
    print(body[:1800])

    # 可见的 input 数量 vs 总数
    all_inp = await page.query_selector_all("input")
    vis = 0
    for el in all_inp:
        try:
            if await el.is_visible():
                vis += 1
        except Exception:
            pass
    print(f"\ninput 总数 {len(all_inp)}，当前可见 {vis}")

    # 找可能的"下一步/编辑/展开/开始"按钮
    for kw in ["下一步", "开始填写", "编辑", "展开", "添加", "保存", "我已准备", "确认"]:
        try:
            loc = page.get_by_text(kw, exact=False)
            if await loc.count() > 0:
                print(f"发现含'{kw}'元素 {await loc.count()} 个")
        except Exception:
            pass

    await asyncio.sleep(2)
    await close_browser()


asyncio.run(main())
