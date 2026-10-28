"""验证岗位发现+初筛的缓存复用（两轮对比）。"""
import asyncio
import time
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.agent.state import AgentState
from src.agent.nodes import discover_jobs, screen_titles
from src.browser.manager import get_browser, close_browser
from src.storage import state_db


async def build():
    return AgentState(site_name="mihoyo", run_id="screentest")


async def main():
    await state_db.init_db()
    await get_browser()

    print("=" * 60)
    print("第一轮：真实初筛（先重置初筛标记）")
    print("=" * 60)
    s1 = await build()
    await state_db.reset_screen_flags("mihoyo")  # 强制真实初筛
    t0 = time.time()
    await discover_jobs.run(s1)
    await screen_titles.run(s1)
    r1 = time.time() - t0
    print(f"第一轮: {r1:.1f}s discovered={len(s1.discovered_jobs)} screened={len(s1.screened_jobs)}")

    print("\n" + "=" * 60)
    print("第二轮：应全部命中缓存")
    print("=" * 60)
    s2 = await build()
    t0 = time.time()
    await discover_jobs.run(s2)
    await screen_titles.run(s2)
    r2 = time.time() - t0
    print(f"第二轮: {r2:.1f}s discovered={len(s2.discovered_jobs)} screened={len(s2.screened_jobs)}")

    set1 = {j.detail_url: j.title for j in s1.screened_jobs}
    set2 = {j.detail_url: j.title for j in s2.screened_jobs}
    only1 = set(set1) - set(set2)
    only2 = set(set2) - set(set1)
    print("\n" + "=" * 60)
    print(f"集合一致(忽略顺序): {set(set1) == set(set2)}")
    if only1:
        print(f"仅第一轮有 ({len(only1)}):")
        for u in list(only1)[:10]:
            print(f"  {set1[u]}")
    if only2:
        print(f"仅第二轮有 ({len(only2)}):")
        for u in list(only2)[:10]:
            print(f"  {set2[u]}")
    print(f"提速: {r1/max(r2,0.1):.0f}x（{r1:.1f}s -> {r2:.1f}s）")

    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
