"""统计腾讯初筛通过岗位中：青云研究类 vs 普通技术岗（本科可投）的分布。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

import aiosqlite
from src.storage import state_db

RESEARCH = ("研究", "课题")
AI = ("agent", "智能体", "ai", "大模型", "多模态", "算法", "机器学习", "深度学习", "llm", "nlp", "cv")
FULLSTACK = ("全栈", "前端", "后端", "开发", "软件", "客户端", "服务端")


async def main():
    await state_db.init_db()
    async with aiosqlite.connect(state_db._DB_PATH) as db:
        c = await db.execute(
            "SELECT job_title FROM jobs WHERE site_name='tencent' AND passed_screen=1")
        titles = [r[0] or "" for r in await c.fetchall()]

    research, ai_ordinary, dev_ordinary, other = [], [], [], []
    for t in titles:
        low = t.lower()
        if any(w in t for w in RESEARCH):
            research.append(t)
        elif any(w in low for w in AI):
            ai_ordinary.append(t)
        elif any(w in low for w in FULLSTACK):
            dev_ordinary.append(t)
        else:
            other.append(t)

    print(f"腾讯初筛通过总数: {len(titles)}")
    print(f"  青云/研究类(多为博士) : {len(research)}")
    print(f"  普通 AI/算法岗        : {len(ai_ordinary)}")
    print(f"  普通 开发/全栈/前后端 : {len(dev_ordinary)}")
    print(f"  其他                  : {len(other)}")
    print("\n普通AI岗示例:")
    for t in ai_ordinary[:15]:
        print("  -", t)
    print("\n普通开发/全栈岗示例:")
    for t in dev_ordinary[:15]:
        print("  -", t)


asyncio.run(main())
