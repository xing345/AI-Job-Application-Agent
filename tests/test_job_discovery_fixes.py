"""
职位发现「抽取到 0 个职位」相关修复的离线测试（不联网 / 不起浏览器 / 不调 LLM）

覆盖日志里定位到的根因：
1. SPA 职位卡片不是 <a href>（腾讯/B站/米哈游/Moka/北森/京东）→ 需要卡片扫描 + 点击取 URL；
2. 详情页 URL 模板写错（B 站多写 /detail）或缺失（米哈游/Moka/北森/腾讯）→ 必须按实测格式构造；
3. 北森详情页只认 guid、腾讯只认 postId，不能拿数字业务 ID 拼 URL；
4. 类别导航误选（把「机械工程师」职位页/百科页/详情页当成「技术类」导航）；
5. 列表 XHR 里不同站点的字段名（positionTitle / JobAdName / postId …）要能认出来；
6. 卡片相关度判定要能剔除「程序&技术类」这类筛选标签。
"""

from src.models.instruction_schemas import TargetInstructionSchema
from src.search.browser_job_finder import (
    CARD_SCAN_JS,
    DETAIL_URL_TEMPLATES,
    BrowserJobFinder,
)
from src.search.query_expander import infer_direction


def _finder():
    return BrowserJobFinder(tavily_api_key="", headless=True, interactive=False)


def _target(**kw):
    # 用真实的「方向推断」结果当词族（与生产链路一致），
    # 而不是手写一份带「工程师/开发」的宽松词表
    d = infer_direction("AI应用开发工程师")
    base = dict(
        company="", role="AI应用开发工程师", location="",
        direction_family=d["key"], direction_category=d["category"],
        title_keywords=d["title_keywords"],
        role_variants=["AI应用开发工程师", "AI应用", "AI开发"],
    )
    base.update(kw)
    return TargetInstructionSchema(**base)


# --------------------------------------------------------------------- #
# 1. 详情页 URL 模板（全部经 tools/verify_detail_urls.py 实测）
# --------------------------------------------------------------------- #
def test_detail_url_templates_for_spa_sites():
    f = _finder()
    cases = [
        ("https://jobs.bilibili.com/campus/positions?type=3", {"id": "30401"},
         "https://jobs.bilibili.com/campus/positions/30401"),
        ("https://jobs.bytedance.com/campus/position?spread=X", {"id": "7669"},
         "https://jobs.bytedance.com/campus/position/7669/detail"),
        ("https://jobs.mihoyo.com/#/campus/position?projectIds%5B0%5D=13", {"id": "9538"},
         "https://jobs.mihoyo.com/#/campus/position/9538"),
        ("https://campus.jd.com/home#/jobs?to=present", {"id": "9114"},
         "https://campus.jd.com/#/details?id=9114"),
        ("https://join.qq.com/post.html?query=p_1", {"id": "1282707398326592512"},
         "https://join.qq.com/post_detail.html?postid=1282707398326592512"),
        ("https://app.mokahr.com/campus-recruitment/zte/46903#/jobs?page=1",
         {"id": "f53af2c5-db6b-4ba2-941d-363818c43b3a"},
         "https://app.mokahr.com/campus-recruitment/zte/46903"
         "#/job/f53af2c5-db6b-4ba2-941d-363818c43b3a"),
    ]
    for page_url, item, expected in cases:
        assert f._build_detail_url(page_url, item) == expected, page_url


def test_zhiye_prefers_guid_over_numeric_id():
    """北森（zhiye）：数字 JobAdId 打不开详情页，必须用 guid"""
    f = _finder()
    page_url = "https://sokon.zhiye.com/campus/jobs?4=%5B%5D"
    guid = "985f0254-9d5e-48d0-89f5-9a472d75ae61"
    url = f._build_detail_url(page_url, {
        "id": "190858674",                       # 数字业务 ID（走这个 URL 是空页）
        "ids": {"jobadid": "190858674", "id": guid},
    })
    assert url == f"https://sokon.zhiye.com/campus/detail?jobAdId={guid}"


