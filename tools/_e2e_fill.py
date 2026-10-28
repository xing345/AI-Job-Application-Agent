"""真实端到端：进入腾讯简历表单 -> LLM生成值 -> 填写，统计成功率（不提交）。"""
import asyncio
import os
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser
from src.agent.nodes.fill_application import (
    enter_application_page, prepare_form, discover_form_fields,
    llm_generate_values, fill_fields)
from src.models.profile import UserProfile
from src.models.job import JobDetail, JobPosting
from src.models.match import FillStatus

POSTID = "1284634302709277696"
DETAIL = f"https://join.qq.com/post_detail.html?postid={POSTID}"


async def main():
    profile = UserProfile.model_validate_json(
        open(r"D:\x\ai agent\data\user_profile.json", encoding="utf-8").read())

    os.environ["BROWSER_PROFILE_SUFFIX"] = "tencent"
    browser = await get_browser()
    page = browser.page
    await page.wait_for_timeout(800)

    posting = JobPosting(title="财经线培训生-AI应用开发", company="腾讯",
                         detail_url=DETAIL, site_name="tencent")
    job = JobDetail(posting=posting, apply_url=DETAIL)

    entered = await enter_application_page(page, job)
    print("进入申请页:", entered, "| URL:", page.url)
    if "login" in page.url:
        print("!! 需要登录，本次终止（请先在交互式运行中扫码）")
        await close_browser(); return

    await prepare_form(page, profile)
    fields = await discover_form_fields(page)
    print("发现字段:", len(fields))

    resume_text = profile.to_resume_text()
    fields = await llm_generate_values(
        fields, resume_text, resume_text, posting.title,
        job.jd_for_match() or resume_text, run_id="e2e")

    withvals = sum(1 for f in fields if f.value is not None)
    print("LLM 给出非空值字段:", withvals, "/", len(fields))

    fields = await fill_fields(page, fields)

    cnt = {s: sum(1 for f in fields if f.status == s) for s in FillStatus}
    print("\n=== 填写结果 ===")
    for s in FillStatus:
        print(f"  {s.value}: {cnt[s]}")

    print("\n失败/需人工字段:")
    for f in fields:
        if f.status in (FillStatus.FAILED, FillStatus.NEEDS_USER_INPUT):
            print(f"  [{f.status.value}] {(f.label or f.name)[:22]}: {f.error[:60]}")

    await page.screenshot(path=r"D:\x\ai agent\tools\_e2e_result.png", full_page=False)
    print("\n截图: tools\\_e2e_result.png")
    await asyncio.sleep(3)
    await close_browser()


asyncio.run(main())
