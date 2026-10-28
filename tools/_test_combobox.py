"""实测 _fill_combobox 能否选中多个下拉字段。"""
import asyncio
import os
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.agent.nodes.fill_application import (
    prepare_form, discover_form_fields, _fill_combobox)
from src.models.profile import UserProfile
from src.models.match import FillStatus

URL = "https://join.qq.com/resumeedit.html?postid=1284634302709277696&subDirectionId="
SHOT = r"D:\x\ai agent\tools\_combobox_filled.png"
WANT = [("学历", "本科"),
        ("成绩排名", "其他"),
        ("面试城市", "远程面试"),
        ("部门", "无明确意向"),
        ("国家/地区", "中国")]


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
    print("combobox字段:", [(x.label or x.placeholder)[:14]
                           for x in fields if x.field_type == "combobox"])

    for key, val in WANT:
        cands = [x for x in fields if key in x.label and x.field_type == "combobox"]
        if not cands:
            print(f"{key}: 无combobox字段")
            continue
        f = cands[0]
        f.value = val
        st = await _fill_combobox(page, f)
        actual = ""
        try:
            actual = await page.locator(f.element_selector).first.input_value()
        except Exception:
            pass
        print(f"{key} -> 目标'{val}' 状态={st.value} 实际='{actual}' {'OK' if st==FillStatus.FILLED else ''} {f.error}")

    await page.screenshot(path=SHOT)
    print("截图:", SHOT)
    await asyncio.sleep(2)
    await close_browser()


asyncio.run(main())
