"""诊断腾讯 resumeedit.html：58字段的真实类型/可见性/selector命中，以及填写失败原因。"""
import asyncio
import os
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.agent.nodes.fill_application import discover_form_fields

POSTID = "1284634302709277696"
URL = f"https://join.qq.com/resumeedit.html?postid={POSTID}&subDirectionId="


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
    await page.wait_for_timeout(4000)
    print("当前URL:", page.url)

    # iframe 检查
    for fr in page.frames:
        if fr != page.main_frame:
            print("发现 iframe:", fr.url[:80])

    fields = await discover_form_fields(page)
    print(f"\n字段总数 {len(fields)}\n")

    # 每个字段：selector 命中数 / 可见性 / bounding box
    for i, f in enumerate(fields):
        info = f"{i:2d}. [{f.field_type:8s}] label='{(f.label or f.name)[:18]}' sel='{f.element_selector[:45]}'"
        try:
            loc = page.locator(f.element_selector)
            cnt = await loc.count()
            vis = await loc.first.is_visible() if cnt else False
            box = await loc.first.bounding_box() if cnt else None
            info += f" 命中{cnt} 可见{vis}"
            if box:
                info += f" y={int(box['y'])}"
        except Exception as e:
            info += f" 检查异常:{str(e)[:40]}"
        print(info)

    # 对前若干文本字段尝试填测试值，捕获具体异常
    print("\n=== 试填测试值 ===")
    tested = 0
    for i, f in enumerate(fields):
        if tested >= 8:
            break
        if f.field_type not in ("text", "textarea", "email", "tel"):
            continue
        tested += 1
        try:
            el = page.locator(f.element_selector).first
            await el.wait_for(state="visible", timeout=4000)
            await el.fill("测试")
            print(f"  {i} 成功: {f.label}")
        except Exception as e:
            print(f"  {i} 失败: {f.label} -> {str(e)[:120]}")

    await asyncio.sleep(2)
    await close_browser()


asyncio.run(main())
