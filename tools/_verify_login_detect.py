"""验证 detect_block 能识别腾讯扫码/社交登录页。"""
import asyncio
import os
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.browser.hitl import default_handler as hitl


async def main():
    os.environ["BROWSER_PROFILE_SUFFIX"] = "tencent"
    browser = await get_browser()
    page = browser.page
    await page.wait_for_timeout(800)
    for _ in range(3):
        try:
            await page.goto("https://join.qq.com/login.html",
                            wait_until="domcontentloaded", timeout=30000)
            break
        except Exception:
            await page.wait_for_timeout(500)
    await page.wait_for_timeout(2500)
    reason = await hitl.detect_block(page)
    print("登录页 detect_block 结果:", reason)
    await close_browser()


asyncio.run(main())
