"""Playwright MCP 客户端封装：通过 stdio 启动官方 Playwright MCP 服务器，
把通用浏览器工具（navigate/snapshot/click/type/select/upload...）暴露为异步方法。

任何网站都用同一套工具，不写站点 selector。
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 官方 @playwright/mcp 的 cli.js；可被环境变量覆盖。
_DEFAULT_CLI = (
    r"C:\Users\Administrator\AppData\Local\Doubao\User Data\sandbox_runtime"
    r"\bases\772984f6fd3a8ae0ae7d2422cd7c2bfa\node\node_modules"
    r"\@playwright\mcp\cli.js"
)


def _extract_text(result: Any) -> str:
    """从 MCP CallToolResult 中拼出文本内容。"""
    parts: list[str] = []
    for c in getattr(result, "content", []) or []:
        txt = getattr(c, "text", None)
        if txt:
            parts.append(txt)
    return "\n".join(parts)


class MCPBrowser:
    """一个 Playwright MCP 浏览器会话。"""

    def __init__(self, user_data_dir: Optional[str] = None, headless: bool = False):
        self.user_data_dir = user_data_dir
        self.headless = headless
        self._session: Optional[ClientSession] = None
        self._cm_stack: list[Any] = []
        self._errlog = None

    async def __aenter__(self) -> "MCPBrowser":
        cli = os.getenv("PLAYWRIGHT_MCP_CLI", _DEFAULT_CLI)
        args: list[str] = []
        if os.path.exists(cli):
            args = [cli]
            command = "node"
        else:
            # 回退：用 npx 临时拉起
            command = "npx"
            args = ["-y", "@playwright/mcp"]
        if self.user_data_dir:
            args += ["--user-data-dir", self.user_data_dir]
        if self.headless:
            args += ["--headless"]
        # 纯文本决策，不要图像响应（减少负担）
        args += ["--image-responses", "omit"]
        # 复杂表单的动作可能较慢，放宽动作超时
        args += ["--timeout-action", "30000"]
        # 捕获 MCP 服务器（node）的 stderr，便于排查崩溃
        from pathlib import Path as _P
        _P("logs").mkdir(exist_ok=True)
        self._errlog = open("logs/mcp_stderr.log", "ab", buffering=0)
        # 动作后默认附带 accessibility snapshot，便于 agent 持续感知
        params = StdioServerParameters(command=command, args=args, stderr=self._errlog)

        stdio_cm = stdio_client(params)
        read, write = await stdio_cm.__aenter__()
        self._cm_stack.append(stdio_cm)
        session_cm = ClientSession(read, write)
        self._session = await session_cm.__aenter__()
        self._cm_stack.append(session_cm)
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        for cm in reversed(self._cm_stack):
            await cm.__aexit__(*exc)
        self._cm_stack.clear()
        self._session = None
        if getattr(self, "_errlog", None):
            try:
                self._errlog.close()
            except Exception:
                pass

    async def call(self, tool: str, arguments: Optional[dict] = None) -> str:
        """调用一个 MCP 工具，返回文本输出。"""
        if self._session is None:
            raise RuntimeError("MCPBrowser 未启动")
        result = await self._session.call_tool(tool, arguments or {})
        if getattr(result, "isError", False):
            raise RuntimeError(_extract_text(result) or f"工具 {tool} 报错")
        return _extract_text(result)

    # ---- 常用工具便捷方法 ----
    async def navigate(self, url: str) -> str:
        return await self.call("browser_navigate", {"url": url})

    async def snapshot(self, target: Optional[str] = None) -> str:
        args: dict[str, Any] = {}
        if target:
            args["target"] = target
        return await self.call("browser_snapshot", args)

    async def click(self, target: str) -> str:
        return await self.call("browser_click", {"target": target, "element": target})

    async def type(self, target: str, text: str, submit: bool = False) -> str:
        return await self.call(
            "browser_type", {"target": target, "element": target, "text": text, "submit": submit}
        )

    async def select_option(self, target: str, values: list[str]) -> str:
        return await self.call(
            "browser_select_option", {"target": target, "element": target, "values": values}
        )

    async def fill_form(self, fields: list[dict]) -> str:
        # 每个 field: {target, name, type, value}
        return await self.call("browser_fill_form", {"fields": fields})

    async def upload(self, paths: list[str]) -> str:
        # browser_file_upload 只接受 paths
        return await self.call("browser_file_upload", {"paths": paths})

    async def wait_for(self, time: Optional[float] = None, text: Optional[str] = None) -> str:
        args: dict[str, Any] = {}
        if time is not None:
            args["time"] = time
        if text is not None:
            args["text"] = text
        return await self.call("browser_wait_for", args)

    async def press_key(self, key: str) -> str:
        return await self.call("browser_press_key", {"key": key})

    async def evaluate(self, function: str) -> str:
        # browser_evaluate：function 是一个返回结果的 JS 函数体，如 "() => {...}"
        return await self.call("browser_evaluate", {"function": function})

    async def handle_dialog(self, accept: bool = True) -> str:
        return await self.call("browser_handle_dialog", {"accept": accept})

    async def screenshot(self, filename: str) -> str:
        return await self.call("browser_take_screenshot", {"filename": filename, "type": "png"})


@asynccontextmanager
async def open_browser(user_data_dir: Optional[str] = None, headless: bool = False):
    b = MCPBrowser(user_data_dir=user_data_dir, headless=headless)
    await b.__aenter__()
    try:
        yield b
    finally:
        await b.__aexit__(None, None, None)
