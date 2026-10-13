"""获取top匹配岗位的详细信息，给用户投递建议。"""
import sqlite3
import json

# 1. 从jobs表获取标题
conn = sqlite3.connect(r"D:\x\ai agent\data\agent_state.db")
cur = conn.cursor()
cur.execute("SELECT job_url, job_title, location, category_path FROM jobs WHERE site_name='mihoyo'")
job_titles = {}
for row in cur.fetchall():
    job_titles[row[0]] = {"title": row[1], "location": row[2], "category": row[3]}
conn.close()

# 2. 从匹配报告获取top岗位
with open(r"D:\x\ai agent\output\match_report_20261012_220211.json", "r", encoding="utf-8") as f:
    report = json.load(f)

# 筛选方向匹配且score>=70的
top_jobs = []
for r in report["results"]:
    if r.get("direction_match") and r.get("score", 0) >= 70:
        url = r["job_url"]
        info = job_titles.get(url, {"title": "未知", "location": "", "category": ""})
        top_jobs.append({
            "url": url,
            "title": info["title"],
            "location": info["location"],
            "category": info["category"],
            "score": r["score"],
            "hard_met": r.get("hard_requirements_met", 0),
            "hard_total": r.get("hard_requirements_total", 0),
            "reason": r.get("reason", ""),
            "matched_points": r.get("matched_points", []),
            "direction_reason": r.get("direction_reason", ""),
        })

top_jobs.sort(key=lambda x: x["score"], reverse=True)

print(f"=== 方向匹配且评分>=70的岗位: {len(top_jobs)} 个 ===\n")

for i, job in enumerate(top_jobs):
    print(f"{'='*70}")
    print(f"【推荐 {i+1}】score={job['score']} | 硬性要求 {job['hard_met']}/{job['hard_total']}")
    print(f"  岗位: {job['title']}")
    print(f"  地点: {job['location']} | 分类: {job['category']}")
    print(f"  URL: {job['url']}")
    print(f"  方向匹配理由: {job['direction_reason']}")
    print(f"  综合评价: {job['reason']}")
    print(f"  匹配点:")
    for p in job["matched_points"][:5]:
        print(f"    - {p[:80]}")
    print()
