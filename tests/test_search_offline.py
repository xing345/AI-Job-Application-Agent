"""
搜索层离线回归测试(不联网 / 不起浏览器 / 不调 LLM)

重点覆盖三件事:
1. 回归: BrowserJobFinder 的入口方法必须存在 —— 曾因重构删掉方法定义、
   而调用点被宽泛的 except 吞掉, 导致两条浏览器通道静默返回空列表
2. 降级返回: 没有岗位达标时返回最接近的 Top-N 并标记, 而不是空列表
3. 模糊匹配: 岗位名写法不同但方向一致时应命中, 方向相反时不应命中
"""

import re

from src.models.instruction_schemas import TargetInstructionSchema
from src.models.schemas import ResumeSchema
from src.search.browser_job_finder import BrowserJobFinder
from src.search.job_finder import JobFinder, JobFinderConfig
from src.search.job_matcher import MatchResultSchema
from src.search.query_expander import expand_role_variants
from src.search.search_pipeline import SearchPipeline


def _target(role: str = "前端工程师", **kwargs) -> TargetInstructionSchema:
    return TargetInstructionSchema(
        company="", role=role, location="北京",
        keywords=["React"],
        role_variants=expand_role_variants(role, ["React"]),
        **kwargs,
    )


def _resume() -> ResumeSchema:
    return ResumeSchema(
        name="张三", email="zhangsan@example.com", phone="13800138000",
        summary="3年前端开发经验", skills=["React", "TypeScript"],
        work_experience=[], education=[], projects=[],
    )


# ---------------------------------------------------------------- #
# 1. 回归: 浏览器找岗入口依赖的方法必须存在, 且能安全返回
# ---------------------------------------------------------------- #
async def test_browser_finder_entrypoints_exist_and_are_safe():
    required = [
        # 门户通道(通道2)
        "_discover_portal_candidates", "_build_portal_queries",
        # 公司官网通道(通道0)
        "_locate_career_page", "_best_career_anchor", "_probe_career_urls",
        # 公司发现/站内抽取
        "_classify_company_result", "_resolve_named_company",
        "_extract_company_jobs", "_find_job_list_href",
    ]
    missing = [name for name in required if not callable(getattr(BrowserJobFinder, name, None))]
    assert not missing, f"BrowserJobFinder 缺少方法定义: {missing}"

    # 未配置 Tavily key 时应安静地返回 [], 而不是抛 AttributeError 被上层吞掉
    finder = BrowserJobFinder(tavily_api_key="")
    assert await finder.discover(_target()) == []
    assert await finder.discover_company_careers(_target(), known_companies=["字节跳动"]) == []


# ---------------------------------------------------------------- #
# 2. 降级返回: 全部低于门槛时返回带标记的 Top-N, 而不是空列表
# ---------------------------------------------------------------- #
class _FakeMatcher:
    """替身匹配器: 按 JD 文本里出现的 URL 返回预置分数, 不联网不调 LLM"""

    def __init__(self, scores: dict):
        self.scores = scores

    async def evaluate_match(self, resume, jd_text):
        match = re.search(r"https?://\S+", jd_text or "")
        url = match.group(0) if match else ""
        score = self.scores.get(url, 0)
        return MatchResultSchema(
            score=score, is_match=score >= 60,
            reasons=[f"预置分数 {score}"], matched_skills=[], missing_skills=[],
            match_summary=f"测试岗位 {score}",
        )


def _make_pipeline(scores: dict) -> SearchPipeline:
    """构造一条只走「评估 -> 筛选」两段的管道, 发现与抓取都用替身"""
    pipeline = SearchPipeline("", "", use_browser=False)
    pipeline.job_matcher = _FakeMatcher(scores)

    items = [
        {"url": "https://jobs.example.com/1", "title": "前端开发工程师", "channel": "fake"},
        {"url": "https://jobs.example.com/2", "title": "数据工程师", "channel": "fake"},
        {"url": "https://jobs.example.com/3", "title": "Web前端", "channel": "fake"},
    ]

    async def fake_discover(target_info):
        return items

    async def fake_fetch(job_items):
        # 第 3 个抓取失败(空串), 用于验证「用职位标题兜底」而不是直接丢弃
        return {
            it["url"]: ("" if it["url"].endswith("/3") else f"{it['url']} " + "x" * 200)
            for it in job_items
        }

    pipeline._discover_job_urls = fake_discover
    pipeline._batch_fetch_jd = fake_fetch
    return pipeline


async def test_pipeline_degrades_instead_of_returning_empty():
    scores = {
        "https://jobs.example.com/1": 50,
        "https://jobs.example.com/2": 30,
        "https://jobs.example.com/3": 40,
    }
    pipeline = _make_pipeline(scores)

    results = await pipeline.run_search_pipeline(
        target_info=_target(), resume=_resume(), min_score=60, max_results=10
    )

    assert results, "全部低于门槛时应降级返回最接近的岗位, 而不是空列表"
    assert all(not r.above_threshold for r in results), "降级结果必须标记为未达门槛"
    assert [r.match_result.score for r in results] == [50, 40, 30], "应按分数降序"

    # 抓取失败但有标题的岗位也要进入结果(用标题兜底评估)
    assert "https://jobs.example.com/3" in [r.url for r in results]


