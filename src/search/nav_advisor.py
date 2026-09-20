"""
NavAdvisor —— 受约束的「下一步导航」LLM 裁决器

背景（问题5）：找岗目前的导航是纯确定性规则（文字打分 + 固定选择器 + 正则），
规则在「类别导航文字里含技术二字」这类场景会选错——把已经在职位列表页的
Agent 带去「技术人才项目」这类宣传页，于是整站抽到 0 个岗位。

设计原则（刻意不做成「LLM 全程自主导航」）：
1. **LLM 不产生动作、只做选择题**：候选链接由确定性代码先算好（同站、短文本、
   非详情页、非提交按钮），LLM 只能在这几个候选里选一个，或者回答「留在当前页」。
   它永远拿不到「点任意元素」的能力，因此不可能点到投递/申请按钮。
2. **只在规则低置信度时调用**：调用方（BrowserJobFinder._find_category_link）
   只在「候选多个/分数接近/当前页看起来已经是列表页」时才问 LLM；
   规则能明确判定的常见情况（例如直达 B 站职位列表页）一次 LLM 都不调。
3. **硬预算 + 超时 + 失败降级**：每次搜索最多 `max_calls_per_search` 次调用，
   超时/报错/输出非法一律返回 passthrough，由确定性规则继续。
4. **可一键关闭**：config.search.nav_advisor.enabled = false 即回到纯规则。

为什么不把翻页、点卡片、抓 JD 也交给 LLM：
- 那些步骤的正确性可以由 DOM/XHR 客观证据直接验证（有没有职位 JSON、URL 像不像
  详情页），确定性代码 0 成本、100% 可复现、出错可精确定位；
- LLM 参与的每一步都要付出 token 成本与不确定性，而收益只有「规则真的判不准」
  的那一小撮场景。所以取舍是：**规则负责 90% 的稳定路径，LLM 只兜底 10% 的模糊决策**。
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Dict, List, Optional

from loguru import logger

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# LLM 看到的候选里绝不允许出现的文本（红线1：绝不自动点提交/投递）
_FORBIDDEN_TEXT = (
    "投递", "申请", "提交", "立即沟通", "立即联系", "发送简历", "登录", "注册",
    "apply", "submit", "send resume", "sign in", "log in", "register",
)


class NavAdvisorConfig:
    """导航裁决器配置（未显式传入时从 config.json 的 llm / search.nav_advisor 段读取）"""

    def __init__(
        self,
        enabled: bool = False,
        api_key: str = None,
        base_url: str = None,
        model: str = None,
        max_calls_per_search: int = 4,
        timeout_s: int = 25,
        max_candidates: int = 6,
    ):
        llm_cfg: Dict = {}
        try:
            config_path = os.path.join(_PROJECT_ROOT, "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    llm_cfg = json.load(f).get("llm", {}) or {}
        except Exception:
            llm_cfg = {}

        self.enabled = bool(enabled)
        self.api_key = (
            api_key or llm_cfg.get("api_key") or os.getenv("OPENAI_API_KEY") or ""
        )
        self.base_url = (
            base_url or llm_cfg.get("base_url") or os.getenv("OPENAI_BASE_URL") or None
        )
        self.model = model or llm_cfg.get("model") or os.getenv("OPENAI_MODEL") or ""
        self.max_calls_per_search = max(0, int(max_calls_per_search))
        self.timeout_s = max(5, int(timeout_s))
        self.max_candidates = max(2, int(max_candidates))
        self._client = None

    def _get_client(self):
        """惰性创建 LLMClient（无 key 时不创建，enabled 直接失效）"""
        if self._client is None:
            from src.utils.llm_client import LLMClient
            self._client = LLMClient(
                model=self.model or None,
                api_key=self.api_key or None,
                base_url=self.base_url,
                temperature=0.0,
                max_tokens=300,
                timeout=self.timeout_s,
            )
        return self._client

    @property
    def usable(self) -> bool:
        """既开关打开、又有可用的 LLM 配置，才真正启用"""
        return bool(self.enabled and (self.api_key or self.model))


_SYSTEM_PROMPT = (
    "你是招聘网站导航助手。你只能在给定候选里做选择，不能编造链接、不能提出新动作。"
    "你的唯一目标：帮助程序进入「包含目标方向职位的职位列表/类别页」，"
    "绝不能进入职位详情页、宣传介绍页、人才项目页、登录页，也绝不能选择任何"
    "投递/申请/提交类链接。只输出 JSON。"
)


class NavAdvisor:
    """把「要不要顺着某个导航链接跳走」这一处模糊决策交给 LLM，其余仍由规则负责"""

    def __init__(self, config: NavAdvisorConfig = None):
        self.config = config or NavAdvisorConfig()
        self.calls = 0

    # ------------------------------------------------------------------ #
    @property
    def enabled(self) -> bool:
        return bool(self.config.usable and self.calls < self.config.max_calls_per_search)

    def reset(self) -> None:
        """新一轮搜索开始前重置调用计数（预算按「每轮搜索」计）"""
        self.calls = 0

    # ------------------------------------------------------------------ #
    @staticmethod
    def _safe_candidates(candidates: List[Dict]) -> List[Dict]:
        """过滤掉提交/申请/登录类候选——这些永远不该出现在 LLM 的选项里"""
        out: List[Dict] = []
        for c in candidates or []:
            text = str(c.get("text") or "")
            low = text.lower()
            if any(w in low for w in _FORBIDDEN_TEXT):
                continue
            href = str(c.get("href") or "")
            if not href.startswith("http"):
                continue
            out.append({"text": text[:30], "href": href})
        return out

    async def choose(
        self,
        *,
        site: str,
        page_url: str,
        role: str,
        recruit_type: str,
        page_job_links: int,
        candidates: List[Dict],
        deterministic_pick: Dict = None,
    ) -> Optional[int]:
        """
        在候选里选一个（返回下标），或返回 -1 表示「留在当前页」。

        Returns:
            下标 / -1（留在此页）/ None（未启用、超预算或调用失败 —— 由确定性规则决定）
        """
        if not self.enabled:
            return None

        safe = self._safe_candidates(candidates)[: self.config.max_candidates]
        if not safe:
            return None

        lines = [
            f"站点: {site}",
            f"当前页: {page_url}",
            f"目标方向: {role}（招聘类型: {recruit_type}）",
            f"当前页已识别到的职位详情链接数: {page_job_links}",
        ]
        if deterministic_pick:
            lines.append(
                f"规则默认选择: {deterministic_pick.get('text')} -> "
                f"{deterministic_pick.get('href')}"
            )
        lines.append("候选链接（只能从中选，或选 stay）:")
        for i, c in enumerate(safe):
            lines.append(f"  [{i}] 文本={c['text']!r} 链接={c['href']}")

        lines.append(
            "\n判断规则：\n"
            "1) 若当前页已经是职位列表（上面链接数 > 0，或 URL 就是列表/搜索页），"
            "必须选 stay；跳去别处只会丢失已渲染的岗位。\n"
            "2) 只有当候选明确是「职位类别/方向栏目」页、且当前页看不到职位时才选它。\n"
            "3) 宣传页、人才项目、招聘流程介绍、公司介绍、登录/注册页一律不选。\n"
            "4) 拿不准就选 stay。\n\n"
            '只输出 JSON: {"action": "stay" 或 "click", "index": 候选下标(整数, stay 时给 -1),'
            ' "reason": "一句话理由"}'
        )
        prompt = "\n".join(lines)

        self.calls += 1
        try:
            client = self.config._get_client()
            data = await asyncio.wait_for(
                client.generate_response(
                    prompt, system_prompt=_SYSTEM_PROMPT, json_output=True
                ),
                timeout=self.config.timeout_s,
            )
        except Exception as e:  # 超时/网络/解析失败一律降级
            logger.warning(f"导航裁决 LLM 调用失败（按规则继续）: {e}")
            return None

        if not isinstance(data, dict):
            logger.warning(f"导航裁决返回非 JSON，按规则继续: {data!r}")
            return None

        action = str(data.get("action") or "").strip().lower()
        try:
            index = int(data.get("index", -1))
        except (TypeError, ValueError):
            index = -1
        reason = str(data.get("reason") or "")[:80]

        if action == "stay":
            logger.info(f"导航裁决(LLM): 留在当前页 —— {reason}")
            return -1
        if action == "click" and 0 <= index < len(safe):
            logger.info(
                f"导航裁决(LLM): 选择候选[{index}] {safe[index]['text']!r} —— {reason}"
            )
            return index
        logger.warning(f"导航裁决输出越界/非法，按规则继续: {data!r}")
        return None
