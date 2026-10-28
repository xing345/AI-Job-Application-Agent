"""诊断飞书投递表单：打开链接，截图 + 导出页面结构，看字段到底是什么。"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

URL = "https://modelbest.jobs.feishu.cn/campus/resume/7682708160822593811/apply"
PROFILE = r"D:\x\ai agent\data\browser_profile"
SHOT = r"D:\x\ai agent\tools\_feishu_form.png"


async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(PROFILE, headless=False)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
        print("URL:", page.url)
        print("TITLE:", await page.title())

        # 统计主文档和 iframe 里的可填元素
        info = await page.evaluate("""() => {
            const out = {main: {}, frames: []};
            const probe = (doc, label) => {
                return {
                    inputs: doc.querySelectorAll('input').length,
                    textareas: doc.querySelectorAll('textarea').length,
                    selects: doc.querySelectorAll('select').length,
                    contenteditables: doc.querySelectorAll('[contenteditable]').length,
                    iframes: doc.querySelectorAll('iframe').length,
                };
            };
            out.main = probe(document);
            document.querySelectorAll('iframe').forEach((f, i) => {
                try { out.frames.push({i, url: f.src, stats: probe(f.contentDocument || document)}); }
                catch(e) { out.frames.push({i, url: f.src, error: String(e)}); }
            });
            return out;
        }""")
        import json
        print("STATS:", json.dumps(info, ensure_ascii=False, indent=2))

        await page.screenshot(path=SHOT, full_page=True)
        print("SHOT saved:", SHOT)

        await page.wait_for_timeout(3000)
        await ctx.close()


asyncio.run(main())
