"""站点适配器与 URL 规范化单元测试。

覆盖：normalize_url、SiteAdapter 基类工具方法、字节跳动适配器注册、
discoverer 适配器路由、兜底 URL 规则收紧。
"""
from __future__ import annotations

import pytest

from src.models.job import JobPosting
from src.search.adapters import get_adapter, list_adapters, normalize_url
from src.search.adapters.base import SiteAdapter
from src.search.adapters.bytedance import BytedanceAdapter
from src.search.site_registry import SiteConfig, get_site_config


class TestNormalizeUrl:
    """URL 规范化测试。"""

    def test_relative_to_absolute(self):
        result = normalize_url("/campus/position/123/detail", "https://jobs.bytedance.com")
        assert result == "https://jobs.bytedance.com/campus/position/123/detail"

    def test_remove_fragment(self):
        result = normalize_url("https://example.com/job/123#section")
        assert result == "https://example.com/job/123"

    def test_remove_trailing_slash(self):
        result = normalize_url("https://example.com/job/123/")
        assert result == "https://example.com/job/123"

    def test_preserve_root_slash(self):
        """根路径的斜杠不应被移除。"""
        result = normalize_url("https://example.com/")
        assert result == "https://example.com/"

    def test_remove_tracking_params(self):
        result = normalize_url("https://example.com/job/123?utm_source=wechat&spm=abc&id=456")
        assert "utm_source" not in result
        assert "spm" not in result
        assert "id=456" in result  # 非跟踪参数保留

    def test_lowercase_scheme_and_netloc(self):
        result = normalize_url("HTTPS://Example.COM/Job/123")
        assert result.startswith("https://example.com/")

    def test_empty_url(self):
        assert normalize_url("") == ""
        assert normalize_url(None) == ""

    def test_preserve_job_id_in_query(self):
        """岗位 ID 在查询参数中时应保留。"""
        result = normalize_url("https://example.com/detail?positionId=123456&from=list")
        assert "positionId=123456" in result
        assert "from=" not in result  # from 是跟踪参数


class TestSiteAdapterBase:
    """SiteAdapter 基类工具方法测试。"""

    def _make_config(self) -> SiteConfig:
        return SiteConfig(
            name="test",
            base_url="https://example.com",
            category_url="https://example.com/jobs",
            job_card_selector="",
            max_pages=10,
        )

    def _make_adapter(self) -> SiteAdapter:
        # 使用 BytedanceAdapter 作为具体实现来测试基类方法
        config = self._make_config()
        config.name = "bytedance"
        return BytedanceAdapter(config)

    def test_make_job_posting_basic(self):
        adapter = self._make_adapter()
        job = adapter._make_job_posting(
            title="前端开发工程师",
            detail_url="/campus/position/123/detail",
            company="字节跳动",
            location="北京",
        )
        assert job is not None
        assert job.title == "前端开发工程师"
        assert job.company == "字节跳动"
        assert job.location == "北京"
        assert job.detail_url.startswith("https://")

    def test_make_job_posting_empty_title(self):
        adapter = self._make_adapter()
        assert adapter._make_job_posting(title="", detail_url="/job/1") is None

    def test_make_job_posting_empty_url(self):
        adapter = self._make_adapter()
        assert adapter._make_job_posting(title="测试", detail_url="") is None

    def test_make_job_posting_title_too_long(self):
        adapter = self._make_adapter()
        long_title = "a" * 201
        assert adapter._make_job_posting(title=long_title, detail_url="/job/1") is None

    def test_dedup_jobs(self):
        adapter = self._make_adapter()
        jobs = [
            JobPosting(title="A", detail_url="https://example.com/job/1", site_name="test"),
            JobPosting(title="B", detail_url="https://example.com/job/2", site_name="test"),
            JobPosting(title="A-dup", detail_url="https://example.com/job/1", site_name="test"),
        ]
        unique = adapter._dedup_jobs(jobs)
        assert len(unique) == 2
        assert unique[0].title == "A"  # 保留先出现的

    def test_is_noise_title(self):
        adapter = self._make_adapter()
        assert adapter._is_noise_title("首页") is True
        assert adapter._is_noise_title("登录") is True
        assert adapter._is_noise_title("北京") is True
        assert adapter._is_noise_title("前端开发工程师") is False
        assert adapter._is_noise_title("Java 后端") is False


