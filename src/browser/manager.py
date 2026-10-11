"""Playwright 浏览器会话管理。

持久化 user_data_dir，headless=False（必须可见，HITL 需要用户手动操作）。
异步上下文管理，全局单例。
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

# 持久化 profile 目录
_DEFAULT_PROFILE_DIR = str(Path(__file__).resolve().parent.parent.parent / "data" / "browser_profile")


class BrowserManager:
    """管理 Playwright 浏览器生命周期。"""

    def __init__(self, user_data_dir: Optional[str] = None, headless: bool = False):
        self.user_data_dir = user_data_dir or _DEFAULT_PROFILE_DIR
        self.headless = headless
        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """启动浏览器，创建持久化上下文。"""
        async with self._lock:
            if self._context is not None:
                return

            os.makedirs(self.user_data_dir, exist_ok=True)
            self._playwright = await async_playwright().start()

            # 使用持久化 context，保留登录态
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=self.headless,
                viewport={"width": 1440, "height": 900},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )

            # 取第一个 page，没有就新建
            if self._context.pages:
                self._page = self._context.pages[0]
            else:
                self._page = await self._context.new_page()

            logger.info("Browser started: profile=%s, headless=%s", self.user_data_dir, self.headless)

    async def stop(self) -> None:
        """关闭浏览器。"""
        if self._context:
            await self._context.close()
            self._context = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._page = None
        logger.info("Browser stopped")

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser 未启动，请先调用 start()")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("Browser 未启动，请先调用 start()")
        return self._context

    async def new_page(self) -> Page:
        """新建标签页。"""
        self._page = await self.context.new_page()
        return self._page

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000) -> Page:
        """导航到指定 URL。"""
        page = self.page
        await page.goto(url, wait_until=wait_until, timeout=timeout)
        return page

    async def screenshot(self, path: Optional[str] = None) -> bytes:
        """截图，用于错误诊断。"""
        page = self.page
        if path:
            await page.screenshot(path=path, full_page=True)
            logger.info("Screenshot saved: %s", path)
        return await page.screenshot(full_page=True)


# 全局单例
_manager: Optional[BrowserManager] = None


async def get_browser() -> BrowserManager:
    global _manager
    if _manager is None:
        _manager = BrowserManager()
        await _manager.start()
    return _manager


async def close_browser() -> None:
    global _manager
    if _manager is not None:
        await _manager.stop()
        _manager = None
