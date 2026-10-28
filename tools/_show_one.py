import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")
from src.storage import state_db
import aiosqlite


async def show(postid):
    await state_db.init_db()
    async with aiosqlite.connect(state_db._DB_PATH) as db:
        c = await db.execute(
            "SELECT job_title, full_jd, responsibilities, requirements FROM jobs WHERE job_url LIKE ?",
            (f"%{postid}%",))
        r = await c.fetchone()
        print("标题:", r[0])
        print("=" * 70)
        print("【full_jd 全文】 长度:", len(r[1] or ""))
        print(r[1])
        print("=" * 70)
        print("【responsibilities】:", repr(r[2]))
        print("【requirements】:", repr(r[3]))


asyncio.run(show("1274481034578500642"))