def test_tencent_prefers_postid():
    f = _finder()
    url = f._build_detail_url(
        "https://join.qq.com/post.html?query=p_1",
        {"id": "22444", "ids": {"id": "22444", "postid": "1282707398326592512"}},
    )
    assert url == "https://join.qq.com/post_detail.html?postid=1282707398326592512"


def test_unknown_host_gets_no_fake_url():
    """未知站点的接口职位宁可不入库，也不给一个打不开的假 URL"""
    f = _finder()
    assert f._build_detail_url("https://jobs.unknown-corp.com/list", {"id": "123"}) == ""


def test_api_supplied_absolute_link_wins():
    f = _finder()
    item = {"id": "1", "url": "https://careers.example.com/job/abc"}
    assert f._build_detail_url("https://careers.example.com/list", item) == \
        "https://careers.example.com/job/abc"


def test_templates_have_no_unverified_bilibili_detail_suffix():
    assert "/detail" not in DETAIL_URL_TEMPLATES["bilibili.com"]["campus"]


# --------------------------------------------------------------------- #
# 2. 列表 XHR 字段名识别（腾讯 searchPosition / 北森 GetJobAdPageList）
# --------------------------------------------------------------------- #
TENCENT_PAYLOAD = {
    "message": "", "status": 0,
    "data": {"count": 116, "positionList": [{
        "id": 22444, "position": 783, "positionTitle": "AI全栈工程师",
        "positionFamily": 2, "workCities": "深圳总部 北京 上海",
        "positionUrl": None, "postId": 1282707398326592512,
    }]},
}

ZHIYE_PAYLOAD = {
    "Code": 200, "Count": 184,
    "Data": [{
        "Id": "985f0254-9d5e-48d0-89f5-9a472d75ae61", "HeadCount": 0,
        "JobAdId": 190858674, "JobAdName": "问界整车研发-算法工程师【2027届校招】(J21001)",
        "LocNames": "重庆市·两江新区", "Duty": "工作职责：" + "x" * 60,
        "Require": "任职资格：" + "y" * 60,
    }],
}


def test_walk_tencent_searchposition_payload():
    f = _finder()
    found = []
    f._walk_jobs_json(TENCENT_PAYLOAD, found)
    assert len(found) == 1
    job = found[0]
    assert job["title"] == "AI全栈工程师"
    assert job["ids"]["postid"] == "1282707398326592512", "postId 必须留档用于拼详情 URL"
    assert "北京" in job["city"]
    assert f._build_detail_url("https://join.qq.com/post.html", job).endswith(
        "postid=1282707398326592512"
    )


def test_walk_zhiye_jobad_payload():
    f = _finder()
    found = []
    f._walk_jobs_json(ZHIYE_PAYLOAD, found)
    assert len(found) == 1
    job = found[0]
    assert "算法工程师" in job["title"]
    assert job["ids"]["id"] == "985f0254-9d5e-48d0-89f5-9a472d75ae61"
    assert len(job["description"]) >= 30, "接口自带 Duty/Require 应保留下来"
    assert f._build_detail_url("https://sokon.zhiye.com/campus/jobs", job) == (
        "https://sokon.zhiye.com/campus/detail"
        "?jobAdId=985f0254-9d5e-48d0-89f5-9a472d75ae61"
    )


# --------------------------------------------------------------------- #
# 3. 类别导航误选（51job「机械工程师」/ 百科页 / 详情页）
# --------------------------------------------------------------------- #
class _FakePage:
    """最小 page 替身：只需要 url + frames（_collect_anchors 用）"""

    def __init__(self, url):
        self.url = url
        self.frames = []


def _patch_anchors(monkeypatch, finder, anchors):
    async def _fake(page, page_url=None):
        return anchors
    monkeypatch.setattr(finder, "_collect_anchors", _fake)


async def test_category_link_rejects_job_and_foreign_links(monkeypatch):
    f = _finder()
    _patch_anchors(monkeypatch, f, [
        # 51job 的岗位页（日志里被误当成「技术类」导航，导致整站 0 个职位）
        {"text": "机械工程师", "href": "https://jobs.51job.com/jixiegongchengshi/"},
        {"text": "技术类", "href": "https://baike.51job.com/zhiwei/01241/"},
        {"text": "研发类", "href": "https://web.51job.com/campus/tech"},
    ])
    page = _FakePage("https://we.51job.com/pc/search")
    got = await f._find_category_link(page, _target())
    assert got == "https://web.51job.com/campus/tech"


