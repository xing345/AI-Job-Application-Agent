"""统计各站点岗位的缓存覆盖情况。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")
from src.storage import state_db


async def main():
    await state_db.init_db()
    import aiosqlite
    async with aiosqlite.connect(state_db._DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT site_name,
                      COUNT(*) AS total,
                      SUM(CASE WHEN passed_screen=1 THEN 1 ELSE 0 END) AS screened,
                      SUM(CASE WHEN full_jd IS NOT NULL THEN 1 ELSE 0 END) AS jd,
                      SUM(CASE WHEN match_json IS NOT NULL THEN 1 ELSE 0 END) AS matched
               FROM jobs GROUP BY site_name ORDER BY total DESC""")
        print(f"{'site':<12}{'total':>6}{'screen':>7}{'jd':>6}{'match':>6}")
        for r in await cursor.fetchall():
            print(f"{r['site_name']:<12}{r['total']:>6}{r['screened']:>7}{r['jd']:>6}{r['matched']:>6}")


asyncio.run(main())
