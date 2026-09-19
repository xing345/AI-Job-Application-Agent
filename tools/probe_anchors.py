"""
锚点诊断探针：解释某个列表页「为什么一个职位都没入库」。

对每个锚点打印：评分 / 是否命中方向词族 / 是否被判为职位详情，
以及类别导航最终选中了哪个链接。

用法：python tools/probe_anchors.py <list_url> [role]
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright  # noqa: E402

from src.models.instruction_schemas import TargetInstructionSchema  # noqa: E402
from src.search.browser_job_finder import BrowserJobFinder  # noqa: E402
from src.search.query_expander import infer_direction  # noqa: E402


async def main():
    url = sys.argv[1]
    role = sys.argv[2] if len(sys.argv) > 2 else "AI应用开发工程师"
    d = infer_direction(role)
    target = TargetInstructionSchema(
        company="", role=role, location="", direction_family=d["key"],
        direction_category=d["category"], title_keywords=d["title_keywords"],
    )
    finder = BrowserJobFinder(tavily_api_key="", headless=True, interactive=False)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            locale="zh-CN", viewport={"width": 1366, "height": 900})
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await finder._settle_page(page)
        body = await finder._safe_inner_text(page)
        print(f"final={page.url}")
        print(f"body_len={len(body)} captcha={finder._has_captcha_or_wall(body)} "
              f"login_wall={finder._looks_login_wall(body)}")
        print(f"body_head={' '.join(body.split())[:200]}")

        cat = await finder._find_category_link(page, target)
        print(f"类别导航 = {cat}")

        anchors = await finder._collect_anchors(page)
        role_toks = finder._role_tokens(target)
        tk = target.title_keywords
        print(f"\n锚点总数 = {len(anchors)}（含 iframe/属性兜底）")
        scored = finder._score_anchors.__self__ and await finder._score_anchors(page, role_toks)
        print(f"评分>0 的锚点 = {len(scored)}")
        pruned = finder._prune_by_title_relevance(scored, tk)
        print(f"方向相关 = {len(pruned)}")

        shown = 0
        for s, a in pruned[:40]:
            head = (a.get("text") or "").split("\n", 1)[0].strip()
            det = finder._looks_like_job_detail(head, a["href"], role_toks, tk)
            nonjob = finder._looks_non_job(a["href"])
            same = finder._same_list_page(a["href"], page.url)
            reason = []
            if not det:
                reason.append("不像职位详情")
            if nonjob:
                reason.append("命中非职位词")
            if same:
                reason.append("等于列表页")
            mark = "OK " if not reason else "!! "
            if shown < 25:
                print(f"{mark}[{s}] {head[:36]!r} {a['href'][:110]} {'/'.join(reason)}")
            shown += 1
        # 未入选的相关锚点里的链接形态
        print("\n未通过详情判定的相关锚点 URL 形态样例:")
        bad = [a["href"] for s, a in pruned
               if not finder._looks_like_job_detail(
                   (a.get("text") or "").split("\n", 1)[0].strip(), a["href"], role_toks, tk)]
        for u in bad[:10]:
            print(f"   {u[:150]}")

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
