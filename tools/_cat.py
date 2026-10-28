import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")
import aiosqlite
from src.storage import state_db


async def m():
    await state_db.init_db()
    async with aiosqlite.connect(state_db._DB_PATH) as db:
        c = await db.execute(
            "SELECT job_title,category_path FROM jobs WHERE job_url LIKE ?",
            ("%1274481034578500642%",))
        r = await c.fetchone()
        print("课题岗:", r[0], "=>", repr(r[1]))

        c = await db.execute(
            "SELECT job_title,category_path FROM jobs WHERE site_name='tencent' "
            "AND (job_title LIKE '%Agent开发%' OR job_title LIKE '%AI全栈%' OR job_title LIKE '%AI应用%')")
        for r in await c.fetchall():
            print("普通岗:", r[0], "=>", repr(r[1]))


asyncio.run(m())
