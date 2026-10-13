"""表单填写操作单元测试。

覆盖：法律/隐私字段检测、FillStatus 枚举、_is_legal_field 函数。
"""
from __future__ import annotations

import pytest

from src.agent.nodes.fill_application import _is_legal_field
from src.models.match import FillField, FillStatus


class TestFillStatus:
    def test_enum_values(self):
        assert FillStatus.PENDING.value == "pending"
        assert FillStatus.FILLED.value == "filled"
        assert FillStatus.FAILED.value == "failed"
        assert FillStatus.SKIPPED.value == "skipped"
        assert FillStatus.NEEDS_USER_INPUT.value == "needs_user_input"

    def test_default_status_pending(self):
        f = FillField(label="测试", field_type="text")
        assert f.status == FillStatus.PENDING

    def test_needs_user_input_status(self):
        f = FillField(label="是否同意条款", field_type="radio", status=FillStatus.NEEDS_USER_INPUT)
        assert f.status == FillStatus.NEEDS_USER_INPUT


class TestLegalFieldDetection:
    """法律/隐私字段检测测试。"""

    def test_agreement_field_detected(self):
        assert _is_legal_field("是否同意用户协议") is True
        assert _is_legal_field("同意隐私政策") is True
        assert _is_legal_field("我已阅读并同意条款") is True

    def test_authorization_field_detected(self):
        assert _is_legal_field("授权背景调查") is True
        assert _is_legal_field("是否授权公司核实信息") is True

    def test_work_permit_field_detected(self):
        assert _is_legal_field("工作许可") is True
        assert _is_legal_field("签证类型") is True
        assert _is_legal_field("是否需要签证支持") is True

    def test_salary_expectation_detected(self):
        assert _is_legal_field("期望薪资") is True
        assert _is_legal_field("薪资期望") is True

    def test_non_compete_detected(self):
        assert _is_legal_field("是否受竞业限制") is True

    def test_authenticity_declaration_detected(self):
        assert _is_legal_field("确认信息真实性") is True
        assert _is_legal_field("承诺所填信息无误") is True

    def test_normal_field_not_detected(self):
        assert _is_legal_field("姓名") is False
        assert _is_legal_field("电话") is False
        assert _is_legal_field("邮箱") is False
        assert _is_legal_field("毕业院校") is False
        assert _is_legal_field("工作经历") is False
        assert _is_legal_field("项目经验") is False
        assert _is_legal_field("技能") is False

    def test_placeholder_used_for_detection(self):
        """placeholder 也参与检测。"""
        assert _is_legal_field("", placeholder="请选择是否同意") is True
        assert _is_legal_field("", placeholder="请输入姓名") is False

    def test_english_legal_terms(self):
        """英文法律术语也应检测。"""
        assert _is_legal_field("I agree to terms") is True
        assert _is_legal_field("Authorize background check") is True
        assert _is_legal_field("Work authorization") is True


class TestFillFieldModel:
    def test_extra_fields_rejected(self):
        with pytest.raises(Exception):
            FillField(label="test", unknown_field="bad")

    def test_options_for_select(self):
        f = FillField(label="学历", field_type="select", options=["本科", "硕士", "博士"])
        assert len(f.options) == 3

    def test_value_none_means_uncertain(self):
        """value 为 None 表示不确定，不编造。"""
        f = FillField(label="不确定字段", field_type="text", value=None)
        assert f.value is None
