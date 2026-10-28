"""探测腾讯 combobox 点击后的弹层选项结构。"""
import asyncio
import os
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.agent.nodes.fill_application import prepare_form, discover_form_fields
from src.models.profile import UserProfile

URL = "https://join.qq.com/resumeedit.html?postid=12846343027092709277696&subDirectionId="
URL = "https://join.qq.com/resumeedit.html?postid=1284634302709277696&subDirectionId="
TARGETS = ["国家/地区", "学历", "成绩排名", "期望工作城市", "感兴趣的事业群"]

OPTION_SELS = [".el-select-dropdown__item", "[class*='select-option']",
               "[class*='dropdown-item']", "[class*='picker-item']",
               "ul[class*='dropdown'] li", "[class*='cascader-node']",
               "[role='option']", "[class*='option-item']"]


async def main():
    profile = UserProfile.model_validate_json(
        open(r"D:\x\ai agent\data\user_profile.json", encoding="utf-8").read())
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
    await page.wait_for_timeout(3500)
    await prepare_form(page, profile)
    fields = await discover_form_fields(page)

    for target in TARGETS:
        f = next((x for x in fields if target in (x.label + x.placeholder)
                  and x.field_type in ("combobox", "datepicker")), None)
        if not f:
            print(f"\n### {target}: 未找到对应字段")
            continue
        print(f"\n### {target} (type={f.field_type})")
        try:
            el = page.locator(f.element_selector).first
            await el.scroll_into_view_if_needed()
            await el.click(timeout=4000)
            await page.wait_for_timeout(900)
        except Exception as e:
            print("  点击失败:", str(e)[:80]); continue

        found = False
        for sel in OPTION_SELS:
            try:
                loc = page.locator(sel)
                c = await loc.count()
                vis_items = []
                for i in range(min(c, 25)):
                    if await loc.nth(i).is_visible():
                        t = (await loc.nth(i).inner_text()).strip().replace("\n", " ")
                        if t:
                            vis_items.append(t[:18])
                if vis_items:
                    print(f"  selector '{sel}' 可见选项 {len(vis_items)}: {vis_items[:12]}")
                    found = True
                    break
            except Exception:
                pass
        if not found:
            print("  未识别到弹层选项")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

    await asyncio.sleep(1)
    await close_browser()


asyncio.run(main())
