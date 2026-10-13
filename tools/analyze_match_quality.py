"""分析米哈游匹配报告，找出匹配不准确的岗位。"""
import sqlite3
import json

# 1. 从jobs表获取标题
conn = sqlite3.connect(r"D:\x\ai agent\data\agent_state.db")
cur = conn.cursor()
cur.execute("SELECT job_url, job_title, location, category_path FROM jobs WHERE site_name='mihoyo'")
job_info = {}
for row in cur.fetchall():
    job_info[row[0]] = {"title": row[1], "location": row[2], "category": row[3]}
conn.close()

# 2. 读取匹配报告
with open(r"D:\x\ai agent\output\match_report_20261012_220211.json", "r", encoding="utf-8") as f:
    report = json.load(f)

print(f"=== 匹配报告分析 ===")
print(f"总匹配数: {report['total']}")
print(f"生成时间: {report['generated_at']}\n")

# 3. 统计direction=True的岗位
dir_true = [r for r in report["results"] if r.get("direction_match")]
dir_false = [r for r in report["results"] if not r.get("direction_match")]
print(f"方向匹配(direction=True): {len(dir_true)} 个")
print(f"方向不匹配(direction=False): {len(dir_false)} 个\n")

# 4. 列出所有direction=True的岗位，按score排序
print("=== 所有方向匹配的岗位 ===")
dir_true.sort(key=lambda x: x.get("score", 0), reverse=True)
for i, r in enumerate(dir_true):
    url = r["job_url"]
    info = job_info.get(url, {"title": "未知", "location": "", "category": ""})
    score = r.get("score", 0)
    hard = f"{r.get('hard_requirements_met', 0)}/{r.get('hard_requirements_total', 0)}"
    print(f"\n[{i+1}] score={score} 硬性={hard}")
    print(f"  标题: {info['title']}")
    print(f"  地点: {info['location']} | 分类: {info['category']}")
    print(f"  URL: {url}")
    print(f"  方向理由: {r.get('direction_reason', '')[:100]}")
    print(f"  综合评价: {r.get('reason', '')[:120]}")

# 5. 检查是否有实习生岗位被标记为direction=True
print("\n\n=== 可疑岗位分析 ===")
print("\n--- 实习生岗位但direction=True ---")
for r in dir_true:
    url = r["job_url"]
    info = job_info.get(url, {"title": "", "category": ""})
    if "实习" in info["category"] or "实习" in info["title"]:
        print(f"  score={r.get('score')} | {info['title']} | {info['category']}")

print("\n--- 非技术类岗位但direction=True ---")
non_tech_keywords = ["运营", "市场", "商务", "产品", "策划", "美术", "表现", "音频", "国际化", "综合", "采购", "人力", "行政", "财务"]
for r in dir_true:
    url = r["job_url"]
    info = job_info.get(url, {"title": "", "category": ""})
    if any(kw in info["category"] or kw in info["title"] for kw in non_tech_keywords):
        print(f"  score={r.get('score')} | {info['title']} | {info['category']}")

# 6. 检查高分但标题不匹配的岗位
print("\n--- 高分(>=70)但标题不含AI/Agent/算法/开发/工程师 ---")
tech_keywords = ["AI", "Agent", "算法", "开发", "工程师", "研发", "大模型", "LLM", "数据", "程序", "技术"]
for r in dir_true:
    if r.get("score", 0) >= 70:
        url = r["job_url"]
        info = job_info.get(url, {"title": ""})
        if not any(kw.lower() in info["title"].lower() for kw in tech_keywords):
            print(f"  score={r.get('score')} | {info['title']}")
