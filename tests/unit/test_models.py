"""数据模型单元测试。

覆盖：Pydantic 校验、枚举状态、extra="forbid"、默认值。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.application import ApplicationRecord, ApplicationStatus, RunRecord, RunStatus
from src.models.job import JobDetail, JobPosting
from src.models.match import FillField, FillStatus, MatchResult, QuotaSortResult, TitleScreenResult
from src.models.profile import Education, Resume, UserProfile, WorkExperience


# ============================================================
# UserProfile / Resume
# ============================================================

class TestUserProfile:
    def test_default_empty(self):
        p = UserProfile()
        assert p.name == ""
        assert p.skills == []
        assert p.education == []

    def test_full_profile(self):
        p = UserProfile(
            name="张三",
            phone="13800138000",
            email="zhangsan@example.com",
            target_directions=["AI Agent开发", "后端开发"],
            target_cities=["北京", "深圳"],
        )
        assert p.name == "张三"
        assert len(p.target_directions) == 2

    def test_extra_fields_rejected(self):
        """extra="forbid"：未定义字段应抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            UserProfile(name="张三", unknown_field="value")

    def test_to_resume_text(self):
        p = UserProfile(name="张三", skills=["Python", "Go"])
        text = p.to_resume_text()
        assert "张三" in text
        assert "Python" in text
        assert "Go" in text


class TestResume:
    def test_from_raw_text(self):
        r = Resume(raw_text="这是简历文本", source_file="resume.pdf")
        assert r.full_text() == "这是简历文本"

    def test_from_profile(self):
        p = UserProfile(name="李四")
        r = Resume(profile=p)
        assert "李四" in r.full_text()

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            Resume(raw_text="test", extra="bad")


# ============================================================
# JobPosting / JobDetail
# ============================================================

class TestJobPosting:
    def test_required_title_and_url(self):
        job = JobPosting(title="后端工程师", detail_url="https://example.com/job/1")
        assert job.title == "后端工程师"
        assert job.dedup_key() == "https://example.com/job/1"

    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            JobPosting(detail_url="https://example.com/job/1")

    def test_missing_url_raises(self):
        with pytest.raises(ValidationError):
            JobPosting(title="后端工程师")


class TestJobDetail:
    def test_jd_for_match_with_parts(self):
        detail = JobDetail(
            posting=JobPosting(title="测试", detail_url="https://example.com/1"),
            responsibilities="负责后端开发",
            requirements="3年以上经验",
        )
        text = detail.jd_for_match()
        assert "岗位职责" in text
        assert "负责后端开发" in text
        assert "任职要求" in text

    def test_jd_for_match_fallback_to_full(self):
        detail = JobDetail(
            posting=JobPosting(title="测试", detail_url="https://example.com/1"),
            full_jd="完整JD文本",
        )
        assert detail.jd_for_match() == "完整JD文本"


# ============================================================
# MatchResult / FillField
# ============================================================

class TestMatchResult:
    def test_score_range(self):
        r = MatchResult(job_url="https://example.com/1", score=85)
        assert r.score == 85

    def test_score_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            MatchResult(job_url="https://example.com/1", score=150)
        with pytest.raises(ValidationError):
            MatchResult(job_url="https://example.com/1", score=-1)

    def test_default_values(self):
        r = MatchResult(job_url="https://example.com/1")
        assert r.score == 0
        assert r.direction_match is False
        assert r.matched_points == []


class TestFillField:
    def test_default_status_pending(self):
        f = FillField(label="姓名", field_type="text")
        assert f.status == FillStatus.PENDING
        assert f.value is None

    def test_options_for_select(self):
        f = FillField(label="学历", field_type="select", options=["本科", "硕士", "博士"])
        assert len(f.options) == 3

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            FillField(label="姓名", unknown="bad")


class TestTitleScreenResult:
    def test_default_empty(self):
        r = TitleScreenResult()
        assert r.related_indices == []
        assert r.unrelated_indices == []


class TestQuotaSortResult:
    def test_recommended_indices(self):
        r = QuotaSortResult(recommended=[0, 2, 5], reasoning="优先目标方向")
        assert len(r.recommended) == 3
        assert "目标方向" in r.reasoning


# ============================================================
# ApplicationRecord / RunRecord
# ============================================================

class TestApplicationStatus:
    def test_enum_values(self):
        assert ApplicationStatus.PENDING.value == "pending"
        assert ApplicationStatus.FORM_FILLED.value == "form_filled"
        assert ApplicationStatus.WAITING_FOR_SUBMIT.value == "waiting_for_submit"
        assert ApplicationStatus.USER_CONFIRMED_SUBMIT.value == "user_confirmed_submit"
        assert ApplicationStatus.PAGE_VERIFIED.value == "page_verified"
        assert ApplicationStatus.FAILED.value == "failed"
        assert ApplicationStatus.UNKNOWN.value == "unknown"

    def test_distinct_states(self):
        """各状态必须严格区分，不得混淆。"""
        states = {s.value for s in ApplicationStatus}
        assert len(states) == 7
        assert "form_filled" in states
        assert "waiting_for_submit" in states
        assert "user_confirmed_submit" in states
        assert "page_verified" in states


class TestApplicationRecord:
    def test_default_status(self):
        r = ApplicationRecord(job_url="https://example.com/1", job_title="测试")
        assert r.status == ApplicationStatus.PENDING
        assert r.filled_fields == 0

    def test_status_transition(self):
        r = ApplicationRecord(job_url="https://example.com/1")
        r.status = ApplicationStatus.FORM_FILLED
        assert r.status == ApplicationStatus.FORM_FILLED
        r.status = ApplicationStatus.WAITING_FOR_SUBMIT
        assert r.status == ApplicationStatus.WAITING_FOR_SUBMIT


class TestRunStatus:
    def test_enum_values(self):
        assert RunStatus.PENDING.value == "pending"
        assert RunStatus.RUNNING.value == "running"
        assert RunStatus.WAITING_FOR_USER.value == "waiting_for_user"
        assert RunStatus.COMPLETED.value == "completed"
        assert RunStatus.FAILED.value == "failed"
        assert RunStatus.INTERRUPTED.value == "interrupted"


class TestRunRecord:
    def test_default_values(self):
        r = RunRecord(run_id="test123")
        assert r.run_id == "test123"
        assert r.status == RunStatus.PENDING
        assert r.jobs_discovered == 0
        assert r.llm_calls == 0

    def test_add_error(self):
        r = RunRecord(run_id="test123")
        for i in range(25):
            r.add_error("node", f"error {i}")
        assert len(r.errors) == 20  # 最多保留20条
        assert r.errors[0].startswith("[node]")

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            RunRecord(run_id="test", unknown="bad")


# ============================================================
# Education / WorkExperience
# ============================================================

class TestEducation:
    def test_defaults(self):
        e = Education()
        assert e.school == ""
        assert e.degree == ""


class TestWorkExperience:
    def test_defaults(self):
        w = WorkExperience()
        assert w.company == ""
        assert w.responsibilities == ""
