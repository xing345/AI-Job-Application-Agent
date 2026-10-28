"""直接子进程方式编排城市操作，检测哪一步让 node 崩溃。"""
import asyncio
import json
import re
from pathlib import Path

CLI = r"C:\Users\Administrator\AppData\Local\Doubao\User Data\sandbox_runtime\bases\772984f6fd3a8ae0ae7d2422cd7c2bfa\node\node_modules\@playwright\mcp\cli.js"
PROFILE = str(Path("data/browser_profile_mcp").resolve())
URL = "https://jobs.bytedance.com/campus/resume/7698959353864505653/apply?spread=DWA3PQP"

SET_JS = ("() => { const i=document.querySelector('.atsx-select-search__field');"
          "i.focus(); const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
          "s.call(i,'上海'); i.dispatchEvent(new Event('input',{bubbles:true})); }")


async def main():
    proc = await asyncio.create_subprocess_exec(
        "node", CLI, "--user-data-dir", PROFILE, "--image-responses", "omit",
        "--timeout-action", "30000",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    async def read_err():
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            print("[stderr]", line.decode("utf-8", "replace").rstrip())

    asyncio.create_task(read_err())

    counter = 0
    pending = {}

    async def reader():
        while True:
            line = await proc.stdout.readline()
            if not line:
                print("[stdout EOF] node 关闭")
                for f in pending.values():
                    if not f.done():
                        f.set_exception(RuntimeError("node closed"))
                return
            msg = json.loads(line)
            if "id" in msg and msg["id"] in pending:
                pending[msg["id"]].set_result(msg)

    asyncio.create_task(reader())

    async def request(method, params=None):
        nonlocal counter
        counter += 1
        mid = counter
        fut = asyncio.get_event_loop().create_future()
        pending[mid] = fut
        req = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}
        proc.stdin.write((json.dumps(req) + "\n").encode())
        await proc.stdin.drain()
        return await asyncio.wait_for(fut, timeout=45)

    async def call(name, args=None):
        r = await request("tools/call", {"name": name, "arguments": args or {}})
        res = r.get("result", {})
        text = "".join(c.get("text", "") for c in res.get("content", []))
        if res.get("isError"):
            print(f"[tool error] {name}: {text[:200]}")
        return text

    await request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "diag", "version": "1.0"}})
    proc.stdin.write((json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode())
    await proc.stdin.drain()

    await call("browser_navigate", {"url": URL})
    await asyncio.sleep(3)
    print("navigated, node alive:", proc.returncode is None)

    # 展开城市
    await call("browser_click", {"target": "e112", "element": "意向城市"})
    await asyncio.sleep(1)
    print("clicked city, alive:", proc.returncode is None)

    # 原生 setter
    await call("browser_evaluate", {"function": SET_JS})
    await asyncio.sleep(3)
    print("evaluate done, alive:", proc.returncode is None)

    # snapshot 找北京 ref
    snap = await call("browser_snapshot", {})
    m = re.search(r'option "北京" \[ref=(e\d+)\]', snap)
    ref = m.group(1) if m else None
    print("北京 ref:", ref)

    if ref:
        await call("browser_click", {"target": ref, "element": "北京选项"})
        await asyncio.sleep(2)
        print("clicked 北京, alive:", proc.returncode is None)

    # 连续做更多 type（模拟 agent 填字段）
    for tgt in ["e160", "e181", "e193"]:
        try:
            await call("browser_type", {"target": tgt, "element": tgt, "text": "测试"})
            print(f"typed {tgt}, alive:", proc.returncode is None)
        except Exception as e:
            print(f"type {tgt} failed: {type(e).__name__}: {e}")
        await asyncio.sleep(1)

    print("final alive:", proc.returncode is None)
    proc.terminate()
    await proc.wait()


asyncio.run(main())
