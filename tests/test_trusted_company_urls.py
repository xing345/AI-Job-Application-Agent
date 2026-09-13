"""
用户显式指定「公司名 + 招聘官网 URL」时的回归测试（离线，不联网不起浏览器）

覆盖 2026-09-12 线上事故：
- 用户输入 https://jobs.bilibili.com/... 与 https://campus.jd.com/...，
  被 _classify_company_result 的聚合/垃圾域名黑名单按子串匹配直接丢弃，
  公司通道最终只剩公司名、且解析到错误招聘页，抽取 0 个职位。
修复约定：
1. trusted=True（用户显式 URL）只做格式校验，跳过黑名单/登录主机/第三方路径过滤；
2. 黑名单匹配从「整 URL 子串」改为「主机名主域/子域精确匹配」，自动发现降噪行为不变。
"""

import pytest

from src.models.instruction_schemas import TargetInstructionSchema
from src.search.browser_job_finder import BrowserJobFinder
from src.search.query_expander import expand_role_variants


def _target(role: str = "AI应用开发工程师") -> TargetInstructionSchema:
    return TargetInstructionSchema(
        company="", role=role, location="",
        keywords=["Python"],
        role_variants=expand_role_variants(role, ["Python"]),
    )


BILI_URL = "https://jobs.bilibili.com/campus/positions?type=3"
JD_URL = "https://campus.jd.com/home#/jobs?to=present&type=present"


# ---------------------------------------------------------------- #
# 1. 用户显式 URL：即使域名在黑名单上也必须保留，并正确识别为招聘页
# ---------------------------------------------------------------- #
def test_trusted_url_bypasses_blacklist():
    finder = BrowserJobFinder(tavily_api_key="")

    # 修复前：两个 URL 分别命中 AGGREGATOR_DOMAINS["bilibili.com"]
    # 与 JUNK_DOMAINS["jd.com"]，分类直接返回 None 被丢弃
    assert finder._classify_company_result(BILI_URL, trusted=True) == "career"
    assert finder._classify_company_result(JD_URL, trusted=True) == "career"

    # 非 http(s) 的 URL 仍然拒绝（只做格式校验，不是全盘放行）
    assert finder._classify_company_result("ftp://jobs.bilibili.com/x", trusted=True) is None
    assert finder._classify_company_result("not-a-url", trusted=True) is None


def test_auto_discovery_blacklist_still_active():
    """自动发现（非 trusted）仍然按黑名单降噪，行为不回退"""
    finder = BrowserJobFinder(tavily_api_key="")
    assert finder._classify_company_result(BILI_URL) is None
    assert finder._classify_company_result(JD_URL) is None
    assert finder._classify_company_result("https://www.zhihu.com/question/1") is None


# ---------------------------------------------------------------- #
# 2. 黑名单改主机精确匹配：子域仍拦截，但不再误伤 query/path 与同串域名
# ---------------------------------------------------------------- #
def test_host_patterns_match_subdomain_but_not_substring():
    finder = BrowserJobFinder(tavily_api_key="")

    # 子域仍然算命中（自动发现时拦截 jobs.bilibili.com / campus.jd.com）
    assert finder._is_aggregator(BILI_URL) is True
    assert finder._is_junk(JD_URL) is True

    # 旧实现是整 URL 子串匹配：query/path 里出现黑名单串会误伤
    assert finder._is_junk("https://example.com/?ref=jd.com") is False
    # 旧实现 "x.com" in "fox.com" / "jd.com" in "notjd.com" 误判，现在不允许
    assert finder._is_aggregator("https://fox.com/news") is False
    assert finder._is_junk("https://notjd.com/join") is False

    # 真正的主域/子域仍然命中
    assert finder._is_junk("https://www.jd.com/") is True
    assert finder._is_aggregator("https://www.zhihu.com/x") is True


# ---------------------------------------------------------------- #
# 3. 候选构建：用户给的 URL 必须进入候选、排在前面，并带上 trusted 标记
# ---------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_company_candidates_keep_user_urls():
    finder = BrowserJobFinder(tavily_api_key="")

    async def _no_search(*args, **kwargs):
        # 公司名解析走 Tavily，离线测试里一律返回空，只验证 URL 分支
        return []

    finder._tavily_search = _no_search

    known = ["哔哩哔哩", BILI_URL, "京东", JD_URL]
    candidates = await finder._discover_company_candidates(_target(), known)

    by_host = {__import__("urllib.parse", fromlist=["urlparse"]).urlparse(c["url"]).netloc: c
               for c in candidates}
    assert "jobs.bilibili.com" in by_host, "用户显式 URL 被过滤掉了，bug 回归"
    assert "campus.jd.com" in by_host, "用户显式 URL 被过滤掉了，bug 回归"

    bili = by_host["jobs.bilibili.com"]
    assert bili["career_url"] == BILI_URL
    assert bili["trusted"] is True

    # 带 career_url 的可直达候选必须排在最前（公司通道会优先进入）
    assert candidates[0].get("career_url"), "可直达招聘页应排在候选最前"
