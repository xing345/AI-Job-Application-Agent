"""个人知识库客户端：连接独立的 personal-kb 服务（默认 http://127.0.0.1:8765），
在填表前检索项目经历、自我评价等素材。服务未启动时自动降级（不影响主流程）。
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

_DEFAULT_BASE = "http://127.0.0.1:8765"


class PersonalKB:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 10.0):
        self.base_url = base_url or os.getenv("PERSONAL_KB_URL", _DEFAULT_BASE)
        self.timeout = timeout

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.get(f"{self.base_url}/health")
                return r.status_code == 200
        except Exception:
            return False

    async def search(self, query: str, top_k: int = 3) -> list[dict]:
        """语义检索，返回 [{text, source, score}]。"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.get(
                    f"{self.base_url}/search",
                    params={"q": query, "top_k": top_k},
                )
                r.raise_for_status()
                return r.json().get("results", [])
        except Exception:
            return []

    async def gather_material(self, topics: list[str], top_k: int = 3) -> str:
        """对多个主题检索，去重后拼成给 LLM 的素材文本。"""
        if not await self.health():
            return ""
        seen_sources: set[str] = set()
        blocks: list[str] = []
        for topic in topics:
            for item in await self.search(topic, top_k=top_k):
                src = item.get("source", "")
                text = item.get("text", "").strip()
                key = src + text[:80]
                if not text or key in seen_sources:
                    continue
                seen_sources.add(key)
                blocks.append(f"【{src}】\n{text}")
        return "\n\n".join(blocks)
