"""直达投递：给定一个表单链接，用通用 MCP agent 打开并直接填写。

不经过岗位发现/初筛/匹配，也不写站点 selector。
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from src.browser_agent.agent import run_form_agent
from src.browser_agent.context import build_user_context
from src.browser_agent.mcp_client import MCPBrowser
from src.agent.nodes.load_profile import load_profile_from_json, load_resume


def _resolve(path: str, default: str) -> str:
    p = path or default
    if os.path.isabs(p):
        return p
    return str(Path(p).resolve())


async def run_apply(
    url: str,
    profile_path: str = "",
    resume_path: str = "",
    run_id: str = "",
) -> dict:
    # 1. 加载用户资料
    pfile = _resolve(profile_path, "data/user_profile.json")
    rfile = _resolve(resume_path, "data/resume.pdf")

    profile = None
    if os.path.exists(pfile):
        profile = load_profile_from_json(pfile)
    resume = None
    if os.path.exists(rfile):
        os.environ["RESUME_PATH"] = rfile  # upload 动作读取
        resume = load_resume(rfile, profile)

    # 2. 组装上下文（含知识库素材）
    user_context = await build_user_context(profile, resume)

    # 3. 用 MCP 专用持久化浏览器 profile（含登录态；与旧 data/browser_profile 分开）
    mcp_profile = os.getenv("MCP_USER_DATA_DIR", "data/browser_profile_mcp")
    user_data_dir = str(Path(mcp_profile).resolve())
    async with MCPBrowser(user_data_dir=user_data_dir, headless=False) as browser:
        print(f"[直达填表] 打开链接: {url}")
        try:
            result = await run_form_agent(browser, url, user_context, run_id=run_id)
        except BaseException as e:
            _log_chain(e)
            raise

        if result["finished"]:
            print("\n" + "=" * 60)
            print("表单已填写完毕。请在浏览器中检查所有字段，确认无误后")
            print("【手动点击提交按钮】。Agent 不会替你提交。")
            print("=" * 60)
            await asyncio.to_thread(_popup_confirm)
        else:
            print(f"\n[提示] Agent 在 {result['steps']} 步后未确认完成，"
                  f"请在浏览器中检查并手动补全/提交。")
    return result


def _log_chain(e: BaseException) -> None:
    """递归解包 ExceptionGroup / TaskGroup，打印最内层真实异常。"""
    import traceback
    if isinstance(e, BaseExceptionGroup):
        print(f"\n[异常组] {type(e).__name__}: {e}，含 {len(e.exceptions)} 个子异常")
        for sub in e.exceptions:
            _log_chain(sub)
        return
    print(f"\n[根因异常] {type(e).__name__}: {e}")
    print("".join(traceback.format_exception(type(e), e, e.__traceback__)))


def _popup_confirm() -> None:
    """弹窗等待用户确认已手动提交。"""
    import tkinter
    from tkinter import messagebox
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    messagebox.showinfo(
        "求职 Agent",
        "请在浏览器中检查所有字段，确认无误后【手动点击提交】。\n\n"
        "提交完成后点击「确定」。",
        parent=root)
    root.destroy()
