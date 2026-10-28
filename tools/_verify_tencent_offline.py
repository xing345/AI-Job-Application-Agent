"""离线验证腾讯缓存：重建JD，统计普通岗/课题岗、切分完整率、方向聚焦。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

import aiosqlite
from src.storage import state_db

AI_WORDS = ("agent", "智能体", "ai", "大模型", "多模态", "强化学习", "算法", "机器学习",
            "深度学习", "llm", "游戏ai", "cua", "infra", "code")
NON_TECH = ("运营", "市场", "销售", "人力", "行政", "财务", "法务", "产品经理")


async def main():
    await state_db.init_db()
    async with aiosqlite.connect(state_db._DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        c = await db.execute(
            """SELECT job_title, full_jd, responsibilities, requirements
               FROM jobs WHERE site_name='tencent' AND full_jd IS NOT NULL""")
        rows = await c.fetchall()

    topic = ordinary = split_ok = ai_focus = nontech = 0
    print(f"腾讯缓存可重建JD: {len(rows)} 个\n")
    for r in rows:
        t = r["job_title"] or ""
        full = r["full_jd"] or ""
        if "课题描述" in full or "课题要求" in full:
            topic += 1
        else:
            ordinary += 1
        if (r["responsibilities"] or "").strip() and (r["requirements"] or "").strip():
            split_ok += 1
        low = t.lower()
        if any(w in low for w in AI_WORDS):
            ai_focus += 1
        if any(w in t for w in NON_TECH) and not any(w in low for w in ("开发", "工程", "技术")):
            nontech += 1

    print(f"  青云课题岗        : {topic}")
    print(f"  普通岗            : {ordinary}")
    print(f"  职责+要求切分完整 : {split_ok}")
    print(f"  AI/技术方向       : {ai_focus}")
    print(f"  纯非技术岗(应=0)  : {nontech}")
    print("\n前12个岗位标题:")
    for r in rows[:12]:
        print("  -", r["job_title"])


asyncio.run(main())
