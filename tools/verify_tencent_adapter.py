"""验证腾讯适配器岗位发现（限制5页快速验证）。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.search.adapters.tencent import TencentAdapter
from src.search.site_registry import get_site_config


async def main():
    browser = await get_browser()
    page = browser.page

    config = get_site_config("tencent")
    adapter = TencentAdapter(config)
    adapter.max_pages = 5  # 只跑5页快速验证

    jobs = await adapter.discover_jobs(page)

    print(f"\n=== 验证结果：发现 {len(jobs)} 个岗位 ===")
    for i, job in enumerate(jobs[:15]):
        print(f"  [{i}] {job.title} | {job.location[:30]}")

    # 验证JD提取（取Agent开发工程师）
    target = next((j for j in jobs if "Agent" in j.title), jobs[0])
    print(f"\n=== JD提取验证: {target.title} ===")
    detail = await adapter.extract_jd_detail(page, target)
    if detail:
        print(f"标题: {detail.posting.title}")
        print(f"职责长度: {len(detail.responsibilities)}")
        print(f"要求长度: {len(detail.requirements)}")
        print(f"全文JD长度: {len(detail.full_jd)}")
        print(f"\n职责前100字: {detail.responsibilities[:100]}")
        print(f"\n要求前100字: {detail.requirements[:100]}")
    else:
        print("JD提取失败")

    await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