async def test_category_link_rejects_detail_pages(monkeypatch):
    f = _finder()
    _patch_anchors(monkeypatch, f, [
        # Moka 的职位详情页：文本短且含「技术」，曾被当成类别导航
        {"text": "技术中心", "href": "https://app.mokahr.com/campus-recruitment/zte/46903#/job/abc"},
        {"text": "技术中心", "href": "https://app.mokahr.com/campus-recruitment/zte/46903#/jobs?page=2"},
    ])
    page = _FakePage("https://app.mokahr.com/campus-recruitment/zte/46903#/jobs")
    got = await f._find_category_link(page, _target())
    # 该 URL 本身已被识别为职位列表页（/campus-recruitment），直接返回 None 也是
    # 正确结果：既没跳去 #/job/ 详情页，也没跳去 #/jobs?page=2 分页。
    # 这里断言的是「不会导航到职位详情页」，None 与别的列表页都算通过。
    assert not got or "#/job/" not in got


def test_category_terms_exclude_job_words():
    f = _finder()
    terms = f._category_match_terms(_target())
    assert "技术类" in terms
    assert "工程师" not in terms and "开发" not in terms


# --------------------------------------------------------------------- #
# 4. 卡片相关度 / 详情页判定
# --------------------------------------------------------------------- #
def test_card_relevant_skips_filter_chips_and_keeps_jobs():
    f = _finder()
    target = _target()
    for chip in ["程序&技术类", "实习生招聘", "校招职位", "应届实习", "筛选条件",
                 "1. 结合公司运营业务场景，定义数据分析及挖掘问题；"]:
        assert not f._card_relevant(chip, target), chip
    for job in ["AI全栈工程师", "大模型应用算法工程师 - TikTok内容安全算法",
                "Agent开发工程师", "AI应用工程师"]:
        assert f._card_relevant(job, target), job


def test_looks_like_detail_url():
    f = _finder()
    ok = [
        "https://join.qq.com/post_detail.html?postid=128",
        "https://sokon.zhiye.com/campus/detail?jobAdId=985f",
        "https://app.mokahr.com/campus-recruitment/zte/46903#/job/f53a",
        "https://jobs.bilibili.com/campus/positions/30401",
        "https://jobs.bytedance.com/campus/position/7669/detail",
        "https://www.zhipin.com/job_detail/abc.html",
    ]
    bad = [
        "https://join.qq.com/post.html?query=p_1,p_2",
        "https://jobs.mihoyo.com/#/campus/position?projectIds%5B1%5D=4&jobName=",
        "https://sokon.zhiye.com/intern",
    ]
    for u in ok:
        assert f._looks_like_detail_url(u), u
    for u in bad:
        assert not f._looks_like_detail_url(u), u


def test_same_list_page():
    f = _finder()
    list_url = "https://app.mokahr.com/campus-recruitment/zte/46903#/jobs?page=1"
    assert f._same_list_page(
        "https://app.mokahr.com/campus-recruitment/zte/46903#/jobs?page=2", list_url)
    assert not f._same_list_page(
        "https://app.mokahr.com/campus-recruitment/zte/46903#/job/abc", list_url)
    assert not f._same_list_page(
        "https://sokon.zhiye.com/campus/detail?jobAdId=x", list_url)


# --------------------------------------------------------------------- #
# 5. 卡片扫描脚本自身约束
# --------------------------------------------------------------------- #
def test_card_scan_js_has_safety_and_rescan_guards():
    assert "data-dsh-card" in CARD_SCAN_JS
    # 重扫前必须清掉上一轮标记，否则点过一次后第二轮扫不到任何卡片
    assert 'removeAttribute("data-dsh-card")' in CARD_SCAN_JS
    # 不点申请/投递类按钮（AGENTS.md：绝不自动提交申请）
    for word in ["投递", "申请", "submit", "apply"]:
        assert word in CARD_SCAN_JS


