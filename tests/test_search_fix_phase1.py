"""
本轮「搜不到岗位 / 登录闪烁 / 只搜到几个」修复的离线回归测试

对应 5 个现象的真实根因（详见 docs/SEARCH_FIX_REPORT.md）：
1. 问题1 聚合门户搜不准 → 门户入口改写为站内搜索 URL（公司官网不受影响）；
2. 问题2/3 登录墙与页面闪烁 → 阻断判定加 DOM 证据、HITL 暂停闸门、
   可见浏览器并发收敛、登录态目录复用；
3. 问题4 「1225 个岗位只搜到几个」→ 成本上限全部可配置 + 接口职位上限放开；
4. 问题5 「下一步导航」→ 已在列表页（DOM 证据）时禁止类别跳转，
   模糊时最多让受约束的 LLM 裁决器在候选里选择/否决。

全部离线：不起浏览器、不联网、不调 LLM。
"""

import asyncio

import pytest

from src.models.instruction_schemas import TargetInstructionSchema
from src.search.browser_job_finder import (
    DANGEROUS_NAV_TEXT,
    PORTAL_SEARCH_URLS,
    STRONG_CAPTCHA_HINTS,
    BrowserJobFinder,
)
from src.search.hitl import BlockHandler
from src.search.nav_advisor import NavAdvisor, NavAdvisorConfig
from src.search.query_expander import infer_direction


def _finder(**kw):
    kw.setdefault("tavily_api_key", "")
    kw.setdefault("headless", True)
    kw.setdefault("interactive", False)
    return BrowserJobFinder(**kw)


def _target(**kw):
    d = infer_direction("AI应用开发工程师")
    base = dict(
        company="", role="AI应用开发工程师", location="",
        direction_family=d["key"], direction_category=d["category"],
        title_keywords=d["title_keywords"],
        role_variants=["AI应用开发工程师", "AI应用", "AI开发"],
        recruit_type="campus",
    )
    base.update(kw)
    return TargetInstructionSchema(**base)


class _FakePage:
    """最小 page 替身：url + frames（_collect_anchors 用）+ 链接计数"""

    def __init__(self, url, links=None):
        self.url = url
        self.frames = []
        self._links = links or []

    async def eval_on_selector_all(self, selector, js):
        # Playwright 的计数脚本返回 int；抽链接的脚本返回列表（与被测代码一致）
        if "length" in js:
            return 0
        if selector == "a[href]":
            return list(self._links)
        return []


def _patch_anchors(monkeypatch, finder, anchors):
    async def _fake(page, page_url=None):
        return anchors
    monkeypatch.setattr(finder, "_collect_anchors", _fake)


# --------------------------------------------------------------------- #
# 问题4：成本上限必须来自配置，且默认不再是「每站 10 个 / 翻 3 页」
# --------------------------------------------------------------------- #
def test_limits_are_configurable():
    f = _finder()
    assert f.max_jobs_per_site == 25
    assert f.max_list_pages == 4
    assert f.max_api_objects == 200

    tuned = _finder(max_jobs_per_site=60, max_list_pages=8, max_api_objects=500)
    assert tuned.max_jobs_per_site == 60
    assert tuned.max_list_pages == 8
    assert tuned.max_api_objects == 500


def test_walk_jobs_json_respects_configured_cap():
    """接口职位上限可配置：字节这种 1000+ 岗位的列表不再被 40 条硬编码砍掉"""
    f = _finder(max_api_objects=120)
    payload = {"data": {"list": [
        {"positionName": f"后端开发工程师-{i}", "id": str(100000 + i)}
        for i in range(200)
    ]}}
    found = []
    f._walk_jobs_json(payload, found)
    assert len(found) == 120

    small = _finder(max_api_objects=10)
    found_small = []
    small._walk_jobs_json(payload, found_small)
    assert len(found_small) == 10


def test_max_card_clicks_configurable():
    assert _finder(max_card_clicks=40).max_card_clicks == 40


def test_browser_profile_dir_is_absolute():
    """登录态目录必须按项目根解析：相对 cwd 会让两次运行落到不同目录（等于没复用）"""
    import os
    f = _finder(user_data_dir="data/browser_profile")
    assert os.path.isabs(f.user_data_dir)
    assert f.user_data_dir.replace("\\", "/").endswith("data/browser_profile")
    assert _finder(user_data_dir=None).user_data_dir is None


