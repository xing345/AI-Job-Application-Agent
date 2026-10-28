"""验证 prepare_form：滚动/勾选/展开项目后，字段能否被正确发现并可见。"""
import asyncio
import os
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.agent.nodes.fill_application import prepare_form, discover_form_fields
from src.models.profile import UserProfile

URL = "https://join.qq.com/resumeedit.html?postid=1284634302709277696&subDirectionId="
SHOT = r"D:\x\ai agent\tools\_after_prepare.png"


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

    # 勾选状态
    for t in ["无实习经历", "无获奖信息"]:
        lab = page.locator("label.no_experience", has_text=t)
        if await lab.count():
            chk = await lab.first.evaluate("el => el.classList.contains('is-checked')")
            print(f"{t} 勾选: {chk}")
    print("项目名称组数:", await page.get_by_text("项目名称", exact=False).count())

    fields = await discover_form_fields(page)
    hit = vis = 0
    for f in fields:
        try:
            loc = page.locator(f.element_selector)
            c = await loc.count()
            if c:
                hit += 1
                if await loc.first.is_visible():
                    vis += 1
        except Exception:
            pass
    print(f"字段总数 {len(fields)}，selector命中 {hit}，可见 {vis}")

    await page.screenshot(path=SHOT, full_page=True)
    print("截图:", SHOT)
    await asyncio.sleep(2)
    await close_browser()


asyncio.run(main())
