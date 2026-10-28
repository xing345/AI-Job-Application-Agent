"""点击'学历'下拉后截图，扫描所有可能的弹层容器。"""
import asyncio
import os
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.agent.nodes.fill_application import prepare_form, discover_form_fields
from src.models.profile import UserProfile

URL = "https://join.qq.com/resumeedit.html?postid=1284634302709277696&subDirectionId="
SHOT = r"D:\x\ai agent\tools\_dropdown_open.png"


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
    el = page.locator(f.element_selector).first
    await el.scroll_into_view_if_needed()
    print("学历字段 selector:", f.element_selector)
    # 看元素外层结构
    wrapper = await el.evaluate("""el => {
        let p = el; let chain=[];
        for(let i=0;i<4 && p;i++){ chain.push(p.tagName.toLowerCase()+'.'+(p.className||'').toString().slice(0,40)); p=p.parentElement;}
        return chain;
    }""")
    print("外层链:", wrapper)

    await el.click(timeout=4000)
    await page.wait_for_timeout(1200)
    await page.screenshot(path=SHOT)

    # 扫描所有 class 含弹层语义的元素
    pops = await page.evaluate("""() => {
        const kws = ['dropdown','popper','panel','select','picker','cascader','popup','dialog','option'];
        const out=[];
        document.querySelectorAll('*').forEach(el=>{
            const cls=(el.className||'').toString();
            if(kws.some(k=>cls.toLowerCase().includes(k))){
                const r = el.getBoundingClientRect();
                if(r.width>0 && r.height>0){
                    out.push({tag:el.tagName.toLowerCase(), cls:cls.slice(0,45),
                              n:el.childElementCount, t:el.textContent.slice(0,25)});
                }
            }
        });
        return out.slice(0,30);
    }""")
    print("\n可见弹层类元素:")
    for p in pops:
        print(" ", p)

    await asyncio.sleep(1)
    await close_browser()


asyncio.run(main())
