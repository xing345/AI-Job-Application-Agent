"""
招聘站点诊断探针（人工排查用，不参与生产链路）

用途：查明某个招聘页为什么「抽取到 0 个职位」——
分别统计 <a href> 锚点数、iframe 内锚点数、内联 JSON/HTML 里的详情链接数、
XHR 响应里的职位对象数，并把渲染后的 HTML 落盘供人工核对。

用法：
    python tools/probe_job_sites.py             # 探针默认站点
    python tools/probe_job_sites.py <url> [url] # 探针指定 URL
    python tools/probe_job_sites.py --headed    # 可见浏览器（需要人工过验证时）
"""

import asyncio
import json
import os
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright  # noqa: E402

from src.search.browser_job_finder import BrowserJobFinder  # noqa: E402

DEFAULT_TARGETS = [
    "https://jobs.bilibili.com/campus/positions?type=3",
    "https://join.qq.com/post.html?query=p_1",
    "https://campus.jd.com/home#/jobs?to=present&type=present",
    "https://sokon.zhiye.com/Campus",
    "https://jobs.mihoyo.com/#/campus/position?projectIds%5B0%5D=13",
    "https://app.mokahr.com/campus-recruitment/zte/46903#/jobs?page=1&anchorName=jobsList",
    "https://www.liepin.com/zhaopin/",
    "https://we.51job.com/pc/search",
    "https://www.zhipin.com/web/geek/job",
]

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "logs", "probe")


async def probe(url: str, headless: bool = True) -> dict:
    """打开一个站点，统计各类「职位链接来源」的数量，返回诊断字典"""
    finder = BrowserJobFinder(tavily_api_key="", headless=headless, interactive=False)
    api_jobs, handler, stats = finder._make_api_capture()
    api_urls = []

    async def on_resp(resp):
        try:
            ct = (resp.headers or {}).get("content-type", "")
            if "json" in ct:
                api_urls.append(f"{resp.status} {ct.split(';')[0]} {resp.url[:160]}")
        except Exception:
            pass
        await handler(resp)

    result = {"url": url}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox"])
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            locale="zh-CN", viewport={"width": 1366, "height": 800},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = await context.new_page()
        page.on("response", on_resp)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await finder._settle_page(page)
        except Exception as e:
            result["goto_error"] = str(e)
        try:
            result["final_url"] = page.url
            result["title"] = (await page.title())[:120]
            body = await finder._safe_inner_text(page)
            result["body_len"] = len(body)
            result["captcha"] = finder._has_captcha_or_wall(body)
            result["login_wall"] = finder._looks_login_wall(body)
            result["body_head"] = re.sub(r"\s+", " ", body)[:400]

            anchors = await finder._collect_anchors(page)
            result["anchors"] = len(anchors)
            result["anchor_sample"] = [
                {"text": a["text"][:60], "href": a["href"][:120]} for a in anchors[:12]
            ]

            frames = page.frames
            result["frames"] = len(frames)
            frame_anchor_total = 0
            for fr in frames:
                if fr == page.main_frame:
                    continue
                try:
                    got = await fr.eval_on_selector_all(
                        "a[href]", "els => els.map(e => ({text:(e.innerText||'').slice(0,60), href:e.href}))")
                    frame_anchor_total += len(got)
                except Exception:
                    continue
            result["iframe_anchors"] = frame_anchor_total

            html = await page.content()
            result["html_len"] = len(html)
            hits = {
                "position_detail": len(re.findall(r"/(?:campus|society|experienced)/positions?/\d+", html)),
                "jobAdId": len(re.findall(r"jobAdId", html)),
                "jobId_kv": len(re.findall(r"[\"'](?:jobId|jobUnionId|positionId|postId)[\"']\s*:", html)),
                "hash_job": len(re.findall(r"#/(?:job|jobs|position)/", html)),
                "api_like": len(re.findall(r"/(?:api|service)[^\"' ]{0,40}(?:job|position|search)", html, re.I)),
            }
            result["html_pattern_hits"] = hits
            os.makedirs(OUT_DIR, exist_ok=True)
            host = (urlparse(url).netloc or "site").replace(":", "_")
            html_path = os.path.join(OUT_DIR, f"{host}.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            result["html_saved"] = html_path
        finally:
            result["json_endpoints"] = api_urls[:25]
            result["json_responses"] = stats["json_responses"]
            result["api_jobs"] = len(api_jobs)
            result["api_job_sample"] = [
                {"title": j["title"][:50], "id": j["id"], "link": j["url"][:100],
                 "city": j["city"]} for j in api_jobs[:8]
            ]
            result["api_detail_urls_built"] = [
                finder._build_company_job_url(page.url, j) for j in api_jobs[:5]
            ]
            await context.close()
            await browser.close()
    return result


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    headless = "--headed" not in sys.argv
    targets = args or DEFAULT_TARGETS
    reports = []
    for url in targets:
        print(f"\n=== 探针: {url} ===", flush=True)
        try:
            rep = await probe(url, headless=headless)
        except Exception as e:
            rep = {"url": url, "probe_error": str(e)}
        reports.append(rep)
        print(json.dumps(rep, ensure_ascii=False, indent=2)[:4000], flush=True)
    out = os.path.join(OUT_DIR, "probe_report.json")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)
    print(f"\n报告已写入 {out}")


if __name__ == "__main__":
    asyncio.run(main())
