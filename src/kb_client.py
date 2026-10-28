"""个人知识库 HTTP 薄客户端。

求职 Agent 不碰知识库内部实现，只通过 localhost:8765 的 HTTP 接口检索相关片段。
知识库服务没启动时降级为空列表，不阻塞填表流程。
"""
from __future__ import annotations

import os
import logging
from typing import List

import httpx

logger = logging.getLogger(__name__)

KB_BASE = os.getenv("KB_BASE_URL", "http://localhost:8765")
_TIMEOUT = 5.0


async def search_knowledge(query: str, top_k: int = 3) -> List[str]:
    """语义检索知识库，返回相关片段文本列表。

    知识库服务未启动/超时/出错时返回空列表，降级为原来的全量 profile。
    """
    if not query.strip():
        return []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{KB_BASE}/search",
                params={"q": query, "top_k": top_k},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            texts = [r.get("text", "") for r in results if r.get("text")]
            if texts:
                logger.info("KB hit %d fragments for query: %s", len(texts), query[:60])
            return texts
    except Exception as e:
        logger.debug("KB service unavailable, degraded to empty: %s", str(e)[:100])
        return []


async def kb_health() -> bool:
    """检查知识库服务是否可用"""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{KB_BASE}/health")
            return resp.status_code == 200
    except Exception:
        return False
