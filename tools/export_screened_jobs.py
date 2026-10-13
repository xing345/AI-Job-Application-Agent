"""导出初筛后的岗位列表（从jobs表+匹配报告合并）。"""
import sqlite3
import json
from datetime import datetime

# 1. 从jobs表获取所有米哈游岗位完整信息
conn = sqlite3.connect(r"D:\x\ai agent\data\agent_state.db")
cur = conn.cursor()
cur.execute("SELECT job_url, job_title, company, location, category_path FROM jobs WHERE site_name='mihoyo'")
all_jobs = {}
for row in cur.fetchall():
    all_jobs[row[0]] = {
        "url": row[0],
        "title": row[1],
        "company": row[2],
        "location": row[3],
        "category_path": row[4],
    }
conn.close()
print(f"jobs表: {len(all_jobs)} 个米哈游岗位")

# 2. 从匹配报告获取初筛通过的157个岗位URL
report_path = r"D:\x\ai agent\output\match_report_20261012_220211.json"
with open(report_path, "r", encoding="utf-8") as f:
    report = json.load(f)

screened_urls = set()
for r in report["results"]:
    screened_urls.add(r["job_url"])
print(f"匹配报告: {len(screened_urls)} 个初筛通过岗位")

# 3. 合并得到初筛后的完整岗位列表
screened_jobs = []
missing = []
for url in screened_urls:
    if url in all_jobs:
        screened_jobs.append(all_jobs[url])
    else:
        missing.append(url)

print(f"合并成功: {len(screened_jobs)} 个岗位完整信息")
if missing:
    print(f"警告: {len(missing)} 个岗位在jobs表中找不到（可能是URL格式差异）")
    for u in missing[:5]:
        print(f"  {u}")

# 4. 按标题排序
screened_jobs.sort(key=lambda x: x["title"])

# 5. 保存为独立文件
output = {
    "site": "mihoyo",
    "generated_at": datetime.now().isoformat(),
    "source": "jobs表 + match_report合并",
    "total_discovered": len(all_jobs),
    "total_screened": len(screened_jobs),
    "jobs": screened_jobs,
}

output_path = r"D:\x\ai agent\output\screened_jobs_mihoyo_20261012.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n已保存: {output_path}")
print(f"文件大小: {len(json.dumps(output, ensure_ascii=False))} 字符")

# 6. 打印前10个岗位预览
print(f"\n=== 前10个岗位预览 ===")
for i, job in enumerate(screened_jobs[:10]):
    print(f"  [{i+1}] {job['title'][:35]:35s} | {job['location'][:8]:8s} | {job['category_path'][:25]}")
