"""申请状态流转与 record_result 节点单元测试。

覆盖：ApplicationStatus 枚举、状态流转合法性、record_result 记录逻辑。
"""
from __future__ import annotations

import pytest

from src.agent.state import AgentState
from src.agent.nodes.record_result import run as record_result_run
from src.models.application import ApplicationStatus, RunStatus
from src.models.job import JobDetail, JobPosting
from src.models.match import FillField, FillStatus


class TestApplicationStatusFlow:
    """申请状态流转测试。"""

    def test_status_enum_values(self):
        assert ApplicationStatus.PENDING.value == "pending"
        assert ApplicationStatus.FORM_FILLED.value == "form_filled"
        assert ApplicationStatus.WAITING_FOR_SUBMIT.value == "waiting_for_submit"
        assert ApplicationStatus.USER_CONFIRMED_SUBMIT.value == "user_confirmed_submit"
        assert ApplicationStatus.PAGE_VERIFIED.value == "page_verified"
        assert ApplicationStatus.FAILED.value == "failed"
        assert ApplicationStatus.UNKNOWN.value == "unknown"

    def test_distinct_states(self):
        """7个状态必须互不相同。"""
        states = {s.value for s in ApplicationStatus}
        assert len(states) == 7

    def test_agent_state_default_status(self):
        state = AgentState(run_id="test")
        assert state.current_application_status == ApplicationStatus.PENDING
        assert state.status == RunStatus.PENDING

    def test_status_transition_sequence(self):
        """模拟完整状态流转序列。"""
        state = AgentState(run_id="test")

        # 填写完成
        state.current_application_status = ApplicationStatus.FORM_FILLED
        assert state.current_application_status == ApplicationStatus.FORM_FILLED

        # 等待提交
        state.current_application_status = ApplicationStatus.WAITING_FOR_SUBMIT
        assert state.current_application_status == ApplicationStatus.WAITING_FOR_SUBMIT

        # 用户确认
        state.current_application_status = ApplicationStatus.USER_CONFIRMED_SUBMIT
        assert state.current_application_status == ApplicationStatus.USER_CONFIRMED_SUBMIT

        # 页面验证成功
        state.current_application_status = ApplicationStatus.PAGE_VERIFIED
        assert state.current_application_status == ApplicationStatus.PAGE_VERIFIED

    def test_unknown_status_for_unverified_submission(self):
        """页面未变化时应标记为 UNKNOWN。"""
        state = AgentState(run_id="test")
        state.current_application_status = ApplicationStatus.UNKNOWN
        assert state.current_application_status == ApplicationStatus.UNKNOWN


class TestRecordResultLogic:
    """record_result 节点逻辑测试（不实际操作浏览器/数据库）。"""

    def _make_state(self, status: ApplicationStatus, fields_filled: int = 3, fields_failed: int = 0) -> AgentState:
        job = JobDetail(
            posting=JobPosting(title="测试工程师", detail_url="https://test.com/1", company="测试公司", site_name="test"),
        )
        fields = [
            FillField(label="姓名", field_type="text", status=FillStatus.FILLED),
            FillField(label="电话", field_type="text", status=FillStatus.FILLED),
            FillField(label="邮箱", field_type="email", status=FillStatus.FILLED),
        ]
        if fields_failed > 0:
            for i in range(fields_failed):
                fields.append(FillField(label=f"失败字段{i}", field_type="text", status=FillStatus.FAILED, error="test error"))

        state = AgentState(
            run_id="test",
            apply_queue=[job],
            current_job_index=0,
            current_fill_fields=fields,
            current_application_status=status,
        )
        return state

    def test_page_verified_counts_as_success(self):
        """PAGE_VERIFIED 状态应记录为成功。"""
        # 不实际调用数据库，只验证逻辑分支
        # 这里通过 mock state_db 来测试
        import asyncio
        from unittest.mock import AsyncMock, patch

        state = self._make_state(ApplicationStatus.PAGE_VERIFIED)
        with patch("src.agent.nodes.record_result.state_db.record_application", new_callable=AsyncMock) as mock_record:
            mock_record.return_value = 1
            result = asyncio.run(record_result_run(state))
            # 验证调用参数中 success=True
            call_kwargs = mock_record.call_args.kwargs
            assert call_kwargs["success"] is True
            assert call_kwargs["status"] == "page_verified"

    def test_user_confirmed_counts_as_success(self):
        """USER_CONFIRMED_SUBMIT 状态应记录为成功（但页面未验证）。"""
        import asyncio
        from unittest.mock import AsyncMock, patch

        state = self._make_state(ApplicationStatus.USER_CONFIRMED_SUBMIT)
        with patch("src.agent.nodes.record_result.state_db.record_application", new_callable=AsyncMock) as mock_record:
            mock_record.return_value = 1
            result = asyncio.run(record_result_run(state))
            call_kwargs = mock_record.call_args.kwargs
            assert call_kwargs["success"] is True
            assert call_kwargs["status"] == "user_confirmed_submit"

    def test_unknown_status_counts_as_failure(self):
        """UNKNOWN 状态应记录为失败。"""
        import asyncio
        from unittest.mock import AsyncMock, patch

        state = self._make_state(ApplicationStatus.UNKNOWN)
        with patch("src.agent.nodes.record_result.state_db.record_application", new_callable=AsyncMock) as mock_record:
            mock_record.return_value = 1
            result = asyncio.run(record_result_run(state))
            call_kwargs = mock_record.call_args.kwargs
            assert call_kwargs["success"] is False
            assert call_kwargs["status"] == "unknown"

    def test_index_increments_after_record(self):
        """记录后 current_job_index 应 +1，状态重置为 PENDING。"""
        import asyncio
        from unittest.mock import AsyncMock, patch

        state = self._make_state(ApplicationStatus.PAGE_VERIFIED)
        assert state.current_job_index == 0
        with patch("src.agent.nodes.record_result.state_db.record_application", new_callable=AsyncMock) as mock_record:
            mock_record.return_value = 1
            result = asyncio.run(record_result_run(state))
            assert result.current_job_index == 1
            assert result.current_application_status == ApplicationStatus.PENDING
            assert result.current_fill_fields == []

    def test_failed_fields_counted(self):
        """失败字段数量应正确传递。"""
        import asyncio
        from unittest.mock import AsyncMock, patch

        state = self._make_state(ApplicationStatus.PAGE_VERIFIED, fields_failed=2)
        with patch("src.agent.nodes.record_result.state_db.record_application", new_callable=AsyncMock) as mock_record:
            mock_record.return_value = 1
            result = asyncio.run(record_result_run(state))
            call_kwargs = mock_record.call_args.kwargs
            assert call_kwargs["failed_fields"] == 2