# --------------------------------------------------------------------- #
# 问题1：聚合门户改写为站内搜索 URL；公司官网不能被改写
# --------------------------------------------------------------------- #
def test_portal_search_url_rewrites_aggregators_only():
    f = _finder()
    t = _target()
    cases = {
        "https://www.zhipin.com/web/geek/job": "zhipin.com",
        "https://www.liepin.com/zhaopin/": "liepin.com",
        "https://we.51job.com/pc/search": "51job.com",
        "https://sou.zhaopin.com/": "zhaopin.com",
    }
    for entry, host in cases.items():
        url = f._portal_search_url(entry, t)
        assert url and host in url, entry
        # 岗位词必须带在查询串里，而不是打开门户默认 feed
        assert "AI" in url or "%" in url

    # 公司官网 / 不认识的门户：不改写（仍走类别+列表遍历）
    assert f._portal_search_url("https://jobs.bytedance.com/campus/position", t) is None
    assert f._portal_search_url("https://jobs.mihoyo.com/#/campus/position", t) is None
    assert f._portal_search_url("https://unknown-corp.com/jobs", t) is None


def test_portal_search_templates_cover_builtin_sites():
    from src.search.site_registry import BUILTIN_JOB_SITES
    hosts = " ".join(s["url"] for s in BUILTIN_JOB_SITES)
    for key in ("zhipin.com", "liepin.com", "51job.com"):
        assert key in hosts
        assert key in PORTAL_SEARCH_URLS


def test_portal_search_disabled_by_switch():
    f = _finder(portal_keyword_search=False)
    assert f.portal_keyword_search is False


# --------------------------------------------------------------------- #
# 问题5：已经在列表页时禁止类别导航跳转（DOM 证据优先）
# --------------------------------------------------------------------- #
async def test_category_link_stays_when_page_already_has_job_links(monkeypatch):
    """字节校招页：导航栏里含「技术」二字的宣传链接不能把 Agent 带离列表页"""
    f = _finder(nav_stay_min_job_links=3)
    _patch_anchors(monkeypatch, f, [
        {"text": "技术", "href": "https://jobs.bytedance.com/campus/page-AgCQiO"},
    ])
    links = [f"https://jobs.bytedance.com/campus/position/76{i}/detail" for i in range(6)]
    page = _FakePage("https://jobs.bytedance.com/campus/position?keywords=&category=1",
                     links=links)
    assert await f._find_category_link(page, _target()) is None


async def test_category_link_still_works_on_non_listing_page(monkeypatch):
    """不在列表页时（且页面上没有职位链接）仍按规则进类别，行为不回归"""
    f = _finder()
    _patch_anchors(monkeypatch, f, [
        {"text": "技术类", "href": "https://www.example-corp.com/campus/tech"},
    ])
    page = _FakePage("https://www.example-corp.com/nav")
    assert await f._find_category_link(page, _target()) == \
        "https://www.example-corp.com/campus/tech"


async def test_category_candidates_never_include_submit_or_login(monkeypatch):
    """红线1：投递/申请/登录类链接永远不进入候选（也不会被 LLM 选中）"""
    f = _finder()
    _patch_anchors(monkeypatch, f, [
        {"text": "技术岗投递", "href": "https://jobs.example-corp.com/campus/tech-apply"},
        {"text": "登录", "href": "https://jobs.example-corp.com/campus/tech-login"},
        {"text": "技术中心", "href": "https://jobs.example-corp.com/campus/tech"},
    ])
    page = _FakePage("https://jobs.example-corp.com/nav")
    got = await f._find_category_link(page, _target())
    assert got == "https://jobs.example-corp.com/campus/tech"
    for word in ("投递", "申请", "登录"):
        assert word in DANGEROUS_NAV_TEXT


