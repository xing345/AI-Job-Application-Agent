"""
模糊方向 -> 标题语义判相关 -> 技能差距：离线回归测试（不联网 / 不起浏览器 / 不调 LLM）

覆盖用户诉求：
1. 只给模糊方向（如「AI应用开发」）也要推断出岗位大类与方向词族，不要求准确岗位名；
2. 遍历职位列表时按「职位标题」语义判相关：大模型/LLM/算法-AI 方向都算相关，
   前端/人力等无关方向不算；
3. 搜索结果必须保留发现阶段的真实职位标题；
4. 报告逐职位输出欠缺技能（skill gap）。
"""

from src.models.instruction_schemas import TargetInstructionSchema
from src.search.browser_job_finder import BrowserJobFinder
from src.search.job_matcher import MatchResultSchema
from src.search.query_expander import (
    infer_direction,
    title_direction_relevance,
    expand_role_variants,
)
from src.search.search_pipeline import SearchPipeline


# ---------------------------------------------------------------- #
# 1. 模糊方向推断
# ---------------------------------------------------------------- #
def test_infer_ai_direction_from_fuzzy_input():
    d = infer_direction("AI应用开发", ["Python", "LangChain"])
    assert d["key"] == "ai"
    assert d["category"] == "技术类"
    assert d["label"] == "AI/算法"
    # 标题词族要覆盖招聘市场上 AI 岗位的常见写法
    kws = [k.lower() for k in d["title_keywords"]]
    for must in ["ai", "大模型", "llm", "算法", "机器学习"]:
        assert must in kws


def test_infer_frontend_direction():
    d = infer_direction("前端工程师")
    assert d["key"] == "frontend"
    assert d["category"] == "技术类"


def test_infer_generic_tech_fallback():
    # 没命中任何具体方向、但是技术语境 -> 泛技术类，标题词族不为空（兜底用）
    d = infer_direction("软件开发")
    assert d["key"] is None
    assert d["category"] == "技术类"
    assert d["title_keywords"]


# ---------------------------------------------------------------- #
# 2. 职位标题与方向词族的语义相关性
# ---------------------------------------------------------------- #
AI_RELATED_TITLES = [
    "大模型应用工程师",
    "LLM开发工程师",
    "算法工程师-AI方向",
    "AIGC算法实习生",
    "机器学习平台工程师",
    "自然语言处理研究员",
    "AI应用开发工程师（智能体方向）",
]
AI_UNRELATED_TITLES = [
    "前端开发工程师",
    "Java后端工程师",
    "人力资源专员",
    "财务分析师",
    "UI设计师",
]


def test_ai_family_titles_are_related():
    kws = infer_direction("AI应用开发")["title_keywords"]
    for title in AI_RELATED_TITLES:
        hits, is_job = title_direction_relevance(title, kws)
        assert hits > 0, f"应判为 AI 相关: {title}"
        assert is_job, f"应识别为职位: {title}"


def test_unrelated_titles_not_related_to_ai():
    kws = infer_direction("AI应用开发")["title_keywords"]
    for title in AI_UNRELATED_TITLES:
        hits, _ = title_direction_relevance(title, kws)
        assert hits == 0, f"不应判为 AI 相关: {title}"


# ---------------------------------------------------------------- #
# 3. BrowserJobFinder 锚点评分 / 标题筛选 / XHR 排序
# ---------------------------------------------------------------- #
def _finder():
    return BrowserJobFinder(tavily_api_key="")


def _ai_target():
    role = "AI应用开发工程师"
    d = infer_direction(role)
    return TargetInstructionSchema(
        company="", role=role, keywords=["Python"],
        role_variants=expand_role_variants(role),
        direction_category=d["category"], direction_family=d["key"],
        title_keywords=d["title_keywords"],
    )


def test_score_anchor_ranks_ai_title_above_unrelated():
    finder = _finder()
    info = _ai_target()
    kws = info.title_keywords
    href = "https://jobs.example.com/position/123/detail"

    ai_score = finder._score_anchor("大模型应用工程师", href, [], kws)
    fe_score = finder._score_anchor("前端开发工程师", href, [], kws)
    hr_score = finder._score_anchor("人力资源专员", href, [], kws)

    assert ai_score > fe_score, "AI 方向职位必须排在无关技术岗之前"
    assert ai_score > 0 and fe_score > 0
    # 人力也是真实职位（识别门应认），但与 AI 方向无关，应由方向筛选滤掉
    assert hr_score > 0
    pruned = finder._prune_by_title_relevance(
        [(ai_score, {"text": "大模型应用工程师", "href": href}),
         (hr_score, {"text": "人力资源专员", "href": href})], kws
    )
    assert [a["text"] for _, a in pruned] == ["大模型应用工程师"]


