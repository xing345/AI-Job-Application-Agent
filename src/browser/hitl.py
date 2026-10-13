"""HITL（人在回路）暂停机制。

pause() 真正阻塞 asyncio 任务，暂停期间浏览器保持打开，用户可手动操作。
等待用户在终端输入 continue 后恢复。
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger(__name__)


@dataclass
class BlockResult:
    """暂停恢复后的页面状态。"""

    reason: str
    url_before: str
    url_after: str
    title_after: str


class BlockHandler:
    """检测拦截页面并暂停等待人工处理。

    只在 interactive + non-headless 时阻塞；headless 模式下检测到拦截直接报错。
    """

    # 登录墙检测 selector
    LOGIN_SELECTORS = [
        'input[type="password"]',
        'input[name*="password" i]',
        'input[name*="pwd" i]',
    ]
    LOGIN_TEXT_KEYWORDS = ["登录", "登陆", "sign in", "login", "账号密码登录"]

    # 验证码检测 selector
    CAPTCHA_SELECTORS = [
        ".g-recaptcha",
        'iframe[src*="captcha" i]',
        'iframe[src*="recaptcha" i]',
        'input[name*="captcha" i]',
        'input[name*="verify" i]',
        ".captcha",
        "#captcha",
        ".geetest_panel",
        ".tcaptcha",
    ]
    CAPTCHA_TEXT_KEYWORDS = ["验证码", "图形验证", "滑块验证", "安全验证", "人机验证", "captcha"]

    # 403 / 拦截页（注意："403"单独作为关键词太容易误报，
    # 因为职位编号、页面元素等可能包含数字403，必须用完整短语匹配）
    BLOCK_TEXT_KEYWORDS = [
        "403 Forbidden", "403 forbidden", "HTTP 403", "http 403",
        "错误代码403", "错误代码：403", "403错误", "403 错误",
        "访问被拒绝", "访问拒绝", "forbidden", "Forbidden",
        "请求过于频繁", "操作频繁", "访问频率受限", "频率限制",
    ]

    def __init__(self, interactive: bool = True):
        self.interactive = interactive

    async def detect_block(self, page: Page) -> Optional[str]:
        """检测当前页面是否存在登录墙/验证码/拦截。

        返回拦截原因字符串，未检测到返回 None。
        """
        # 1. 验证码元素检测
        for sel in self.CAPTCHA_SELECTORS:
            try:
                if await page.locator(sel).count() > 0:
                    return f"检测到验证码元素: {sel}"
            except Exception:
                continue

        # 2. 登录墙检测：密码框 + 登录语义
        has_password = False
        for sel in self.LOGIN_SELECTORS:
            try:
                if await page.locator(sel).count() > 0:
                    has_password = True
                    break
            except Exception:
                continue

        if has_password:
            try:
                body_text = (await page.locator("body").inner_text()).lower()
                for kw in self.LOGIN_TEXT_KEYWORDS:
                    if kw.lower() in body_text:
                        return f"检测到登录墙（密码框 + '{kw}'）"
            except Exception:
                pass
            # 有密码框就大概率是登录页
            return "检测到登录墙（密码输入框）"

        # 3. 页面文本关键词检测（验证码/403）
        try:
            body_text = await page.locator("body").inner_text()
            for kw in self.CAPTCHA_TEXT_KEYWORDS + self.BLOCK_TEXT_KEYWORDS:
                if kw in body_text:
                    return f"页面包含拦截关键词: '{kw}'"
        except Exception:
            pass

        return None

    async def pause(self, page: Page, reason: str) -> BlockResult:
        """阻塞等待用户手动处理。

        - 真正阻塞 asyncio（通过 asyncio.to_thread 运行 input）
        - 暂停期间浏览器保持打开
        - 终端打印醒目的暂停提示
        - 用户输入 continue 后恢复
        - 恢复时重新读取页面 URL 和标题
        """
        url_before = page.url

        if not self.interactive:
            # 非交互模式（如 headless）无法 HITL，直接报错
            raise RuntimeError(
                f"遇到拦截且非交互模式无法处理: {reason} | URL: {url_before}"
            )

        banner = (
            "\n"
            "╔══════════════════════════════════════════════════════════════╗\n"
            "║                    HITL 暂停 - 需要人工处理                    ║\n"
            "╠══════════════════════════════════════════════════════════════╣\n"
            f"║ 原因: {reason:<52} ║\n"
            f"║ URL : {url_before[:52]:<52} ║\n"
            "║                                                              ║\n"
            "║ 请在浏览器中手动完成操作（登录/验证码/等），完成后在终端        ║\n"
            "║ 输入 continue 并回车，Agent 将从断点继续。                     ║\n"
            "╚══════════════════════════════════════════════════════════════╝\n"
        )
        print(banner, flush=True)
        logger.warning("HITL pause: %s | %s", reason, url_before)

        # 真正阻塞：在独立线程中等待用户输入，不阻塞事件循环
        # 但当前协程会 await 这个 future，达到暂停效果
        await asyncio.to_thread(self._wait_for_continue)

        # 恢复后重新读取页面状态
        try:
            url_after = page.url
            title_after = await page.title()
        except Exception:
            url_after = url_before
            title_after = ""

        print(f"\n[HITL] 已恢复，当前页面: {title_after} | {url_after}\n", flush=True)
        logger.info("HITL resumed: %s -> %s", url_before, url_after)

        return BlockResult(
            reason=reason,
            url_before=url_before,
            url_after=url_after,
            title_after=title_after,
        )

    async def check_and_pause(self, page: Page) -> Optional[BlockResult]:
        """检测拦截，命中则暂停。返回 BlockResult 表示曾暂停，None 表示未拦截。"""
        reason = await self.detect_block(page)
        if reason:
            return await self.pause(page, reason)
        return None

    @staticmethod
    def _wait_for_continue() -> None:
        """阻塞线程等待用户输入 continue。"""
        while True:
            try:
                user_input = input("[HITL] 输入 continue 恢复 > ").strip().lower()
            except EOFError:
                # 非交互环境下无法输入，直接返回
                print("[HITL] 检测到非交互输入流，自动恢复", flush=True)
                return
            if user_input in ("continue", "c", "go", "ok"):
                return
            print("[HITL] 未识别指令，请输入 continue", flush=True)


# 全局默认 handler（interactive=True）
default_handler = BlockHandler(interactive=True)