# --------------------------------------------------------------------- #
# 问题5：LLM 导航裁决器只做「选择题」，且失败/关闭时完全回退规则
# --------------------------------------------------------------------- #
class _StubAdvisor(NavAdvisor):
    """记录调用的假裁决器（不联网、不调 LLM）"""

    def __init__(self, answer):
        super().__init__(NavAdvisorConfig(enabled=False))
        self.answer = answer
        self.seen = []

    @property
    def enabled(self):
        return True

    async def choose(self, **kw):
        self.seen.append(kw)
        return self.answer


async def test_nav_advisor_can_veto_deterministic_jump(monkeypatch):
    f = _finder()
    advisor = _StubAdvisor(-1)
    f.nav_advisor = advisor
    _patch_anchors(monkeypatch, f, [
        {"text": "技术类", "href": "https://jobs.bytedance.com/campus/page-AgCQiO"},
        {"text": "技术中心", "href": "https://jobs.bytedance.com/campus/page-Xyz"},
    ])
    # 非列表 URL，但页面上已经能看到 1 个职位链接 → 属于「规则判不准」的场景
    page = _FakePage("https://jobs.bytedance.com/hub",
                     links=["https://jobs.bytedance.com/campus/position/123/detail"])
    assert await f._find_category_link(page, _target()) is None
    assert advisor.seen, "模糊时应询问裁决器"
    # 裁决器只拿到候选，没有被赋予「点任意元素」的能力
    cand = advisor.seen[0]["candidates"]
    assert cand and all(set(c) == {"text", "href"} for c in cand)


async def test_nav_advisor_can_pick_another_candidate(monkeypatch):
    f = _finder()
    f.nav_advisor = _StubAdvisor(1)
    # 两个候选同分（规则判不准）→ 才轮到裁决器做选择
    _patch_anchors(monkeypatch, f, [
        {"text": "技术类", "href": "https://jobs.example-corp.com/campus/a"},
        {"text": "技术类", "href": "https://jobs.example-corp.com/campus/b"},
    ])
    page = _FakePage("https://jobs.example-corp.com/nav")
    got = await f._find_category_link(page, _target())
    assert got == "https://jobs.example-corp.com/campus/b", "裁决器选中的候选应被采用"


async def test_nav_advisor_not_called_when_rule_is_confident(monkeypatch):
    """规则明确时不花 LLM 的钱：最高分明显领先就直接用规则结果"""
    f = _finder()
    advisor = _StubAdvisor(1)
    f.nav_advisor = advisor
    _patch_anchors(monkeypatch, f, [
        {"text": "技术类", "href": "https://jobs.example-corp.com/campus/a"},
        {"text": "程序", "href": "https://jobs.example-corp.com/campus/b"},
    ])
    page = _FakePage("https://jobs.example-corp.com/nav")
    got = await f._find_category_link(page, _target())
    assert got == "https://jobs.example-corp.com/campus/a"
    assert advisor.seen == [], "分数不接近时不应调用 LLM"


async def test_nav_advisor_failure_falls_back_to_rules(monkeypatch):
    class _Boom(_StubAdvisor):
        async def choose(self, **kw):
            raise RuntimeError("LLM 挂了")

    f = _finder()
    f.nav_advisor = _Boom(None)
    _patch_anchors(monkeypatch, f, [
        {"text": "技术类", "href": "https://jobs.example-corp.com/campus/a"},
        {"text": "技术类", "href": "https://jobs.example-corp.com/campus/b"},
    ])
    page = _FakePage("https://jobs.example-corp.com/nav")
    assert await f._find_category_link(page, _target()) == \
        "https://jobs.example-corp.com/campus/a"



def test_nav_advisor_budget_and_kill_switch():
    assert BrowserJobFinder.build_nav_advisor({}, {}) is None, "未开启时不应创建"
    assert BrowserJobFinder.build_nav_advisor({"enabled": False}, {}) is None

    advisor = BrowserJobFinder.build_nav_advisor(
        {"enabled": True, "max_calls_per_search": 2}, {"api_key": "k", "model": "m"}
    )
    assert advisor is not None
    assert advisor.enabled
    advisor.calls = 2
    assert not advisor.enabled, "预算用尽后必须停止调用 LLM"