# --------------------------------------------------------------------- #
# 6. 方向相关性：短英文关键词按词边界匹配、通用岗位词不算方向
# --------------------------------------------------------------------- #
def test_short_ascii_keyword_needs_word_boundary():
    f = _finder()
    assert f._kw_hit("ai 工程师", "ai")
    assert f._kw_hit("AI应用开发", "ai")
    # 'ai' 不该在 Baidu / Email / Daily 里命中
    assert not f._kw_hit("baidu 招聘", "ai")
    assert not f._kw_hit("email marketing", "ai")
    assert not f._kw_hit("daily report 专员", "ai")
    # 长关键词仍是子串匹配
    assert f._kw_hit("机器学习平台开发", "机器学习")


def test_title_relevance_ignores_generic_role_words():
    """搜 AI 方向时，只含「工程师/开发」的无关岗位不该被判为相关"""
    f = _finder()
    target = _target()
    assert f._title_relevant("AI算法工程师", target)
    assert f._title_relevant("大模型应用开发", target)
    assert not f._title_relevant("个人护理产品创新研发工程师", target)
    assert not f._title_relevant("汽车产品工程师", target)
    assert not f._title_relevant("复合材料工艺工程师", target)


def test_clean_job_title_strips_card_noise():
    f = _finder()
    assert f._clean_job_title(
        "急 软件开发工程师 发布于 2026-08-31 本科 本科 | 江苏·南京市 湖北·武汉市"
    ) == "软件开发工程师"
    titled = f._clean_job_title(
        "个人护理产品创新研发工程师 (MJ000488) 9千-1.2万 重庆登康口腔护理用品 重庆·两江新区"
    )
    assert titled.startswith("个人护理产品创新研发工程师")
    assert "9千" not in titled


def test_aggregator_portal_does_not_keep_all_when_nothing_matches():
    """聚合门户（前程无忧等）列表是全网岗位：方向无命中时不能兜底全留"""
    f = _finder()
    scored = [(3, {"text": "个人护理产品创新研发工程师", "href": "https://jobs.51job.com/x/1.html"}),
              (3, {"text": "汽车产品工程师", "href": "https://jobs.51job.com/x/2.html"})]
    assert f._prune_by_title_relevance(scored, ["ai", "算法"], keep_all_when_empty=False) == []
    # 公司官网通道保持兜底行为（避免整站空结果）
    assert len(f._prune_by_title_relevance(scored, ["ai", "算法"])) == 2
    assert not f._strict_relevance("https://jobs.bilibili.com/campus/positions")
    assert f._strict_relevance("https://we.51job.com/pc/search")


async def test_page_looks_blocked_needs_no_usable_job_list():
    """页面已有职位链接时不算被挡（智联正常页面里也带验证组件提示）"""
    f = _finder()

    class _Page:
        url = "https://www.zhaopin.com/companydetail/jobs-CZ1/"

        def __init__(self, links):
            self._links = links

        async def eval_on_selector_all(self, sel, js):
            return self._links

        async def inner_text(self, sel):
            return "验证码 请完成安全验证 " + "职位说明" * 60

    many = [f"https://www.zhaopin.com/jobdetail/CC{i}.htm" for i in range(10)]
    none = ["https://www.zhaopin.com/", "https://www.zhaopin.com/about/"]
    assert await f._page_looks_blocked(_Page(many)) == ""
    assert await f._page_looks_blocked(_Page(none)) == "captcha"


# --------------------------------------------------------------------- #
# 7. 接口通道过滤 / 低分兜底 / 类别导航自纠错
# --------------------------------------------------------------------- #
def test_jobs_from_api_strict_filters_unrelated_titles():
    """接口通道 strict 时不能把财务/市场这类岗位当相关岗位混进来"""
    f = _finder()
    target = _target()
    items = [
        {"title": "AI算法工程师", "id": "1"},
        {"title": "财务（统招）", "id": "2"},
        {"title": "国际化市场品牌-美洲区域方向", "id": "3"},
    ]
    seen = set()
    kept = f._jobs_from_api(
        items, "https://join.qq.com/post.html", target, "腾讯", "", seen, 10, strict=True)
    assert [j["title"] for j in kept] == ["AI算法工程师"]
    assert kept[0]["title_score"] == 10

    seen2 = set()
    # 非 strict 通道 + 一个关键词都没命中时保留全部（站点级兜底会再降权）
    loose = f._jobs_from_api(
        [{"title": "财务（统招）", "id": "2"},
         {"title": "国际化市场品牌-美洲区域方向", "id": "3"}],
        "https://join.qq.com/post.html", target, "腾讯", "", seen2, 10, strict=False)
    assert len(loose) == 2, "非 strict 通道在没有命中项时保留原行为（由站点级兜底负责降权）"


