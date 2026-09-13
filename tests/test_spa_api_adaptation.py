"""
SPA 招聘站适配离线测试（不联网 / 不起浏览器 / 不调 LLM）

用从 jobs.bilibili.com 真实抓到的 positionList 接口样本做夹具，验证：
1. XHR 职位 JSON 能被正确遍历出 职位名/ID/城市/完整JD；
2. 职类字典接口（postCodeList）不会被误判成职位列表；
3. B 站校招详情页 URL 模板正确；
4. 直达的职位列表 URL 不会被「找列表页」逻辑导航走；
5. 方向词族对接口职位同样做标题相关性筛选；
6. 接口已带回完整 JD 时，管道不再开浏览器重抓详情页。
"""

import json
import os

from src.search.browser_job_finder import BrowserJobFinder
from src.search.query_expander import infer_direction
from src.search.search_pipeline import SearchPipeline

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name: str):
    with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


def _finder():
    return BrowserJobFinder(tavily_api_key="")


def test_walk_bilibili_position_list_extracts_jobs_and_jd():
    finder = _finder()
    found = []
    finder._walk_jobs_json(_load("bilibili_positionList.json"), found)

    assert len(found) == 10, "data.list 的 10 个职位都应被遍历出来"
    job = next(j for j in found if j["id"] == "30401")
    assert "音视频理解工程师" in job["title"]
    assert job["city"] == "上海", "workLocation 应被识别为城市"
    assert len(job.get("description", "")) >= 100, "接口已带完整 JD，应保留下来"


def test_walk_ignores_postcode_dictionary_payload():
    finder = _finder()
    found = []
    finder._walk_jobs_json(_load("bilibili_postCodeList.json"), found)
    assert found == [], "职类/序列字典不是职位，不能误收"


def test_bilibili_campus_detail_url_template():
    finder = _finder()
    url = finder._build_company_job_url(
        "https://jobs.bilibili.com/campus/positions?type=3",
        {"id": "30401", "title": "音视频理解工程师"},
    )
    assert url == "https://jobs.bilibili.com/campus/positions/30401/detail"


def test_listing_url_guard_keeps_direct_list_page():
    assert BrowserJobFinder._looks_like_listing_url(
        "https://jobs.bilibili.com/campus/positions?type=3"
    )
    assert not BrowserJobFinder._looks_like_listing_url(
        "https://www.bilibili.com/html/join.html"
    )


def test_rank_api_jobs_filters_bilibili_by_ai_direction():
    finder = _finder()
    found = []
    finder._walk_jobs_json(_load("bilibili_positionList.json"), found)
    kws = infer_direction("AI应用开发")["title_keywords"]

    ranked = finder._rank_api_jobs(found, kws)
    titles = [j["title"] for j in ranked]

    assert any("AI" in t for t in titles), "AI 创作项目工程师应被识别为相关"
    # 运营/市场/营销/前端等无关方向不应进入相关集合
    assert not any(
        ("运营" in t or "市场" in t or "营销" in t or "前端" in t) for t in titles
    )


async def test_pipeline_reuses_inline_jd_without_browser_fetch():
    pipeline = SearchPipeline("", "", use_browser=False)
    url = "https://jobs.bilibili.com/campus/positions/30401/detail"
    items = [{
        "url": url,
        "title": "【B-UP】音视频理解工程师（校招）",
        "description": "工作职责:" + "x" * 200,  # 接口带回的完整 JD
    }]

    async def _boom(*args, **kwargs):
        raise AssertionError("接口已带 JD 时不应再开浏览器抓详情页")

    pipeline.job_matcher.fetch_jd_texts = _boom
    out = await pipeline._batch_fetch_jd(items)

    assert len(out[url]) >= 200
