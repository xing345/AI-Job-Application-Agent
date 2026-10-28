"""非 MCP：直接用 Playwright 打开字节表单，监测 URL 是否跳走。"""
import asyncio
from playwright.async_api import async_playwright

URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"
PROFILE = r"D:\x\ai agent\data\browser_profile"


async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(PROFILE, headless=False)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        for i in range(8):
            await page.wait_for_timeout(1000)
            print(f"t{i}: {page.url}")
        await ctx.close()


asyncio.run(main())
