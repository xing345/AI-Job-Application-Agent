"""JD 提取、匹配结果、配额排序单元测试。

覆盖：MatchResult 模型校验、硬性要求字段、排序键逻辑、回退排序、
字节跳动 JD 文本拆分、元信息解析。
"""
from __future__ import annotations

import pytest

from src.models.job import JobDetail, JobPosting
from src.models.match import MatchResult
from src.agent.nodes.confirm_list import _fallback_sort, _sort_key


class TestMatchResultModel:
    """MatchResult 模型校验测试。"""

    def test_basic_fields(self):
        r = MatchResult(job_url="https://example.com/1", job_title="前端开发", score=85)
        assert r.score == 85
        assert r.job_title == "前端开发"
        assert r.hard_requirements_total == 0
        assert r.hard_requirements_met == 0

    def test_score_range(self):
        """分数必须在 0-100 之间。"""
        with pytest.raises(Exception):
            MatchResult(job_url="https://example.com/1", score=101)
        with pytest.raises(Exception):
            MatchResult(job_url="https://example.com/1", score=-1)

    def test_hard_requirements_fields(self):
        r = MatchResult(
            job_url="https://example.com/1",
            hard_requirements_total=5,
            hard_requirements_met=4,
            matched_points=["[硬性] 3年前端开发经验", "[加分] React经验"],
            missing_points=["[硬性]  TypeScript经验"],
        )
        assert r.hard_requirements_total == 5
        assert r.hard_requirements_met == 4
        assert len(r.matched_points) == 2
        assert "[硬性]" in r.matched_points[0]
        assert "[加分]" in r.matched_points[1]

    def test_extra_fields_rejected(self):
        with pytest.raises(Exception):
            MatchResult(job_url="https://example.com/1", unknown_field="bad")

    def test_default_lists_empty(self):
        r = MatchResult(job_url="https://example.com/1")
        assert r.matched_points == []
        assert r.missing_points == []
        assert r.reason == ""


class TestSortKey:
    """排序键逻辑测试。"""

    def test_higher_score_first(self):
        r1 = MatchResult(job_url="1", score=90)
        r2 = MatchResult(job_url="2", score=80)
        assert _sort_key(r1) > _sort_key(r2)

    def test_hard_ratio_breaks_tie(self):
        """同分时，硬性要求满足度高的排前面。"""
        r1 = MatchResult(job_url="1", score=80, hard_requirements_total=5, hard_requirements_met=5)
        r2 = MatchResult(job_url="2", score=80, hard_requirements_total=5, hard_requirements_met=3)
        assert _sort_key(r1) > _sort_key(r2)

    def test_direction_breaks_tie(self):
        """同分时，方向匹配的排前面。"""
        r1 = MatchResult(job_url="1", score=80, direction_match=True)
        r2 = MatchResult(job_url="2", score=80, direction_match=False)
        assert _sort_key(r1) > _sort_key(r2)

    def test_no_hard_requirements_default_ratio_zero(self):
        """无硬性要求时，满足比例为 0。"""
        r = MatchResult(job_url="1", score=80, hard_requirements_total=0)
        key = _sort_key(r)
        assert key[1] == 0  # hard_ratio


class TestFallbackSort:
    """回退排序逻辑测试。"""

    def _make_detail(self, title: str, url: str) -> JobDetail:
        return JobDetail(
            posting=JobPosting(title=title, detail_url=url, site_name="test"),
        )

    def test_sorts_by_score_descending(self):
        details = [self._make_detail(f"岗位{i}", f"https://example.com/{i}") for i in range(3)]
        matches = [
            MatchResult(job_url="https://example.com/0", score=60),
            MatchResult(job_url="https://example.com/1", score=90),
            MatchResult(job_url="https://example.com/2", score=75),
        ]
        result = _fallback_sort(details, matches, max_count=3)
        assert result == [1, 2, 0]  # 90, 75, 60

    def test_respects_max_count(self):
        details = [self._make_detail(f"岗位{i}", f"https://example.com/{i}") for i in range(5)]
        matches = [MatchResult(job_url=f"https://example.com/{i}", score=100 - i * 10) for i in range(5)]
        result = _fallback_sort(details, matches, max_count=2)
        assert len(result) == 2
        assert result == [0, 1]

    def test_tie_breaker_hard_ratio(self):
        details = [self._make_detail(f"岗位{i}", f"https://example.com/{i}") for i in range(2)]
        matches = [
            MatchResult(job_url="https://example.com/0", score=80, hard_requirements_total=5, hard_requirements_met=3),
            MatchResult(job_url="https://example.com/1", score=80, hard_requirements_total=5, hard_requirements_met=5),
        ]
        result = _fallback_sort(details, matches, max_count=2)
        assert result == [1, 0]  # 硬性要求满足度高的排前面

    def test_empty_candidates(self):
        result = _fallback_sort([], [], max_count=5)
        assert result == []


class TestBytedanceJdExtraction:
    """字节跳动 JD 提取工具方法测试（不启动浏览器）。"""

    def test_split_jd_text_with_both_sections(self):
        from src.search.adapters.bytedance import BytedanceAdapter
        from src.search.site_registry import get_site_config
        config = get_site_config("bytedance")
        adapter = BytedanceAdapter(config)

        text = """岗位概述
我们正在寻找优秀的前端开发工程师。

岗位职责
1. 负责公司Web产品的前端开发
2. 与设计师和后端工程师协作
3. 优化前端性能

任职要求
1. 本科及以上学历，计算机相关专业
2. 3年以上前端开发经验
3. 熟悉React/Vue框架
4. 有良好的沟通能力"""

        resp, req = adapter._split_jd_text(text)
        assert "岗位职责" in resp
        assert "前端开发" in resp
        assert "任职要求" in req
        assert "本科" in req
        assert "React" in req

    def test_split_jd_text_only_requirements(self):
        from src.search.adapters.bytedance import BytedanceAdapter
        from src.search.site_registry import get_site_config
        config = get_site_config("bytedance")
        adapter = BytedanceAdapter(config)

        text = """任职要求
1. 本科及以上学历
2. 熟悉Python"""

        resp, req = adapter._split_jd_text(text)
        assert resp == ""  # 没有岗位职责部分
        assert "任职要求" in req

    def test_parse_meta_text(self):
        from src.search.adapters.bytedance import BytedanceAdapter
        from src.search.site_registry import get_site_config
        config = get_site_config("bytedance")
        adapter = BytedanceAdapter(config)

        # 标准格式
        loc, cat = adapter._parse_meta_text("北京 · 抖音 · 技术")
        assert loc == "北京"
        assert "抖音" in cat
        assert "技术" in cat

        # 只有地点
        loc, cat = adapter._parse_meta_text("上海")
        assert loc == "上海"
        assert cat == ""

        # 用 | 分隔
        loc, cat = adapter._parse_meta_text("深圳 | 腾讯 | 产品")
        assert loc == "深圳"
        assert "腾讯" in cat

    def test_adapter_has_jd_extract_method(self):
        from src.search.adapters.bytedance import BytedanceAdapter
        assert hasattr(BytedanceAdapter, "extract_jd_detail")
        assert hasattr(BytedanceAdapter, "_extract_jd_title")
        assert hasattr(BytedanceAdapter, "_extract_jd_meta")
        assert hasattr(BytedanceAdapter, "_extract_jd_content")
        assert hasattr(BytedanceAdapter, "_split_jd_text")
