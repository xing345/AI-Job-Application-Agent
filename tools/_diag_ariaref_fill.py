"""验证 aria-ref 定位填值。"""
import asyncio
from playwright.async_api import async_playwright

URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"
PROFILE = r"D:\x\ai agent\data\browser_profile"


async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(PROFILE, headless=True)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        loc = page.locator("aria-ref=e98")
        print("count:", await loc.count())
        await loc.fill("TESTREF123")
        print("value:", await loc.input_value())
        await ctx.close()


asyncio.run(main())
