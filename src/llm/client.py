"""统一 LLM 客户端。

OpenAI 兼容接口，异步调用，支持 Pydantic structured output，
指数退避重试，超时控制，日志记录。

response_format 自动降级：json_schema → json_object → 无（靠 prompt 约束）。
兼容 DeepSeek、智谱等不支持 json_schema 的接口。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, Type, TypeVar

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

load_dotenv()

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# 全局单例
_client: Optional[AsyncOpenAI] = None
_model: str = ""


def _get_client() -> AsyncOpenAI:
    global _client, _model
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        _model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY 未设置，请在 .env 中配置")
        _client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=30.0)
    return _client


def get_model_name() -> str:
    _get_client()
    return _model


def _is_response_format_error(e: Exception) -> bool:
    """判断错误是否由 response_format 不支持导致。"""
    msg = str(e).lower()
    return any(kw in msg for kw in [
        "response_format",
        "json_schema",
        "unavailable now",
        "invalid_request_error",
        "not supported",
    ])


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


async def chat(
    messages: List[Dict[str, str]],
    response_format: Optional[Type[T]] = None,
    temperature: float = 0.1,
    max_retries: int = 3,
) -> str:
    """统一 LLM 调用入口。

    response_format 自动降级：json_schema → json_object → 无。
    """
    client = _get_client()
    model = _model

    # response_format 降级链
    rf_modes = ["json_schema", "json_object", "none"] if response_format else ["none"]
    rf_index = 0

    last_error: Optional[Exception] = None

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
            logger.info(
                "LLM call ok: model=%s, rf_mode=%s, prompt_tokens=%s, completion_tokens=%s",
                model, mode,
                usage.prompt_tokens if usage else "?",
                usage.completion_tokens if usage else "?",
            )
            return content
        except Exception as e:
            last_error = e
            # 如果是 response_format 不支持，立即降级，不等退避
            if response_format and _is_response_format_error(e) and rf_index < len(rf_modes) - 1:
                rf_index += 1
                new_mode = rf_modes[rf_index]
                logger.info("response_format 降级: %s -> %s", mode, new_mode)
                continue

            wait = 2 ** attempt
            logger.warning("LLM call attempt %d failed (mode=%s): %s; retrying in %ds",
                           attempt + 1, mode, e, wait)
            if attempt < max_retries - 1:
                await asyncio.sleep(wait)

    raise RuntimeError(f"LLM 调用失败（已重试 {max_retries} 次）: {last_error}")


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
            # 尝试按逗号分割
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
    """递归清洗数据，使其符合 Pydantic 模型。"""
    if not isinstance(data, dict):
        return data

    fields = model_cls.model_fields
    result: Dict[str, Any] = {}

    for key, value in data.items():
        if key not in fields:
            result[key] = value
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
                # 列表中的每个元素都是嵌套模型
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


async def chat_structured(
    messages: List[Dict[str, str]],
    output_type: Type[T],
    temperature: float = 0.1,
) -> T:
    """调用 LLM 并解析为指定 Pydantic 模型。

    自动降级 response_format，数据清洗后验证。
    """
    raw = await chat(messages, response_format=output_type, temperature=temperature)

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
            data = json.loads(text[start : end + 1])
        else:
            raise RuntimeError(f"LLM 返回无法解析为 JSON: {text[:200]}")

    # 数据清洗 + 验证
    try:
        coerced = _coerce_data(data, output_type)
        return output_type.model_validate(coerced)
    except ValidationError:
        # 清洗后仍失败，尝试直接验证（可能有额外字段等小问题）
        try:
            return output_type.model_validate(data)
        except ValidationError as e:
            logger.warning("Pydantic 验证失败，返回原始数据的部分字段: %s", e)
            # 最后手段：用默认值填充，保留能解析的字段
            return output_type.model_construct(**{k: v for k, v in data.items() if k in output_type.model_fields})
