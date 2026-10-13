"""查询数据库中保存的岗位和状态。"""
import sqlite3
import json

conn = sqlite3.connect(r"D:\x\ai agent\data\agent_state.db")
cur = conn.cursor()

# 1. jobs表中的米哈游岗位
cur.execute("SELECT COUNT(*) FROM jobs WHERE site_name='mihoyo'")
count = cur.fetchone()[0]
print(f"=== jobs表: 米哈游岗位 {count} 个 ===")

cur.execute("SELECT job_title, job_url, location, category_path FROM jobs WHERE site_name='mihoyo' ORDER BY id LIMIT 10")
for row in cur.fetchall():
    print(f"  {row[0][:30]:30s} | {row[2][:10]:10s} | {row[3][:20]}")

# 2. agent_state表
cur.execute("SELECT COUNT(*) FROM agent_state")
state_count = cur.fetchone()[0]
print(f"\n=== agent_state表: {state_count} 条记录 ===")

cur.execute("SELECT session_id, node_name, created_at FROM agent_state ORDER BY id DESC LIMIT 5")
for row in cur.fetchall():
    print(f"  session={row[0]} node={row[1]} time={row[2]}")

# 3. 最新的agent_state内容
cur.execute("SELECT state_json FROM agent_state ORDER BY id DESC LIMIT 1")
row = cur.fetchone()
if row:
    state = json.loads(row[0])
    print(f"\n=== 最新状态 keys: {list(state.keys())} ===")
    if 'screened_jobs' in state:
        print(f"  screened_jobs 数量: {len(state['screened_jobs'])}")
    if 'jobs' in state:
        print(f"  jobs 数量: {len(state['jobs'])}")
    if 'discovered_jobs' in state:
        print(f"  discovered_jobs 数量: {len(state['discovered_jobs'])}")
    # 打印所有key的类型和长度
    for k, v in state.items():
        if isinstance(v, list):
            print(f"  {k}: list[{len(v)}]")
        elif isinstance(v, dict):
            print(f"  {k}: dict[{len(v)} keys]")
        else:
            print(f"  {k}: {type(v).__name__} = {str(v)[:50]}")

conn.close()
print("\n查询完成")
