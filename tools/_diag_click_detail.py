"""精确诊断：学历 el-select 点击前后，容器内 dropdown 结构与可见性。"""
import asyncio
import os
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.agent.nodes.fill_application import prepare_form, discover_form_fields
from src.models.profile import UserProfile

URL = "https://join.qq.com/resumeedit.html?postid=1284634302709277696&subDirectionId="


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

    f = next(x for x in fields if "学历" in x.label and x.field_type == "combobox")
    inp = page.locator(f.element_selector).first
    await inp.scroll_into_view_if_needed()
    handle = await inp.element_handle()
    await page.evaluate(
        """el => { window.__sel = el.closest('.el-select'); }""", handle)

    before = await page.evaluate(
        """() => {
            const c = window.__sel;
            const dd = c.querySelector('.el-select-dropdown');
            const items = c.querySelectorAll('.el-select-dropdown__item');
            return {
                selCls: c.className,
                ddExists: !!dd,
                ddDisplay: dd ? getComputedStyle(dd).display : null,
                itemCount: items.length,
                itemTexts: Array.from(items).map(i=>i.textContent.trim()),
                dropdownHTML: dd ? dd.outerHTML.slice(0,300) : null
            };
        }""")
    print("=== 点击前 ===")
    for k, v in before.items():
        print(f"  {k}: {v}")

    await inp.click(timeout=4000)
    await page.wait_for_timeout(1000)

    after = await page.evaluate(
        """() => {
            const c = window.__sel;
            const dd = c.querySelector('.el-select-dropdown');
            const items = c.querySelectorAll('.el-select-dropdown__item');
            return {
                ddDisplay: dd ? getComputedStyle(dd).display : null,
                visItems: Array.from(items).map(it=>({
                    t: it.textContent.trim(),
                    vis: !!(it.offsetParent || it.getClientRects().length),
                    itemDisplay: getComputedStyle(it).display
                })),
                bodyDropdownCount: document.querySelectorAll('body > .el-select-dropdown, .el-select-dropdown').length
            };
        }""")
    print("=== 点击后 ===")
    for k, v in after.items():
        print(f"  {k}: {v}")

    await page.screenshot(path=r"D:\x\ai agent\tools\_diag_click.png")
    await asyncio.sleep(1)
    await close_browser()


asyncio.run(main())
