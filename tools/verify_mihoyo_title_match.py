"""验证米哈游目标岗位8925的标题匹配和JD提取（含串岗检测）。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.search.adapters.mihoyo import MihoyoAdapter
from src.search.site_registry import get_site_config
from src.models.job import JobPosting


async def main():
    browser = await get_browser()
    page = browser.page

    # 先测试标题匹配函数
    print("=== 标题匹配函数测试 ===")
    cases = [
        ("基础研究-游戏AI研发工程师（Agent方向）", "基础研究-游戏AI研发工程师（Agent方向）", True),
        ("基础研究-图形研究员（动捕动画方向）", "基础研究-游戏AI研发工程师（Agent方向）", False),
        ("游戏AI研发工程师(Agent方向)", "基础研究-游戏AI研发工程师（Agent方向）", None),
    ]
    for got, exp, want in cases:
        r = MihoyoAdapter._titles_match(got, exp)
        print(f"  match={r} | got='{got}' exp='{exp}'")

    # 模拟连续跳转串岗场景：连续提取3个不同岗位
    config = get_site_config("mihoyo")
    adapter = MihoyoAdapter(config)

    test_jobs = [
        ("8337", "游戏AI研发实习生（Agent方向）"),
        ("8925", "基础研究-游戏AI研发工程师（Agent方向）"),
        ("8919", "基础研究-Agent 算法研究员"),
    ]

    for job_id, title in test_jobs:
        url = f"https://jobs.mihoyo.com/#/campus/position/{job_id}"
        print(f"\n=== {title} (ID={job_id}) ===")
        # 模拟fetch_single_jd的goto
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        posting = JobPosting(title=title, detail_url=url, site_name="mihoyo", company="米哈游")
        detail = await adapter.extract_jd_detail(page, posting)
        if detail:
            print(f"  成功: {detail.posting.title}")
            print(f"  职责={len(detail.responsibilities)} 要求={len(detail.requirements)} 全文={len(detail.full_jd)}")
            # 验证没有串岗
            match = MihoyoAdapter._titles_match(detail.posting.title, title)
            print(f"  标题一致性: {match}")
        else:
            print(f"  提取失败（返回None）")

    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
