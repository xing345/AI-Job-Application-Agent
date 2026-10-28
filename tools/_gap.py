"""核对各站点新优先级Top80中：已有JD缓存数、已有匹配数，确定补抓工作量。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

import aiosqlite
from src.storage import state_db
from src.agent.nodes.screen_titles import prioritize_jobs
from src.models.job import JobPosting


async def main():
    await state_db.init_db()
    for site in ("bytedance", "tencent"):
        async with aiosqlite.connect(state_db._DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            c = await db.execute(
                "SELECT job_url,job_title,company,location,category_path,site_name,"
                "full_jd,match_json FROM jobs WHERE site_name=? AND passed_screen=1", (site,))
            rows = await c.fetchall()

        jobs = [JobPosting(
            title=r["job_title"] or "", company=r["company"] or "",
            location=r["location"] or "", detail_url=r["job_url"],
            category_path=r["category_path"] or "", site_name=r["site_name"]) for r in rows]
        by_url = {r["job_url"]: r for r in rows}
        top = prioritize_jobs(jobs, 80)

        has_jd = sum(1 for j in top if by_url[j.detail_url]["full_jd"])
        has_match = sum(1 for j in top if by_url[j.detail_url]["match_json"])
        print(f"[{site}] 新Top{len(top)}: 已有JD {has_jd}（待抓 {len(top)-has_jd}），已有匹配 {has_match}（待匹配 {len(top)-has_match}）")


asyncio.run(main())
