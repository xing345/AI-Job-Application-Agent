"""验证 click/type 工具参数：打开字节登录页，给手机号框 type。"""
import asyncio
import re
from pathlib import Path
from src.browser_agent.mcp_client import MCPBrowser

PROFILE = str(Path("data/browser_profile_mcp").resolve())
LOGIN = "https://jobs.bytedance.com/campus/login"


async def main():
    async with MCPBrowser(user_data_dir=PROFILE, headless=False) as b:
        await b.navigate(LOGIN)
        await b.wait_for(time=2)
        snap = await b.snapshot()
        refs = re.findall(r"\[ref=(e\d+)\]", snap)
        print("refs found:", refs[:6])
        # 找第一个 textbox
        m = re.search(r"textbox[^\n]*\[ref=(e\d+)\]", snap)
        if not m:
            print("no textbox; snapshot:\n", snap[:800])
            return
        ref = m.group(1)
        print("typing into", ref)
        out = await b.type(ref, "15638108926")
        print("TYPE OK:", "error" not in out.lower(), out[:200])
        await b.wait_for(time=1)


asyncio.run(main())