def test_nav_advisor_filters_dangerous_candidates():
    advisor = NavAdvisor(NavAdvisorConfig(enabled=True, api_key="k", model="m"))
    safe = advisor._safe_candidates([
        {"text": "投递简历", "href": "https://x.com/apply"},
        {"text": "登录", "href": "https://x.com/login"},
        {"text": "技术类", "href": "https://x.com/tech"},
        {"text": "坏链接", "href": "javascript:void(0)"},
    ])
    assert [c["text"] for c in safe] == ["技术类"]


# --------------------------------------------------------------------- #
# 问题2：阻断判定改为「文本 + DOM 证据」，不再仅凭文案
# --------------------------------------------------------------------- #
async def test_blocked_detection_requires_dom_evidence_for_weak_hints():
    f = _finder()

    class _Page:
        def __init__(self, links, controls=0):
            self._links = links
            self._controls = controls
            self.url = "https://www.zhipin.com/web/geek/job"

        async def eval_on_selector_all(self, selector, js):
            if "length" in js:
                # 只有验证控件选择器命中时才返回控件数
                return self._controls if ("captcha" in selector or "slider" in selector) else 0
            if selector == "a[href]":
                return list(self._links)
            return []

        async def inner_text(self, sel):
            # Boss 正常页面里就有「验证码登录」入口文案
            return "短信验证码登录 扫码登录 " + "职位描述" * 60

    job_links = [f"https://www.zhipin.com/job_detail/{i}.html" for i in range(8)]
    # 有职位链接 → 不算被挡
    assert await f._page_looks_blocked(_Page(job_links)) == ""
    # 没有职位链接，但正文只有弱特征「验证码」且 DOM 里没有验证控件 → 不算被挡
    assert await f._page_looks_blocked(_Page([])) == ""
    # 同样页面，但 DOM 里真的有验证控件 → 判定 captcha
    assert await f._page_looks_blocked(_Page([], controls=2)) == "captcha"


async def test_blocked_detection_strong_hint_and_login_form():
    f = _finder()

    class _Page:
        def __init__(self, body, password=0):
            self.body = body
            self.password = password
            self.url = "https://www.liepin.com/zhaopin/"

        async def eval_on_selector_all(self, selector, js):
            if "length" in js:
                return self.password if "password" in selector else 0
            return []

        async def inner_text(self, sel):
            return self.body

    assert await f._page_looks_blocked(_Page("请完成安全验证 " + "x" * 300)) == "captcha"
    assert await f._page_looks_blocked(
        _Page("请先登录后查看职位 " + "x" * 300, password=1)) == "login"
    # 只有「请登录」页眉文案、没有密码框 → 不算登录墙
    assert await f._page_looks_blocked(
        _Page("请登录后查看 " + "x" * 300, password=0)) == ""
    assert "请完成安全验证" in STRONG_CAPTCHA_HINTS


# --------------------------------------------------------------------- #
# 问题3：HITL 暂停期间浏览器必须静止
# --------------------------------------------------------------------- #
async def test_block_handler_pauses_and_resumes():
    seen = {}

    async def on_pause(info):
        # 暂停期间闸门必须是关的（浏览器侧据此停工）
        seen["paused_during_ask"] = handler.is_paused
        seen["event_set"] = handler._resume.is_set()
        return "continue"

    handler = BlockHandler(interactive=True, headless=False, on_pause=on_pause)
    ok = await handler.handle("captcha", "https://www.zhipin.com/web/geek/job", "d")
    assert ok is True
    assert seen["paused_during_ask"] is True
    assert seen["event_set"] is False
    assert handler.is_paused is False
    # 恢复后 wait_until_resumed 立即返回
    await asyncio.wait_for(handler.wait_until_resumed(), timeout=1)


async def test_wait_until_resumed_blocks_until_user_done():
    started = asyncio.Event()

    async def on_pause(info):
        started.set()
        await asyncio.sleep(0.15)
        return "continue"

    handler = BlockHandler(interactive=True, headless=False, on_pause=on_pause)
    waiter_done = asyncio.Event()

    async def waiter():
        await handler.wait_until_resumed()
        waiter_done.set()

    task = asyncio.create_task(handler.handle("login", "https://www.liepin.com/x"))
    await started.wait()
    w = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)
    assert not waiter_done.is_set(), "暂停期间其它页面必须先停住（否则窗口会闪）"
    await task
    await asyncio.wait_for(w, timeout=1)
    assert waiter_done.is_set()