def test_fallback_site_jobs_are_ranked_last():
    """整站无相关岗位时的兜底：仍要求像职位，但 title_score 只给 1"""
    f = _finder()
    target = _target()
    scored_all = [
        (5, {"text": "财务（统招）", "href": "https://jobs.mihoyo.com/#/campus/position/9164"}),
        (5, {"text": "浏览器渲染工程师", "href": "https://jobs.mihoyo.com/#/campus/position/9538"}),
        (0, {"text": "首页", "href": "https://jobs.mihoyo.com/"}),
    ]
    jobs = f._fallback_site_jobs(
        [], scored_all, "https://jobs.mihoyo.com/#/campus/position?projectIds%5B0%5D=13",
        target, "米哈游校招", set(), 10)
    assert jobs, "整站无相关岗位时不该静默返回空"
    assert all(j["title_score"] == 1 for j in jobs)
    assert all(j["source"] == "browser_fallback" for j in jobs)


def test_has_relevant_anchor():
    f = _finder()
    assert not f._has_relevant_anchor([], ["ai"])
    assert not f._has_relevant_anchor(
        [(3, {"text": "质量工程师", "href": "https://x/1.html"})], ["ai", "算法"])
    assert f._has_relevant_anchor(
        [(3, {"text": "AI算法工程师", "href": "https://x/2.html"})], ["ai", "算法"])
    # 没有方向词族时无法判定，视为有相关（不做否判定）
    assert f._has_relevant_anchor([(3, {"text": "x", "href": "https://x/3.html"})], [])


def test_has_relevant_api():
    f = _finder()
    assert not f._has_relevant_api([{"title": "财务（统招）"}, {"title": "市场品牌"}], ["ai"])
    assert f._has_relevant_api([{"title": "AI应用工程师"}], ["ai"])
    # 无方向词族时只要有接口职位就算（不做否判定）
    assert f._has_relevant_api([{"title": "财务（统招）"}], [])


# --------------------------------------------------------------------- #
# 8. URL 去重：同一岗位带不同跟踪参数不能入库两次
# --------------------------------------------------------------------- #
def test_dedupe_key_ignores_tracking_params():
    f = _finder()
    a = "https://jobs.bytedance.com/campus/position/7669711026486085893/detail"
    b = a + "?spread=DWA3PQP"
    assert f._dedupe_key(a) == f._dedupe_key(b)
    c = "https://www.liepin.com/job/1984148871.shtml"
    d = c + "?pgRef=c_pc_industry_search_page%3Ac_pc_industry_search_job_listcard"
    assert f._dedupe_key(c) == f._dedupe_key(d)
    e = "https://jobs.51job.com/chongqing-ljxq/173707736.html?s=pchome_jobgroup_joblist&t=0_0&req=abc"
    assert f._dedupe_key(e) == "https://jobs.51job.com/chongqing-ljxq/173707736.html?#"
    # 业务参数必须保留，否则不同岗位会被并成一个
    j1 = "https://campus.jd.com/#/details?id=9114"
    j2 = "https://campus.jd.com/#/details?id=9095"
    assert f._dedupe_key(j1) != f._dedupe_key(j2)
    assert "id=9114" in f._dedupe_key(j1)


def test_mark_seen_dedupes_across_channels():
    f = _finder()
    seen = set()
    url = "https://jobs.bytedance.com/campus/position/7669/detail"
    assert f._mark_seen(seen, url) is True
    assert f._mark_seen(seen, url + "?spread=DWA3PQP") is False, "同岗位带跟踪参数应视为重复"
    assert f._mark_seen(seen, url + "/") is False
