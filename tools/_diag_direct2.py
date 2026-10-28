"""直接管理 node MCP：立即初始化，收集 stderr，报告 node 退出原因。"""
import asyncio
import json
from pathlib import Path

CLI = r"C:\Users\Administrator\AppData\Local\Doubao\User Data\sandbox_runtime\bases\772984f6fd3a8ae0ae7d2422cd7c2bfa\node\node_modules\@playwright\mcp\cli.js"
PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"


async def main():
    proc = await asyncio.create_subprocess_exec(
        "node", CLI, "--user-data-dir", PROFILE,
        "--image-responses", "omit",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    stderr_lines = []

    async def read_err():
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            s = line.decode("utf-8", "replace").rstrip()
            stderr_lines.append(s)
            print("[stderr]", s)

    async def read_out():
        while True:
            line = await proc.stdout.readline()
            if not line:
                print("[stdout EOF]")
                return
            print("[stdout]", line.decode("utf-8", "replace")[:200].rstrip())

    t_err = asyncio.create_task(read_err())
    t_out = asyncio.create_task(read_out())

    counter = 0

    async def send(method, params=None):
        nonlocal counter
        counter += 1
        msg = {"jsonrpc": "2.0", "id": counter, "method": method, "params": params or {}}
        proc.stdin.write((json.dumps(msg) + "\n").encode())
        await proc.stdin.drain()

    # 立即 initialize
    await send("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                              "clientInfo": {"name": "diag", "version": "1.0"}})
    proc.stdin.write((json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode())
    await proc.stdin.drain()
    print("initialize sent")
    await asyncio.sleep(2)
    print("after init, returncode:", proc.returncode)

    # navigate
    await asyncio.sleep(1)
    if proc.returncode is not None:
        print("node exited early")
    else:
        await send("tools/call", {"name": "browser_navigate", "arguments": {"url": URL}})
        print("navigate sent")
        await asyncio.sleep(6)
        print("after navigate, returncode:", proc.returncode)

    # 等 node 退出
    wait_task = asyncio.create_task(proc.wait())
    done, pending = await asyncio.wait([wait_task], timeout=15)
    if wait_task in done:
        print("node returncode:", proc.returncode)
    else:
        print("node 仍存活，15秒后终止")
        proc.terminate()
        await proc.wait()

    print("===== 全部 stderr =====")
    for s in stderr_lines:
        print(s)


asyncio.run(main())
