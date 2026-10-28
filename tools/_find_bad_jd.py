import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")
from src.storage import state_db
import aiosqlite

GOOD = ("岗位描述", "岗位职责", "工作职责", "岗位要求", "任职要求",
        "课题描述", "课题要求")


async def main():
    await state_db.init_db()
    async with aiosqlite.connect(state_db._DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        c = await db.execute(
            "SELECT job_url, job_title, full_jd FROM jobs WHERE site_name='tencent' AND full_jd IS NOT NULL")
        bad = []
        for r in await c.fetchall():
            jd = r["full_jd"] or ""
            if not any(k in jd for k in GOOD):
                bad.append((r["job_url"], r["job_title"], jd[:60]))
        print(f"腾讯已缓存JD中坏数据(无岗位描述/要求): {len(bad)} 个")
        for url, title, head in bad:
            print(f"  {title} | {head} | {url}")


asyncio.run(main())
