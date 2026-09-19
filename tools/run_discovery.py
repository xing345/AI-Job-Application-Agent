"""
职位发现链路实测脚本（人工验证用）

直接跑 BrowserJobFinder.discover_fixed_sites（生产同款路径），
逐站打印抽取结果与耗时，用来验证「为什么抽取到 0 个职位」。

用法：
    python tools/run_discovery.py                  # 全部固定站点，无头
    python tools/run_discovery.py --headed         # 可见浏览器
    python tools/run_discovery.py <url> [url ...]  # 只跑指定站点
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger  # noqa: E402

from src.models.instruction_schemas import TargetInstructionSchema  # noqa: E402
from src.search.browser_job_finder import BrowserJobFinder  # noqa: E402
from src.search.query_expander import expand_role_variants, infer_direction  # noqa: E402
from src.search.site_registry import resolve_sites  # noqa: E402


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    headless = "--headed" not in sys.argv
    if args:
        sites = [{"name": f"站点{i+1}", "url": u, "kind": "company_site"}
                 for i, u in enumerate(args)]
    else:
        sites = resolve_sites()

    # 用生产链路同款的方向推断（JobSearcher 就是这么构造 TargetInstructionSchema 的）
    role = "AI应用开发工程师"
    direction = infer_direction(role)
    target = TargetInstructionSchema(
        company="", role=role, location="",
        direction_family=direction["key"],
        direction_category=direction["category"],
        title_keywords=direction["title_keywords"],
        role_variants=expand_role_variants(role),
        recruit_type="campus",
    )
    finder = BrowserJobFinder(
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        headless=headless, interactive=False, max_jobs_per_site=10,
    )
    t0 = time.time()
    jobs = await finder.discover_fixed_sites(target, sites)
    print(f"\n=== 合计 {len(jobs)} 个职位，耗时 {time.time() - t0:.1f}s ===")
    by_host = {}
    for j in jobs:
        host = j["url"].split("/")[2] if "//" in j["url"] else j["url"]
        by_host.setdefault(host, []).append(j)
    for host, items in by_host.items():
        print(f"\n[{host}] {len(items)} 个")
        for j in items[:12]:
            print(f"   - {j.get('title','')[:50]} | {j['url'][:120]} | {j.get('source')}")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    asyncio.run(main())