def test_prune_keeps_only_related_when_present():
    finder = _finder()
    kws = _ai_target().title_keywords
    scored = [
        (15, {"text": "大模型应用工程师", "href": "https://x/position/1/detail"}),
        (6, {"text": "前端开发工程师", "href": "https://x/position/2/detail"}),
        (15, {"text": "LLM开发工程师", "href": "https://x/position/3/detail"}),
    ]
    pruned = finder._prune_by_title_relevance(scored, kws)
    titles = [a["text"] for _, a in pruned]
    assert "大模型应用工程师" in titles and "LLM开发工程师" in titles
    assert "前端开发工程师" not in titles, "存在相关职位时，无关职位应被滤掉"


def test_prune_falls_back_to_all_when_none_related():
    finder = _finder()
    kws = _ai_target().title_keywords
    scored = [
        (6, {"text": "前端开发工程师", "href": "https://x/position/2/detail"}),
        (6, {"text": "测试工程师", "href": "https://x/position/4/detail"}),
    ]
    # 一个 AI 相关的都没有时不能返回空（整体兜底，交给 JD 匹配阶段细判）
    pruned = finder._prune_by_title_relevance(scored, kws)
    assert len(pruned) == 2


def test_rank_api_jobs_orders_related_first():
    finder = _finder()
    kws = _ai_target().title_keywords
    api_jobs = [
        {"title": "前端开发工程师", "id": "1"},
        {"title": "AIGC算法工程师", "id": "2"},
        {"title": "大模型应用工程师", "id": "3"},
    ]
    ranked = finder._rank_api_jobs(api_jobs, kws)
    assert [j["id"] for j in ranked] == ["3", "2"] or \
        set(j["id"] for j in ranked) == {"2", "3"}
    assert all(j["id"] != "1" for j in ranked), "存在相关 XHR 职位时只返回相关职位"


def test_looks_like_job_detail_accepts_ai_title():
    finder = _finder()
    kws = _ai_target().title_keywords
    href = "https://jobs.example.com/position/9/detail"
    assert finder._looks_like_job_detail("大模型应用工程师", href, [], kws)
    # 登录/导航不是职位详情
    assert not finder._looks_like_job_detail("首页", href, [], kws)


# ---------------------------------------------------------------- #
# 4. 管道保留真实职位标题
# ---------------------------------------------------------------- #
def test_filter_keeps_real_discovered_title():
    pipeline = SearchPipeline("", "", use_browser=False)
    url = "https://jobs.example.com/position/9/detail"
    match = MatchResultSchema(
        score=80, is_match=True, reasons=["技能对口"],
        matched_skills=["Python"], missing_skills=["RAG 检索增强"],
        match_summary="AI 岗匹配",
    )
    items = [{"url": url, "title": "大模型应用工程师", "channel": "company_site"}]

    results = pipeline._filter_and_sort_results({url: match}, 60, 10, items)

    assert len(results) == 1
    assert results[0].title == "大模型应用工程师", "发现阶段的真实标题不能被 match_summary 覆盖"


# ---------------------------------------------------------------- #
# 5. JobSearcher 把方向词族下传到搜索指令
# ---------------------------------------------------------------- #
def test_job_searcher_builds_title_keywords_for_ai_persona():
    from src.search.job_searcher import JobSearcher

    searcher = JobSearcher({})
    persona = {
        "name": "张亚辉", "email": "z@example.com", "phone": "",
        "career_objective": {
            "target_positions": ["AI应用开发"], "location_preference": [],
        },
        "technical_skills": {"ai": ["Python", "PyTorch", "LangChain"]},
    }
    target_info, _ = searcher._build_search_inputs(persona)
    assert target_info.direction_family == "ai"
    assert target_info.direction_category == "技术类"
    assert target_info.title_keywords, "必须下传标题词族供浏览器阶段按标题判相关"


# ---------------------------------------------------------------- #
# 6. 报告逐职位输出欠缺技能
# ---------------------------------------------------------------- #
def test_report_lists_missing_skills_per_job():
    import time
    pipeline = SearchPipeline("", "", use_browser=False)

    def make(url, title, missing):
        return type(
            "R", (), {
                "url": url, "title": title, "above_threshold": True,
                "is_qualified": True, "get_priority_score": lambda self: 70,
                "match_result": MatchResultSchema(
                    score=70, is_match=True, reasons=["r"],
                    matched_skills=["Python"], missing_skills=missing,
                    match_summary="s",
                ),
                "matched_at": time.time(),
            },
        )()

    results = [
        make("https://x/1", "大模型应用工程师", ["RAG", "向量数据库"]),
        make("https://x/2", "LLM开发工程师", ["CUDA 优化"]),
    ]
    report = pipeline.generate_report(results)
    assert "大模型应用工程师" in report and "LLM开发工程师" in report
    assert "RAG" in report and "CUDA 优化" in report, "每个职位都要列出欠缺技能"
