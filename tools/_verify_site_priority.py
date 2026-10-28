"""离线验证指定站点新优先级：初筛通过岗位重排后 Top80 的构成。用法: python _verify_site_priority.py <site>"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

import aiosqlite
from src.storage import state_db
from src.agent.nodes.screen_titles import prioritize_jobs
from src.models.job import JobPosting


async def main(site: str):
    await state_db.init_db()
    async with aiosqlite.connect(state_db._DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        c = await db.execute(
            "SELECT job_url,job_title,company,location,category_path,site_name "
            "FROM jobs WHERE site_name=? AND passed_screen=1", (site,))
        rows = await c.fetchall()

    jobs = [JobPosting(
        title=r["job_title"] or "", company=r["company"] or "",
        location=r["location"] or "", detail_url=r["job_url"],
        category_path=r["category_path"] or "", site_name=r["site_name"]) for r in rows]

    top = prioritize_jobs(jobs, 80)
    qing = sum(1 for j in top if "青云" in (j.category_path or ""))
    print(f"[{site}] 初筛通过 {len(jobs)}，去重+优先级后 Top{len(top)}：普通岗 {len(top) - qing}，青云课题 {qing}")
    print("Top 20:")
    for i, j in enumerate(top[:20], 1):
        tag = "[青云]" if "青云" in (j.category_path or "") else "      "
        print(f"  {i:2d}. {tag} {j.title}  ({j.location})")


asyncio.run(main(sys.argv[1]))