async def test_block_handler_skips_without_pausing_when_headless():
    handler = BlockHandler(interactive=True, headless=True)
    assert await handler.handle("captcha", "https://x.com/1") is False
    assert handler.is_paused is False
    await asyncio.wait_for(handler.wait_until_resumed(), timeout=1)


async def test_block_handler_reset_forgets_handled_domains():
    """浏览器被重建（用户关窗口/崩溃）后必须重新询问，不能按「已通行」放行"""
    calls = []

    async def on_pause(info):
        calls.append(info.url)
        return "continue"

    handler = BlockHandler(interactive=True, headless=False, on_pause=on_pause)
    assert await handler.handle("login", "https://www.zhipin.com/web/geek/job") is True
    assert await handler.handle("login", "https://www.zhipin.com/job_detail/1.html") is True
    assert len(calls) == 1, "同一站点只打断一次"

    handler.reset()
    assert await handler.handle("login", "https://www.zhipin.com/web/geek/job") is True
    assert len(calls) == 2, "浏览器重建后必须重新询问"


# --------------------------------------------------------------------- #
# 找到「像职位详情」的候选：口径与最终入库一致（修「相关 2 个 → 最终 0 个」）
# --------------------------------------------------------------------- #
def test_filter_detail_like_reports_reject_reasons():
    f = _finder()
    t = _target()
    list_url = "https://jobs.example.com/list"
    scored = [
        (3, {"text": "首页", "href": "https://jobs.example.com/"}),
        (3, {"text": "AI算法工程师", "href": "https://jobs.example.com/blog/1"}),
        (3, {"text": "AI算法工程师", "href": list_url}),
        (3, {"text": "AI算法工程师", "href": "https://jobs.example.com/position/123"}),
    ]
    kept, stats = f._filter_detail_like(scored, list_url, [], t.title_keywords)
    assert [a["href"] for _s, a in kept] == ["https://jobs.example.com/position/123"]
    assert stats["rejected"] == 3
    assert stats["nav_text"] == 1
    assert stats["non_job"] == 1
    assert stats["same_list"] == 1


def test_role_query_prefers_primary_role():
    f = _finder()
    assert f._role_query(_target(role="AI应用开发工程师")) == "AI应用开发工程师"


# --------------------------------------------------------------------- #
# 配置贯通：config.json 的 search / browser / llm 段必须真的传到浏览器层
# --------------------------------------------------------------------- #
def test_searcher_propagates_config_to_finder():
    from src.search.job_searcher import JobSearcher

    searcher = JobSearcher({
        "search": {
            "max_jobs_per_site": 33, "max_list_pages": 6, "max_card_clicks": 7,
            "max_api_objects": 321, "jd_fetch_limit": 55, "jd_concurrency": 4,
            "portal_keyword_search": False,
            "nav_advisor": {"enabled": True, "max_calls_per_search": 2},
        },
        "llm": {"api_key": "k", "model": "m"},
        "browser": {"headless": True, "persist_login": False, "visible_concurrency": 1},
    })
    pipeline = searcher.pipeline
    bf = pipeline.browser_finder
    assert (bf.max_jobs_per_site, bf.max_list_pages, bf.max_card_clicks,
            bf.max_api_objects) == (33, 6, 7, 321)
    assert bf.portal_keyword_search is False
    assert pipeline.jd_fetch_limit == 55
    assert pipeline.jd_concurrency == 4
    assert pipeline.job_matcher.config.persist_login is False
    assert pipeline.job_matcher.config.visible_concurrency == 1
    assert pipeline.nav_advisor is not None
    assert bf.nav_advisor is pipeline.nav_advisor, "发现器与管道共用同一个裁决器实例"


def test_searcher_disables_nav_advisor_by_config():
    from src.search.job_searcher import JobSearcher

    searcher = JobSearcher({
        "search": {"nav_advisor": {"enabled": False}},
        "llm": {"api_key": "k", "model": "m"},
        "browser": {"headless": True},
    })
    assert searcher.pipeline.nav_advisor is None
    assert searcher.pipeline.browser_finder.nav_advisor is None

