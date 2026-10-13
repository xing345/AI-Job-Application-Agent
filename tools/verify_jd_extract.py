"""阶段5 JD详情页提取验证：打开字节跳动岗位详情页，测试适配器提取效果。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.models.job import JobPosting
from src.search.adapters.bytedance import BytedanceAdapter
from src.search.site_registry import get_site_config


async def test():
    print("=== JD详情页提取验证 ===")

    browser = await get_browser()
    page = browser.page
    print("[1] Browser launched OK")

    # 使用从列表页获取的真实岗位 URL
    job_url = "https://jobs.bytedance.com/campus/position/7667878785178552629/detail"
    print(f"[2] Fetching JD: {job_url}")

    try:
        await page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(4000)
        title = await page.title()
        print(f"    Page title: {title}")
        print(f"    Page URL: {page.url}")
    except Exception as e:
        print(f"    Page load FAILED: {e}")
        await close_browser()
        return

    # 测试适配器提取
    config = get_site_config("bytedance")
    adapter = BytedanceAdapter(config)
    base_posting = JobPosting(
        title="XR系统应用开发工程师 - 移动OS",
        detail_url=job_url,
        site_name="bytedance",
    )

    print("\n[3] Testing adapter.extract_jd_detail...")
    try:
        detail = await adapter.extract_jd_detail(page, base_posting)
        if detail:
            print(f"    Title: {detail.posting.title}")
            print(f"    Company: {detail.posting.company}")
            print(f"    Location: {detail.posting.location}")
            print(f"    Category: {detail.posting.category_path}")
            print(f"    Full JD length: {len(detail.full_jd)}")
            print(f"    Responsibilities length: {len(detail.responsibilities)}")
            print(f"    Requirements length: {len(detail.requirements)}")
            print(f"\n    Responsibilities preview:\n{detail.responsibilities[:300]}")
            print(f"\n    Requirements preview:\n{detail.requirements[:300]}")
        else:
            print("    Adapter returned None!")
            # 手动调试：检查页面元素
            print("\n    [Debug] Checking page elements...")
            for sel in adapter.JD_TITLE_SELECTORS:
                try:
                    el = page.locator(sel).first
                    count = await el.count()
                    if count > 0:
                        text = (await el.inner_text()).strip()
                        print(f"    Title selector '{sel}': found, text='{text[:60]}'")
                except Exception as e:
                    print(f"    Title selector '{sel}': error - {e}")

            for sel in adapter.JD_CONTENT_SELECTORS:
                try:
                    el = page.locator(sel).first
                    count = await el.count()
                    if count > 0:
                        text = (await el.inner_text()).strip()
                        print(f"    Content selector '{sel}': found, len={len(text)}")
                        if len(text) > 50:
                            print(f"        preview: {text[:100]}")
                except Exception as e:
                    pass
    except Exception as e:
        print(f"    Extract FAILED: {e}")
        import traceback
        traceback.print_exc()

    await close_browser()
    print("\n=== JD详情页验证完成 ===")


if __name__ == "__main__":
    asyncio.run(test())
