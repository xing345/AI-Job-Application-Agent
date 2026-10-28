"""离线验证方向优先级排序效果（字节/腾讯）。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.storage import state_db
from src.agent.nodes.screen_titles import prioritize_jobs, title_priority_score


def _posting(row, site):
    from src.models.job import JobPosting
    return JobPosting(
        title=row.get("job_title") or "", company=row.get("company") or "",
        location=row.get("location") or "", detail_url=row["job_url"],
        category_path=row.get("category_path") or "",
        site_name=row.get("site_name") or site)


async def check(site):
    rows = await state_db.get_site_job_postings(site)
    jobs = [_posting(r, site) for r in rows]
    top = prioritize_jobs(jobs, 80)
    print("=" * 90)
    print(f"{site}: 库中 {len(jobs)} -> 深度处理 {len(top)}")
    print("=" * 90)
    print("【Top 20】")
    for j in top[:20]:
        print(f"  {title_priority_score(j.title):>4}  {j.title[:60]}")
    # 80 构成统计
    intern = sum(1 for j in top if "实习" in j.title)
    research = sum(1 for j in top if title_priority_score(j.title) < 0)
    print(f"\n80个中: 实习岗 {intern}，负分(研究/硬件类) {research}")
    print("【末5】")
    for j in top[-5:]:
        print(f"  {title_priority_score(j.title):>4}  {j.title[:60]}")


async def main():
    await state_db.init_db()
    await check("bytedance")
    print()
    await check("tencent")


asyncio.run(main())
