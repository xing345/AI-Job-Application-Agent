"""离线修复腾讯已缓存JD：课题/普通岗重新切分补全，无效/已下架岗清空缓存。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

import aiosqlite
from src.storage import state_db
from src.search.site_registry import get_site_config
from src.search.adapters.tencent import TencentAdapter


async def main():
    await state_db.init_db()
    ad = TencentAdapter(get_site_config("tencent"))

    fixed = 0
    cleared = 0
    async with aiosqlite.connect(state_db._DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        c = await db.execute(
            "SELECT job_url, job_title, full_jd FROM jobs WHERE site_name='tencent' AND full_jd IS NOT NULL")
        rows = await c.fetchall()

        for r in rows:
            url = r["job_url"]
            title = r["job_title"] or ""
            full_jd = r["full_jd"] or ""
            lines = [l.strip() for l in full_jd.split("\n") if l.strip()]
            valid = (
                "岗位已下架" not in full_jd
                and ad._has_jd_keywords(full_jd)
                and ad._page_has_title(lines, title)
            )
            if valid:
                resp, req, _ = ad._split_jd_sections(full_jd)
                if resp or req:
                    jd_hash = state_db._compute_jd_hash(full_jd)
                    await db.execute(
                        """UPDATE jobs SET full_jd=?, responsibilities=?, requirements=?,
                                  jd_hash=?, jd_fetched_at=? WHERE job_url=?""",
                        (full_jd, resp, req, jd_hash,
                         __import__("datetime").datetime.now().isoformat(), url))
                    fixed += 1
                else:
                    print("切分仍为空:", title)
            else:
                await db.execute(
                    """UPDATE jobs SET full_jd=NULL, responsibilities='', requirements='',
                              jd_hash='', jd_fetched_at=NULL, match_json=NULL, matched_at=NULL
                       WHERE job_url=?""", (url,))
                cleared += 1
        await db.commit()

    print(f"腾讯缓存JD总数 {len(rows)}：重新切分补全 {fixed}，无效清空 {cleared}")


asyncio.run(main())
