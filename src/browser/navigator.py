"""页面导航、点击、等待封装。

所有浏览器操作走这里，统一超时和异常处理。
"""
from __future__ import annotations

import logging
from typing import List, Optional

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)


async def safe_goto(page: Page, url: str, timeout: int = 30000) -> bool:
    """安全导航，失败返回 False。"""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        return True
    except PlaywrightTimeoutError:
        logger.warning("Navigation timeout: %s", url)
        return False
    except Exception as e:
        logger.warning("Navigation failed: %s -> %s", url, e)
        return False


async def wait_for_load(page: Page, timeout: int = 15000) -> None:
    """等待页面网络空闲。"""
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    except PlaywrightTimeoutError:
        # networkidle 可能等不到，退化为 domcontentloaded
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass


async def safe_click(page: Page, selector: str, timeout: int = 10000) -> bool:
    """安全点击，失败返回 False。"""
    try:
        el = page.locator(selector).first
        await el.wait_for(state="visible", timeout=timeout)
        await el.click()
        return True
    except Exception as e:
        logger.warning("Click failed: %s -> %s", selector, e)
        return False


async def safe_fill(page: Page, selector: str, value: str, timeout: int = 10000) -> bool:
    """安全填写文本框。"""
    try:
        el = page.locator(selector).first
        await el.wait_for(state="visible", timeout=timeout)
        await el.fill(value)
        return True
    except Exception as e:
        logger.warning("Fill failed: %s -> %s", selector, e)
        return False


async def safe_select(page: Page, selector: str, value: str, timeout: int = 10000) -> bool:
    """安全选择下拉框。"""
    try:
        el = page.locator(selector).first
        await el.wait_for(state="visible", timeout=timeout)
        await el.select_option(value=value)
        return True
    except Exception as e:
        logger.warning("Select failed: %s -> %s", selector, e)
        return False


async def extract_text(page: Page, selector: str, timeout: int = 5000) -> str:
    """提取元素文本，失败返回空串。"""
    try:
        el = page.locator(selector).first
        await el.wait_for(state="visible", timeout=timeout)
        return (await el.inner_text()).strip()
    except Exception:
        return ""


async def extract_all_texts(page: Page, selector: str, timeout: int = 5000) -> List[str]:
    """提取所有匹配元素的文本。"""
    try:
        locator = page.locator(selector)
        count = await locator.count()
        texts: list[str] = []
        for i in range(count):
            try:
                t = await locator.nth(i).inner_text()
                texts.append(t.strip())
            except Exception:
                continue
        return texts
    except Exception:
        return []


async def element_exists(page: Page, selector: str, timeout: int = 3000) -> bool:
    """检查元素是否存在。"""
    try:
        locator = page.locator(selector)
        await locator.first.wait_for(state="attached", timeout=timeout)
        return await locator.count() > 0
    except Exception:
        return False
