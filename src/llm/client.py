"""统一 LLM 客户端。

OpenAI 兼容接口，异步调用，支持 Pydantic structured output，
指数退避重试，超时控制，并发上限，日志记录。

response_format 自动降级：json_schema → json_object → 无（靠 prompt 约束）。
兼容 DeepSeek、智谱等不支持 json_schema 的接口。

错误处理策略：
- 认证错误(401/403)、无效请求(400)、模型拒绝 → 不重试，直接抛出
- 超时、限流(429)、5xx、网络错误 → 有限重试+指数退避
- LLM 输出无法解析为 JSON / Pydantic 验证失败 → 不重试，抛出明确异常
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Type, TypeVar

from dotenv import load_dotenv
from openai import APIError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

load_dotenv()

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# 全局单例
_client: Optional[AsyncOpenAI] = None
_model: str = ""
_semaphore: Optional[asyncio.Semaphore] = None

# 默认并发上限
DEFAULT_MAX_CONCURRENT = 5
# 默认超时（秒）
DEFAULT_TIMEOUT = 30.0
# 默认重试次数
DEFAULT_MAX_RETRIES = 3


def _get_client() -> AsyncOpenAI:
    global _client, _model
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        _model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY 未设置，请在 .env 中配置")
        _client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=DEFAULT_TIMEOUT)
    return _client


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        max_concurrent = int(os.getenv("LLM_MAX_CONCURRENT", str(DEFAULT_MAX_CONCURRENT)))
        _semaphore = asyncio.Semaphore(max_concurrent)
    return _semaphore


def get_model_name() -> str:
    _get_client()
    return _model


# ============================================================
# 错误分类
# ============================================================

def _is_retryable_error(e: Exception) -> bool:
    """判断错误是否可重试。

    不可重试：认证错误、无效请求、模型拒绝、LLM 输出解析失败
    可重试：超时、限流、5xx、网络错误
    """
    # 限流 → 可重试（等退避后）
    if isinstance(e, RateLimitError):
        return True
    # 超时 → 可重试
    if isinstance(e, APITimeoutError):
        return True
    # APIStatusError: 根据状态码判断
    if isinstance(e, APIStatusError):
        status = getattr(e, "status_code", 0)
        # 401 认证失败、403 禁止、400 无效请求 → 不可重试
        if status in (400, 401, 403):
            return False
        # 404 模型不存在等 → 不可重试
        if status == 404:
            return False
        # 429 限流 → 可重试
        if status == 429:
            return True
        # 5xx 服务端错误 → 可重试
        if status >= 500:
            return True
        # 其他 4xx → 不可重试
        return False
    # 通用 APIError（网络错误等） → 可重试
    if isinstance(e, APIError):
        return True
    # 其他异常默认不可重试
    return False


def _is_response_format_error(e: Exception) -> bool:
    """判断错误是否由 response_format 不支持导致。"""
    msg = str(e).lower()
    return any(kw in msg for kw in [
        "response_format",
        "json_schema",
        "unavailable now",
        "not supported",
    ])


# ============================================================
# response_format 构建
# ============================================================

def _build_response_format(mode: str, model_cls: Type[BaseModel]) -> Optional[Dict[str, Any]]:
    """根据模式构建 response_format 参数。"""
    if mode == "json_schema":
        schema = model_cls.model_json_schema()
        return {
            "type": "json_schema",
            "json_schema": {
                "name": model_cls.__name__,
                "schema": schema,
                "strict": False,
            },
        }
    if mode == "json_object":
        return {"type": "json_object"}
    return None


# ============================================================
# 核心调用
# ============================================================

async def chat(
    messages: List[Dict[str, str]],
    response_format: Optional[Type[T]] = None,
    temperature: float = 0.1,
    max_retries: int = DEFAULT_MAX_RETRIES,
    run_id: str = "",
) -> str:
    """统一 LLM 调用入口。

    response_format 自动降级：json_schema → json_object → 无。
    认证错误和无效请求不重试；超时、限流、5xx 有限重试。
    """
    client = _get_client()
    model = _model
    semaphore = _get_semaphore()

    # response_format 降级链
    rf_modes = ["json_schema", "json_object", "none"] if response_format else ["none"]
    rf_index = 0

    last_error: Optional[Exception] = None
    t0 = time.monotonic()

    async with semaphore:
        for attempt in range(max_retries):
            kwargs: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }

            mode = rf_modes[rf_index]
            if response_format and mode != "none":
                rf = _build_response_format(mode, response_format)
                if rf:
                    kwargs["response_format"] = rf

            try:
                resp = await client.chat.completions.create(**kwargs)
                content = resp.choices[0].message.content or ""
                usage = resp.usage
                elapsed = time.monotonic() - t0
                logger.info(
                    "LLM ok: model=%s rf=%s attempt=%d prompt_tokens=%s completion_tokens=%s elapsed=%.1fs run_id=%s",
                    model, mode, attempt + 1,
                    usage.prompt_tokens if usage else "?",
                    usage.completion_tokens if usage else "?",
                    elapsed, run_id,
                )
                return content

            except Exception as e:
                last_error = e

                # response_format 不支持 → 立即降级，不计数重试
                if response_format and _is_response_format_error(e) and rf_index < len(rf_modes) - 1:
                    rf_index += 1
                    new_mode = rf_modes[rf_index]
                    logger.info("response_format 降级: %s -> %s run_id=%s", mode, new_mode, run_id)
                    continue

                # 不可重试错误 → 立即抛出
                if not _is_retryable_error(e):
                    logger.error(
                        "LLM non-retryable error: model=%s rf=%s attempt=%d error=%s run_id=%s",
                        model, mode, attempt + 1, e, run_id,
                    )
                    raise

                # 可重试错误 → 指数退避
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "LLM retryable error: model=%s rf=%s attempt=%d/%d error=%s retry_in=%ds run_id=%s",
                        model, mode, attempt + 1, max_retries, e, wait, run_id,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "LLM max retries reached: model=%s rf=%s error=%s run_id=%s",
                        model, mode, e, run_id,
                    )

    raise RuntimeError(f"LLM 调用失败（已重试 {max_retries} 次）: {last_error}")


# ============================================================
# 数据清洗（丢弃额外字段，适配 extra="forbid"）
# ============================================================

def _coerce_value(value: Any, target_type: Any) -> Any:
    """将值强制转换为目标类型，处理 LLM 输出不规范的情况。"""
    if value is None:
        return None

    # 目标是字符串，但值是列表/字典
    if target_type is str or (hasattr(target_type, "__origin__") and target_type.__origin__ is str):
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    # 目标是列表，但值是字符串
    if hasattr(target_type, "__origin__") and target_type.__origin__ is list:
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(",") if p.strip()]
            return parts if parts else []
        if not isinstance(value, list):
            return [value]

    # 目标是整数
    if target_type is int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0

    # 目标是布尔
    if target_type is bool:
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "y")
        return bool(value)

    return value


def _coerce_data(data: Any, model_cls: Type[BaseModel]) -> Any:
    """递归清洗数据，使其符合 Pydantic 模型。

    重要：丢弃模型中未定义的额外字段（适配 extra="forbid"）。
    """
    if not isinstance(data, dict):
        return data

    fields = model_cls.model_fields
    result: Dict[str, Any] = {}

    for key, value in data.items():
        # 丢弃额外字段
        if key not in fields:
            continue

        field_info = fields[key]
        annotation = field_info.annotation

        # 处理 Optional[X] / X | None
        origin = getattr(annotation, "__origin__", None)
        if origin is Optional or (hasattr(annotation, "__args__") and type(None) in getattr(annotation, "__args__", [])):
            args = [a for a in annotation.__args__ if a is not type(None)]
            if args:
                annotation = args[0]
                origin = getattr(annotation, "__origin__", None)

        # 处理嵌套模型
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            if isinstance(value, list):
                item_origin = getattr(field_info.annotation, "__origin__", None)
                if item_origin is list:
                    args = getattr(field_info.annotation, "__args__", [])
                    if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                        result[key] = [_coerce_data(item, args[0]) for item in value if isinstance(item, dict)]
                        continue
            if isinstance(value, dict):
                result[key] = _coerce_data(value, annotation)
                continue

        # 处理 List[Model]
        if origin is list:
            args = getattr(annotation, "__args__", [])
            if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                if isinstance(value, list):
                    result[key] = [_coerce_data(item, args[0]) for item in value if isinstance(item, dict)]
                elif isinstance(value, dict):
                    result[key] = [_coerce_data(value, args[0])]
                else:
                    result[key] = []
                continue

        # 基本类型 coerce
        result[key] = _coerce_value(value, annotation)

    return result


# ============================================================
# 结构化输出
# ============================================================

class LLMOutputError(RuntimeError):
    """LLM 输出无法解析或验证失败时抛出。"""

    def __init__(self, message: str, raw_text: str = ""):
        super().__init__(message)
        self.raw_text = raw_text


async def chat_structured(
    messages: List[Dict[str, str]],
    output_type: Type[T],
    temperature: float = 0.1,
    run_id: str = "",
) -> T:
    """调用 LLM 并解析为指定 Pydantic 模型。

    自动降级 response_format，数据清洗后验证。
    验证失败时抛出 LLMOutputError，不使用 model_construct 绕过验证。
    """
    raw = await chat(messages, response_format=output_type, temperature=temperature, run_id=run_id)

    # 清理 markdown 代码块
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # 解析 JSON
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                raise LLMOutputError(
                    f"LLM 返回无法解析为 JSON（提取片段也失败）: {text[:200]}",
                    raw_text=raw,
                )
        else:
            raise LLMOutputError(
                f"LLM 返回无法解析为 JSON: {text[:200]}",
                raw_text=raw,
            )

    # 数据清洗（丢弃额外字段）+ 验证
    try:
        coerced = _coerce_data(data, output_type)
        return output_type.model_validate(coerced)
    except ValidationError as e:
        # 清洗后仍失败，尝试直接验证（可能有额外字段等小问题）
        try:
            return output_type.model_validate(data)
        except ValidationError:
            raise LLMOutputError(
                f"LLM 输出 Pydantic 验证失败（模型={output_type.__name__}）: {e}",
                raw_text=raw,
            )
