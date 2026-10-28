"""探测腾讯简历表单的"添加xx / 无xx经历"控件类型与当前模块组数。"""
import asyncio
import os
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser

URL = "https://join.qq.com/resumeedit.html?postid=1284634302709277696&subDirectionId="
TEXTS = ["添加项目经历", "添加实习经历", "添加获奖信息", "添加学历",
         "无项目经历", "无实习经历", "无获奖信息"]


async def info_of(page, text):
    loc = page.get_by_text(text, exact=True)
    cnt = await loc.count()
    if cnt == 0:
        # 宽松匹配
        loc = page.get_by_text(text, exact=False)
        cnt = await loc.count()
        if cnt == 0:
            return f"[{text}] 未找到"
    js = """el => {
        let p = el;
        return {
            tag: el.tagName.toLowerCase(),
            cls: (el.className||'').toString().slice(0,50),
            ownText: el.childElementCount===0 ? el.textContent.slice(0,20) : '(含子元素)',
            parentTag: el.parentElement ? el.parentElement.tagName.toLowerCase() : '',
            parentCls: el.parentElement ? (el.parentElement.className||'').toString().slice(0,40) : '',
            nearbyInput: el.parentElement ? el.parentElement.querySelector('input[type=checkbox]') ? 'has-checkbox' : 'no-checkbox' : ''
        };
    }"""
    try:
        d = await loc.first.evaluate(js)
        return f"[{text}] x{cnt} tag={d['tag']} class='{d['cls']}' parent={d['parentTag']}({d['parentCls']}) {d['nearbyInput']} text='{d['ownText']}'"
    except Exception as e:
        return f"[{text}] x{cnt} 取信息失败 {str(e)[:50]}"


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
    # 滚一遍
    for y in range(0, 12000, 700):
        await page.evaluate(f"window.scrollTo(0,{y})")
        await page.wait_for_timeout(150)
    await page.wait_for_timeout(1000)

    for t in TEXTS:
        print(await info_of(page, t))

    # 当前各模块组数（数必填标签）
    for label in ["项目名称", "公司", "奖项名称", "学校名称"]:
        c = await page.get_by_text(label, exact=False).count()
        print(f"含'{label}'元素数: {c}")

    await asyncio.sleep(1)
    await close_browser()


asyncio.run(main())