async def test_pipeline_keeps_qualified_results_only_when_present():
    scores = {
        "https://jobs.example.com/1": 85,
        "https://jobs.example.com/2": 30,
        "https://jobs.example.com/3": 20,
    }
    pipeline = _make_pipeline(scores)

    results = await pipeline.run_search_pipeline(
        target_info=_target(), resume=_resume(), min_score=60, max_results=10
    )

    assert [r.url for r in results] == ["https://jobs.example.com/1"]
    assert all(r.above_threshold for r in results)


# ---------------------------------------------------------------- #
# 3. 模糊匹配: 岗位名写法不同但方向一致要命中
# ---------------------------------------------------------------- #
def test_is_job_page_is_fuzzy_and_blocks_noise():
    finder = JobFinder(JobFinderConfig(api_key=""))
    info = _target("前端工程师")

    # 写法不同但方向一致 -> 命中
    assert finder._is_job_page(
        "https://jobs.bytedance.com/position/1", "Web前端开发工程师", "React 技术栈", info
    )
    # 方向相反 -> 拒绝(不能因为都含「工程师」就判为命中)
    assert not finder._is_job_page(
        "https://jobs.bytedance.com/position/2", "后端开发工程师", "Java 技术栈", info
    )
    # 噪声站点 -> 拒绝
    assert not finder._is_job_page("https://www.zhihu.com/question/1", "前端招聘", "", info)
    # 非招聘页面 -> 拒绝
    assert not finder._is_job_page(
        "https://jobs.bytedance.com/blog/x", "前端开发工程师", "", info
    )


def test_search_query_uses_variants_and_drops_overseas_sites():
    finder = JobFinder(JobFinderConfig(api_key=""))
    query = finder._build_search_query(_target("前端工程师"))

    assert "前端" in query and "招聘" in query
    # 不再用 site: 白名单锁定海外 ATS 域名
    assert "site:" not in query
    assert "greenhouse" not in query.lower()
    assert "lever.co" not in query.lower()


# ---------------------------------------------------------------- #
# 4. 搜索前指定公司: 目标公司名单能传到管道里
# ---------------------------------------------------------------- #
def test_pipeline_target_companies_can_be_updated():
    pipeline = SearchPipeline("", "", use_browser=False)
    assert pipeline.target_companies is None

    pipeline.set_target_companies(["字节跳动", "  ", "美团"])
    assert pipeline.target_companies == ["字节跳动", "美团"]

    pipeline.set_target_companies([])
    assert pipeline.target_companies is None, "空名单应回到不限公司"


async def test_orchestrator_parses_and_applies_company_input():
    from src.orchestrator.agent_orchestrator import AgentOrchestrator

    agent = AgentOrchestrator()
    assert agent._parse_company_input("字节跳动, 美团 https://jobs.abc.com") == [
        "字节跳动", "美团", "https://jobs.abc.com"
    ]
    assert agent._parse_company_input("") == []

    # 注入假 job_searcher, 验证名单确实推给了搜索器
    class _FakeSearcher:
        def __init__(self):
            self.received = None

        def set_target_companies(self, companies):
            self.received = companies

    agent.job_searcher = _FakeSearcher()
    agent._apply_target_companies(["字节跳动"])
    assert agent.job_searcher.received == ["字节跳动"]
    assert agent.config['search']['target_companies'] == ["字节跳动"]


async def test_prompt_target_companies_keeps_current_on_empty_input():
    from src.orchestrator.agent_orchestrator import AgentOrchestrator

    agent = AgentOrchestrator()
    # 用户直接回车 -> 保持当前设置
    assert await agent._prompt_target_companies(lambda _: "", ["美团"]) == ["美团"]
    # 用户输入新名单 -> 替换
    assert await agent._prompt_target_companies(lambda _: "字节跳动 美团", ["x"]) == [
        "字节跳动", "美团"
    ]


# ---------------------------------------------------------------- #
# 5. JobSearcher 构造的搜索输入带上岗位变体
# ---------------------------------------------------------------- #
def test_job_searcher_fills_role_variants():
    from src.search.job_searcher import JobSearcher

    searcher = JobSearcher({})
    persona = {
        "name": "张三", "email": "zhangsan@example.com", "phone": "13800138000",
        "career_objective": {
            "target_positions": ["前端工程师"], "location_preference": ["北京"],
        },
        "technical_skills": {"frontend": ["React", "TypeScript"]},
    }

    target_info, _ = searcher._build_search_inputs(persona)

    assert target_info.role == "前端工程师"
    assert "前端开发" in target_info.role_variants, "应扩展出同义岗位变体"
