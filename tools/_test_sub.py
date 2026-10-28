import asyncio


async def t():
    p = await asyncio.create_subprocess_exec(
        "node", "--version",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    print("stdin:", p.stdin)
    out = await p.stdout.read()
    print("node version:", out.decode().strip())


asyncio.run(t())
