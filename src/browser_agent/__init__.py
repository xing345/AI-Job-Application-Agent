"""通用浏览器 Agent：基于 MCP 协议 + accessibility snapshot 的网页表单填写。"""
from src.browser_agent.mcp_client import MCPBrowser, open_browser
from src.browser_agent.agent import run_form_agent

__all__ = ["MCPBrowser", "open_browser", "run_form_agent"]
