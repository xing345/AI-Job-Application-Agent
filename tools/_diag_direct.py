"""直接管理 node MCP 子进程，捕获退出码与 stderr，定位崩溃原因。"""
import asyncio
import json
import os
from pathlib import Path

CLI = r"C:\Users\Administrator\AppData\Local\Doubao\User Data\sandbox_runtime\bases\772984f6fd3a8ae0ae7d2422cd7c2bfa\node\node_modules\@playwright\mcp\cli.js"
PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"


class DirectMCP:
    def __init__(self):
        self.proc = None
        self._id = 0
        self._waiters = {}

    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            "node", CLI, "--user-data-dir", PROFILE,
            "--image-responses", "omit",
            "--timeout-action", "30000",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        asyncio.create_task(self._read_stdout())
        asyncio.create_task(self._read_stderr())

    async def _read_stdout(self):
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                print("[node stdout EOF] 进程关闭了输出")
                return
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if "id" in msg and msg["id"] in self._waiters:
                self._waiters[msg["id"]].set_result(msg)

    async def _read_stderr(self):
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                print("[node stderr EOF]")
                return
            print("[node stderr]", line.decode("utf-8", "replace").rstrip())

    async def call(self, name, args=None):
        self._id += 1
        mid = self._id
        fut = asyncio.get_event_loop().create_future()
        self._waiters[mid] = fut
        req = {"jsonrpc": "2.0", "id": mid, "method": "tools/call",
               "params": {"name": name, "arguments": args or {}}}
        await self.proc.stdin.write((json.dumps(req) + "\n").encode())
        msg = await asyncio.wait_for(fut, timeout=60)
        return msg

    async def notify(self, method, params=None):
        n = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        await self.proc.stdin.write((json.dumps(n) + "\n").encode())

    async def initialize(self):
        self._id += 1
        mid = self._id
        fut = asyncio.get_event_loop().create_future()
        self._waiters[mid] = fut
        req = {"jsonrpc": "2.0", "id": mid, "method": "initialize",
               "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                          "clientInfo": {"name": "diag", "version": "1.0"}}}
        await self.proc.stdin.write((json.dumps(req) + "\n").encode())
        await fut
        await self.notify("notifications/initialized")


async def main():
    d = DirectMCP()
    await d.start()
    await asyncio.sleep(2)
    if d.proc.returncode is not None:
        print(f"node 启动即退出 returncode={d.proc.returncode}")
        err = await d.proc.stderr.read()
        print("stderr:", err.decode("utf-8", "replace"))
        return
    print("node 运行中，stdin:", d.proc.stdin)
    await d.initialize()
    print("initialized")
    await d.call("browser_navigate", {"url": URL})
    print("navigated")
    await asyncio.sleep(3)
    # 做一组会触发问题的操作：展开城市、点选项
    for i in range(8):
        try:
            snap = await d.call("browser_snapshot", {})
            text = json.dumps(snap)
            print(f"round {i}: snapshot len={len(text)}")
        except asyncio.TimeoutError:
            print(f"round {i}: timeout")
        except Exception as e:
            print(f"round {i}: error {type(e).__name__}: {e}")
        await asyncio.sleep(1)

    # 等 node 退出
    await asyncio.sleep(2)
    if d.proc.returncode is None:
        print("node 仍在运行，终止")
        d.proc.terminate()
    else:
        print(f"node 已退出，returncode={d.proc.returncode}")
    await asyncio.sleep(1)


asyncio.run(main())
