"""探测腾讯详情页点击"投递简历"后的真实跳转：同页/新标签/登录，以及表单结构。"""
import asyncio
import os
import sys
sys.path.insert(0, r"D:\x\ai agent")

import aiosqlite
from src.storage import state_db
from src.browser.manager import get_browser, close_browser


async def main():
    os.environ["BROWSER_PROFILE_SUFFIX"] = "tencent"
    await state_db.init_db()
    async with aiosqlite.connect(state_db._DB_PATH) as db:
        c = await db.execute(
            "SELECT job_url,job_title FROM jobs WHERE site_name='tencent' "
            "AND job_title='AI全栈工程师' AND category_path LIKE '应届毕业生 %' LIMIT 1")
        r = await c.fetchone()
    if not r:
        # 退而取任一全职目标岗
        async with aiosqlite.connect(state_db._DB_PATH) as db:
            c = await db.execute(
                "SELECT job_url,job_title FROM jobs WHERE site_name='tencent' "
                "AND job_title IN ('Agent开发工程师','AI应用工程师') "
                "AND category_path LIKE '应届毕业生%' LIMIT 1")
            r = await c.fetchone()
    url, title = r
    print("目标岗:", title, "|", url)

    browser = await get_browser()
    page = browser.page
    context = page.context
    await page.wait_for_timeout(800)

    for attempt in range(3):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            break
        except Exception as e:
            print(f"goto 重试 {attempt + 1}: {e}")
            await page.wait_for_timeout(600)
    await page.wait_for_timeout(3000)
    print("详情页当前URL:", page.url)

    clicked = False
    for text in ["投递简历", "立即投递", "申请职位", "立即申请", "投简历"]:
        try:
            btn = page.get_by_text(text, exact=False).first
            if await btn.count() > 0 and await btn.is_visible():
                print("→ 点击按钮:", text)
                try:
                    async with context.expect_page(timeout=5000) as pi:
                        await btn.click()
                    new_page = await pi.value
                    await new_page.wait_for_load_state("domcontentloaded")
                    await new_page.wait_for_timeout(2500)
                    print("→ 在新标签页打开:", new_page.url)
                    target = new_page
                except Exception:
                    await page.wait_for_timeout(3000)
                    print("→ 同页跳转后URL:", page.url)
                    target = page
                clicked = True
                break
        except Exception as e:
            print("按钮尝试失败:", text, e)

    if not clicked:
        print("未找到/未能点击投递按钮")
        target = page

    await target.wait_for_timeout(2000)
    n_input = len(await target.query_selector_all("input:not([type=hidden])"))
    n_ta = len(await target.query_selector_all("textarea"))
    n_sel = len(await target.query_selector_all("select"))
    print(f"表单元素: input={n_input} textarea={n_ta} select={n_sel}")
    body = await target.locator("body").inner_text()
    print("页面正文前600字:\n", body[:600])

    await asyncio.sleep(3)
    await close_browser()


asyncio.run(main())