class TestBytedanceAdapter:
    """字节跳动适配器测试。"""

    def test_adapter_registered(self):
        assert get_adapter("bytedance") is BytedanceAdapter

    def test_adapter_not_found(self):
        assert get_adapter("nonexistent_site") is None

    def test_list_adapters_contains_bytedance(self):
        assert "bytedance" in list_adapters()

    def test_site_name(self):
        assert BytedanceAdapter.site_name == "bytedance"

    def test_company_name(self):
        assert BytedanceAdapter.company_name == "字节跳动"

    def test_card_selector(self):
        assert "/campus/position/" in BytedanceAdapter.CARD_SELECTOR
        assert "/detail" in BytedanceAdapter.CARD_SELECTOR

    def test_init_uses_config_max_pages(self):
        config = get_site_config("bytedance")
        adapter = BytedanceAdapter(config)
        assert adapter.max_pages == config.max_pages

    @pytest.mark.asyncio
    async def test_extract_meta_pipe_separated(self):
        """测试元信息解析：地点 | 团队 | 类别"""
        config = get_site_config("bytedance")
        adapter = BytedanceAdapter(config)

        # Mock ElementHandle
        class MockCard:
            async def query_selector(self, sel):
                return None
            async def inner_text(self):
                return "前端开发工程师\n北京 · 抖音 · 技术"

        card = MockCard()
        location, category = await adapter._extract_meta(card)
        assert location == "北京"
        assert "抖音" in category
        assert "技术" in category

    @pytest.mark.asyncio
    async def test_extract_meta_single_part(self):
        """只有地点时。"""
        config = get_site_config("bytedance")
        adapter = BytedanceAdapter(config)

        class MockCard:
            async def query_selector(self, sel):
                return None
            async def inner_text(self):
                return "测试岗位\n上海"

        card = MockCard()
        location, category = await adapter._extract_meta(card)
        assert location == "上海"
        assert category == ""


class TestDiscovererAdapterRouting:
    """discoverer 适配器路由测试（不实际启动浏览器）。"""

    def test_get_adapter_for_bytedance(self):
        from src.search.adapters import get_adapter
        assert get_adapter("bytedance") is not None

    def test_get_adapter_case_insensitive(self):
        from src.search.adapters import get_adapter
        assert get_adapter("BYTEDANCE") is BytedanceAdapter
        assert get_adapter("Bytedance") is BytedanceAdapter

    def test_no_adapter_for_unknown_site(self):
        from src.search.adapters import get_adapter
        assert get_adapter("unknown_site_12345") is None


class TestTightenedUrlFallback:
    """兜底 URL 规则收紧测试。"""

    def test_job_url_with_keyword_and_digits(self):
        """包含岗位关键词和6位数字应匹配。"""
        from src.search.discoverer import _is_job_detail_url
        config = SiteConfig(name="test", base_url="https://example.com",
                            category_url="https://example.com/jobs", job_card_selector="")
        assert _is_job_detail_url("https://example.com/position/123456", config) is True

    def test_url_with_digits_but_no_keyword(self):
        """只有数字没有岗位关键词不应匹配（收紧后）。"""
        from src.search.discoverer import _is_job_detail_url
        config = SiteConfig(name="test", base_url="https://example.com",
                            category_url="https://example.com/jobs", job_card_selector="")
        # 纯数字路径，无岗位关键词
        assert _is_job_detail_url("https://example.com/article/123456", config) is False

    def test_pagination_url_excluded(self):
        """分页 URL 不应匹配。"""
        from src.search.discoverer import _is_job_detail_url
        config = SiteConfig(name="test", base_url="https://example.com",
                            category_url="https://example.com/jobs", job_card_selector="")
        assert _is_job_detail_url("https://example.com/jobs/page/2", config) is False
