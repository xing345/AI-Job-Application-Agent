"""LLM 客户端单元测试。

覆盖：错误分类（可重试/不可重试）、结构化输出解析、Pydantic 校验、
额外字段丢弃、并发限制、LLMOutputError。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict, Field

from src.llm.client import (
    LLMOutputError,
    _coerce_data,
    _is_retryable_error,
    chat_structured,
)


# ============================================================
# 测试用模型
# ============================================================

class SimpleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    score: int = Field(ge=0, le=100)
    tags: list[str] = []


# ============================================================
# 错误分类测试
# ============================================================

class TestErrorClassification:
    def test_auth_error_not_retryable(self):
        """401 认证错误不可重试。"""
        from openai import AuthenticationError
        e = AuthenticationError(message="invalid api key", response=MagicMock(status_code=401), body={"message": "invalid api key"})
        assert _is_retryable_error(e) is False

    def test_permission_denied_not_retryable(self):
        """403 禁止错误不可重试。"""
        from openai import PermissionDeniedError
        e = PermissionDeniedError(message="forbidden", response=MagicMock(status_code=403), body={"message": "forbidden"})
        assert _is_retryable_error(e) is False

    def test_bad_request_not_retryable(self):
        """400 无效请求不可重试。"""
        from openai import BadRequestError
        e = BadRequestError(message="invalid request", response=MagicMock(status_code=400), body={"message": "invalid request"})
        assert _is_retryable_error(e) is False

    def test_rate_limit_retryable(self):
        """429 限流可重试。"""
        from openai import RateLimitError
        e = RateLimitError(message="rate limited", response=MagicMock(status_code=429), body={"message": "rate limited"})
        assert _is_retryable_error(e) is True

    def test_timeout_retryable(self):
        """超时可重试。"""
        from openai import APITimeoutError
        e = APITimeoutError(request=MagicMock())
        assert _is_retryable_error(e) is True

    def test_server_error_retryable(self):
        """5xx 服务端错误可重试。"""
        from openai import APIStatusError
        e = APIStatusError(message="internal error", response=MagicMock(status_code=500), body={"message": "internal error"})
        assert _is_retryable_error(e) is True

    def test_gateway_timeout_retryable(self):
        """502/503/504 可重试。"""
        from openai import APIStatusError
        for code in (502, 503, 504):
            e = APIStatusError(message="error", response=MagicMock(status_code=code), body={"message": "error"})
            assert _is_retryable_error(e) is True

    def test_not_found_not_retryable(self):
        """404 模型不存在不可重试。"""
        from openai import NotFoundError
        e = NotFoundError(message="model not found", response=MagicMock(status_code=404), body={"message": "model not found"})
        assert _is_retryable_error(e) is False

    def test_generic_exception_not_retryable(self):
        """普通异常不可重试。"""
        assert _is_retryable_error(ValueError("test")) is False


# ============================================================
# 数据清洗测试
# ============================================================

class TestCoerceData:
    def test_drops_extra_fields(self):
        """额外字段应被丢弃（适配 extra="forbid"）。"""
        data = {"name": "test", "score": 90, "unknown": "bad", "another": 123}
        result = _coerce_data(data, SimpleResult)
        assert "name" in result
        assert "score" in result
        assert "unknown" not in result
        assert "another" not in result

    def test_coerce_string_to_int(self):
        """字符串数字应转为 int。"""
        data = {"name": "test", "score": "90"}
        result = _coerce_data(data, SimpleResult)
        assert result["score"] == 90

    def test_coerce_invalid_int_to_zero(self):
        """无法转换的 int 转为 0。"""
        data = {"name": "test", "score": "not_a_number"}
        result = _coerce_data(data, SimpleResult)
        assert result["score"] == 0

    def test_coerce_list_from_string(self):
        """逗号分隔字符串应转为列表。"""
        data = {"name": "test", "score": 90, "tags": "a,b,c"}
        result = _coerce_data(data, SimpleResult)
        assert result["tags"] == ["a", "b", "c"]

    def test_none_value_preserved(self):
        """None 值应保留。"""
        data = {"name": "test", "score": 90, "tags": None}
        result = _coerce_data(data, SimpleResult)
        assert result["tags"] is None


# ============================================================
# chat_structured 测试（mock LLM 调用）
# ============================================================

def _make_mock_response(content: str):
    """构造模拟的 LLM 响应。"""
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
    return mock_resp


class TestChatStructured:
    @pytest.mark.asyncio
    async def test_valid_json_parsed(self):
        """有效 JSON 应正确解析为 Pydantic 模型。"""
        content = '{"name": "测试岗位", "score": 85, "tags": ["AI", "后端"]}'
        with patch("src.llm.client.chat", new_callable=AsyncMock, return_value=content):
            result = await chat_structured([], SimpleResult, run_id="test")
            assert result.name == "测试岗位"
            assert result.score == 85
            assert result.tags == ["AI", "后端"]

    @pytest.mark.asyncio
    async def test_markdown_code_block_stripped(self):
        """markdown 代码块应被清理。"""
        content = '```json\n{"name": "test", "score": 90}\n```'
        with patch("src.llm.client.chat", new_callable=AsyncMock, return_value=content):
            result = await chat_structured([], SimpleResult)
            assert result.name == "test"
            assert result.score == 90

    @pytest.mark.asyncio
    async def test_json_extracted_from_text(self):
        """JSON 包裹在其他文本中时应提取。"""
        content = '思考过程... \n{"name": "test", "score": 80}\n更多文本'
        with patch("src.llm.client.chat", new_callable=AsyncMock, return_value=content):
            result = await chat_structured([], SimpleResult)
            assert result.name == "test"

    @pytest.mark.asyncio
    async def test_invalid_json_raises_llm_output_error(self):
        """无法解析的 JSON 应抛出 LLMOutputError。"""
        content = "这不是 JSON"
        with patch("src.llm.client.chat", new_callable=AsyncMock, return_value=content):
            with pytest.raises(LLMOutputError) as exc_info:
                await chat_structured([], SimpleResult)
            assert "无法解析为 JSON" in str(exc_info.value)
            assert exc_info.value.raw_text == content

    @pytest.mark.asyncio
    async def test_validation_failure_raises_llm_output_error(self):
        """Pydantic 验证失败应抛出 LLMOutputError（不使用 model_construct）。"""
        # score 超出范围
        content = '{"name": "test", "score": 999}'
        with patch("src.llm.client.chat", new_callable=AsyncMock, return_value=content):
            with pytest.raises(LLMOutputError) as exc_info:
                await chat_structured([], SimpleResult)
            assert "Pydantic 验证失败" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_required_field_raises(self):
        """缺少必填字段应抛出 LLMOutputError。"""
        content = '{"score": 80}'  # 缺少 name
        with patch("src.llm.client.chat", new_callable=AsyncMock, return_value=content):
            with pytest.raises(LLMOutputError):
                await chat_structured([], SimpleResult)

    @pytest.mark.asyncio
    async def test_extra_fields_in_llm_output_dropped(self):
        """LLM 输出的额外字段应被丢弃，不导致验证失败。"""
        content = '{"name": "test", "score": 85, "extra1": "a", "extra2": 123}'
        with patch("src.llm.client.chat", new_callable=AsyncMock, return_value=content):
            result = await chat_structured([], SimpleResult)
            assert result.name == "test"
            assert result.score == 85
            # 额外字段不应存在
            assert not hasattr(result, "extra1")
            assert not hasattr(result, "extra2")


# ============================================================
# 并发限制测试
# ============================================================

class TestConcurrencyLimit:
    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_calls(self):
        """Semaphore 应限制并发调用数量。"""
        from src.llm.client import _get_semaphore

        sem = _get_semaphore()
        # 默认并发上限为 5
        assert sem._value <= 5

        # 模拟并发调用
        active = 0
        max_active = 0

        async def mock_call():
            nonlocal active, max_active
            async with sem:
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*[mock_call() for _ in range(10)])
        assert max_active <= 5
