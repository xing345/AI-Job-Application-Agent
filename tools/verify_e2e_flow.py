"""阶段5端到端流程验证：发现→初筛→JD抓取→匹配→确认。

手动驱动各节点，验证完整流程连接和数据流转。
"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.agent.state import AgentState
from src.agent.nodes.load_profile import run as load_profile
from src.agent.nodes.discover_jobs import run as discover_jobs
from src.agent.nodes.screen_titles import run as screen_titles
from src.agent.nodes.fetch_jd import run as fetch_jd
from src.agent.nodes.match_jobs import run as match_jobs, print_match_table
from src.models.profile import UserProfile
from src.browser.manager import get_browser, close_browser


async def main():
    print("=" * 70)
    print("阶段5 端到端流程验证")
    print("=" * 70)

    # 构造初始 state
    state = AgentState(
        run_id="e2e_test",
        site_name="bytedance",
    )

    # 加载用户画像
    print("\n[1/6] 加载用户画像...")
    try:
        import json
        with open(r"D:\x\ai agent\data\user_profile.json", "r", encoding="utf-8") as f:
            profile_data = json.load(f)
        state.profile = UserProfile(**profile_data)
        print(f"  姓名: {state.profile.name}")
        print(f"  目标方向: {state.profile.target_directions}")
        print(f"  目标城市: {state.profile.target_cities}")
    except Exception as e:
        print(f"  画像加载失败: {e}，使用默认画像")
        state.profile = UserProfile(
            name="测试用户",
            target_directions=["前端开发", "后端开发", "AI算法"],
            target_cities=["北京", "深圳"],
        )

    # 启动浏览器
    print("\n[2/6] 启动浏览器并发现岗位...")
    browser = await get_browser()
    print(f"  浏览器已启动")

    try:
        # 节点1：岗位发现
        state = await discover_jobs(state)
        print(f"  发现岗位数: {len(state.discovered_jobs)}")
        if state.discovered_jobs:
            print(f"  第一个岗位: {state.discovered_jobs[0].title}")
            print(f"  第一个岗位URL: {state.discovered_jobs[0].detail_url}")
            print(f"  第一个岗位地点: {state.discovered_jobs[0].location}")
            print(f"  第一个岗位公司: {state.discovered_jobs[0].company}")
        if state.errors:
            print(f"  错误: {state.errors[-1]}")

        # 节点2：标题初筛
        print(f"\n[3/6] 标题语义初筛 ({len(state.discovered_jobs)}个岗位)...")
        state = await screen_titles(state)
        print(f"  初筛后岗位数: {len(state.screened_jobs)}")
        if state.screened_jobs:
            print(f"  前3个相关岗位:")
            for j in state.screened_jobs[:3]:
                print(f"    - {j.title}")
        if state.errors:
            print(f"  错误: {state.errors[-1]}")

        # 限制 JD 抓取数量（避免太慢）
        max_jd = 3
        if len(state.screened_jobs) > max_jd:
            print(f"\n  限制只抓取前 {max_jd} 个 JD（加速验证）")
            state.screened_jobs = state.screened_jobs[:max_jd]

        # 节点3：JD抓取
        print(f"\n[4/6] 抓取JD详情 ({len(state.screened_jobs)}个岗位)...")
        state = await fetch_jd(state)
        print(f"  成功抓取JD数: {len(state.job_details)}")
        for i, detail in enumerate(state.job_details):
            print(f"  [{i}] {detail.posting.title}")
            print(f"      地点: {detail.posting.location}, 公司: {detail.posting.company}")
            print(f"      JD长度: {len(detail.full_jd)}, 职责: {len(detail.responsibilities)}, 要求: {len(detail.requirements)}")
        if state.errors:
            print(f"  错误: {state.errors[-1]}")

        # 节点4：JD匹配
        print(f"\n[5/6] LLM深度匹配 ({len(state.job_details)}个岗位)...")
        state = await match_jobs(state)
        print(f"  匹配结果数: {len(state.match_results)}")
        print_match_table(state.match_results)

        # 打印匹配详情
        for i, match in enumerate(state.match_results[:3]):
            print(f"\n  [{i}] {match.job_title} (分数:{match.score})")
            print(f"      方向匹配: {'是' if match.direction_match else '否'}")
            print(f"      硬性要求: {match.hard_requirements_met}/{match.hard_requirements_total}")
            if match.matched_points:
                print(f"      匹配点: {'; '.join(match.matched_points[:3])}")
            if match.missing_points:
                print(f"      缺失点: {'; '.join(match.missing_points[:3])}")

        # 节点5：用户确认（自动选择 top1）
        print(f"\n[6/6] 用户确认（自动选择 top1）...")
        if state.match_results:
            top_job_url = state.match_results[0].job_url
            top_detail = next((d for d in state.job_details if d.posting.detail_url == top_job_url), None)
            if top_detail:
                state.apply_queue = [top_detail]
                state.current_job_index = 0
                print(f"  已选择: {top_detail.posting.title}")
                print(f"  投递队列: {len(state.apply_queue)} 个岗位")
            else:
                print(f"  未找到 top 岗位详情")
        else:
            print("  无匹配结果")

        print("\n" + "=" * 70)
        print("端到端流程验证完成（发现→初筛→JD抓取→匹配→确认）")
        print("=" * 70)
        print(f"\n汇总:")
        print(f"  发现岗位: {len(state.discovered_jobs)}")
        print(f"  初筛通过: {len(state.screened_jobs)}")
        print(f"  JD抓取成功: {len(state.job_details)}")
        print(f"  匹配结果: {len(state.match_results)}")
        print(f"  投递队列: {len(state.apply_queue)}")
        if state.match_results:
            print(f"  最高匹配分: {state.match_results[0].score}")
        print(f"  错误数: {len(state.errors)}")

    finally:
        await close_browser()
        print("\n浏览器已关闭")


if __name__ == "__main__":
    asyncio.run(main())
