"""列出字节表单的所有字段详情，判断哪些会失败/跳过。"""
import asyncio
import json
from playwright.async_api import async_playwright
import sys
sys.path.insert(0, r"D:\x\ai agent")
from src.agent.nodes.fill_application import discover_form_fields, prepare_form

URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"
PROFILE = r"D:\x\ai agent\data\browser_profile"


async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(PROFILE, headless=True)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        print("URL:", page.url, "TITLE:", await page.title())
        if "login" in page.url:
            print("!! 需要登录，profile 无登录态")
            await ctx.close()
            return
        fields = await discover_form_fields(page)
        for i, f in enumerate(fields):
            print(f"[{i}] type={f.field_type:9} label={f.label!r} name={f.name!r} "
                  f"ph={f.placeholder!r} opts={json.dumps(f.options, ensure_ascii=False)[:70] if f.options else ''}")
        await ctx.close()


asyncio.run(main())
