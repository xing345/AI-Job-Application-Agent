"""端到端验证分阶段缓存：同样3个岗位跑两轮，对比耗时与缓存命中。"""
import asyncio
import time
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.agent.state import AgentState
from src.agent.nodes import fetch_jd, match_jobs, load_profile
from src.browser.manager import get_browser, close_browser
from src.models.job import JobPosting
from src.storage import state_db

TEST_JOBS = [
    ("8925", "基础研究-游戏AI研发工程师（Agent方向）"),
    ("9560", "平台研发-Agent开发工程师"),
    ("8919", "基础研究-Agent 算法研究员"),
]


def make_postings():
    out = []
    for job_id, title in TEST_JOBS:
        out.append(JobPosting(
            title=title, company="米哈游",
            detail_url=f"https://jobs.mihoyo.com/#/campus/position/{job_id}",
            category_path="程序&技术类 / 全职", site_name="mihoyo"))
    return out


async def build_state():
    state = AgentState(site_name="mihoyo", run_id="cachetest")
    state.screened_jobs = make_postings()
    state.profile = load_profile.load_profile_from_json(
        r"D:\x\ai agent\data\user_profile.json")
    state.resume = load_profile.load_resume(
        r"D:\x\ai agent\data\resume.pdf", state.profile)
    return state


async def main():
    await state_db.init_db()
    browser = await get_browser()

    # 第一轮
    print("=" * 70)
    print("第一轮（可能实际抓取 JD + 调用 LLM）")
    print("=" * 70)
    state1 = await build_state()
    t0 = time.time()
    await fetch_jd.run(state1)
    await match_jobs.run(state1)
    round1 = time.time() - t0
    print(f"第一轮耗时: {round1:.1f} 秒")
    print(f"第一轮结果: {[(r.job_title[:20], r.score) for r in state1.match_results]}")

    # 第二轮（全新 state，同样岗位）
    print("\n" + "=" * 70)
    print("第二轮（应全部命中缓存，秒过）")
    print("=" * 70)
    state2 = await build_state()
    t0 = time.time()
    await fetch_jd.run(state2)
    await match_jobs.run(state2)
    round2 = time.time() - t0
    print(f"第二轮耗时: {round2:.1f} 秒")
    print(f"第二轮结果: {[(r.job_title[:20], r.score) for r in state2.match_results]}")

    # 一致性校验
    s1 = sorted([(r.job_url, r.score) for r in state1.match_results])
    s2 = sorted([(r.job_url, r.score) for r in state2.match_results])
    print("\n" + "=" * 70)
    print(f"两轮结果一致: {s1 == s2}")
    print(f"提速: {round1/max(round2,0.1):.0f} 倍（{round1:.1f}s -> {round2:.1f}s）")

    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
