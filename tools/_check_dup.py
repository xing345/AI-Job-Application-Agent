import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")
from src.storage import state_db
import aiosqlite


async def main():
    await state_db.init_db()
    async with aiosqlite.connect(state_db._DB_PATH) as db:
        for site, kw in [("bytedance", "AI全栈开发工程师（电商/前后端）"),
                        ("bytedance", "AI全栈开发工程师（客户端方向） - TikTok研发"),
                        ("tencent", "AI全栈工程师"),
                        ("tencent", "AI应用工程师")]:
            c = await db.execute(
                "SELECT job_url, location FROM jobs WHERE site_name=? AND job_title=?",
                (site, kw))
            rows = await c.fetchall()
            print(f"\n[{site}] {kw}  ({len(rows)}条)")
            for u, loc in rows:
                print(f"   {loc or '-':<8} {u}")


asyncio.run(main())
