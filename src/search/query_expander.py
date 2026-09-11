"""
岗位名模糊扩展与统一分词（确定性规则，不依赖 LLM）

搜索链路上「岗位名必须完整出现」的精确匹配，是搜不到岗位的主因之一：
目标岗位写「前端工程师」，标题写「Web前端开发」就会被直接丢掉。

这里做两件事：
1. expand_role_variants() —— 把目标岗位按「词根 × 后缀」+「技术栈派生」扩展成一组近义变体
2. role_tokens()          —— 统一的 token 提取（英文技术栈词 + 通用岗位词 + 中文二元组）

JobFinder / BrowserJobFinder / SearchPipeline 共用本模块，
避免各处再写一份分词实现导致行为漂移。
"""

import re
from typing import Iterable, List, Optional

# 岗位词根：限定职能方向。命中则按后缀组合出同义岗位名
ROLE_ROOTS = [
    "前端", "后端", "服务端", "全栈", "客户端", "移动端", "Android", "iOS",
    "算法", "推荐", "测试", "运维", "安全", "网络", "嵌入式", "硬件",
    "大数据", "数据开发", "数据分析", "数据科学", "机器学习", "深度学习",
    "人工智能", "AI", "产品", "运营", "设计", "UI", "交互", "视觉",
]

# 岗位后缀：同一职能的不同叫法
ROLE_SUFFIXES = [
    "工程师", "开发工程师", "开发", "架构师", "专家", "经理", "主管", "实习生",
]

# 职位名里常见的通用词（用于中文岗位名切分与「像不像职位」的判定）
ROLE_GENERIC_TOKENS = [
    "工程师", "开发", "设计师", "产品", "运营", "经理", "架构师", "分析师",
    "研究员", "实习", "校招", "专家", "负责人", "总监", "专员", "主管", "顾问",
]

# 技术栈 -> 岗位方向派生（关键词里出现这些技术时，补出对应岗位名）
STACK_ROLE_MAP = {
    "react": ["Web前端", "React开发"],
    "vue": ["Web前端", "Vue开发"],
    "angular": ["Web前端"],
    "javascript": ["Web前端"], "typescript": ["Web前端"],
    "node": ["Node开发", "后端"], "node.js": ["Node开发", "后端"],
    "java": ["Java开发", "后端"], "spring": ["Java开发", "后端"],
    "golang": ["Go开发", "后端"], "go": ["Go开发", "后端"],
    "python": ["Python开发", "后端"],
    "django": ["Python开发"], "flask": ["Python开发"], "fastapi": ["Python开发"],
    "c++": ["C++开发"], "c#": ["C#开发"], "php": ["PHP开发"], "rust": ["Rust开发"],
    "android": ["Android开发", "移动端"], "ios": ["iOS开发", "移动端"],
    "flutter": ["移动端"], "uniapp": ["移动端"],
    "pytorch": ["算法工程师"], "tensorflow": ["算法工程师"],
    "docker": ["运维"], "kubernetes": ["运维"], "k8s": ["运维"], "devops": ["运维"],
    "hadoop": ["大数据"], "spark": ["大数据"], "flink": ["大数据"],
    "sql": ["数据分析"], "mysql": ["后端"], "redis": ["后端"],
    "figma": ["UI设计"], "sketch": ["UI设计"],
}

_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z+#.\-]{1,}")
_CJK_RE = re.compile(r"[一-鿿]")
_PUNCT_RE = re.compile(r"[\s，,、/（）()【】\[\]·|]")


def _split_role(role: str) -> tuple:
    """把岗位名拆成 (方向词, 技术栈串)"""
    text = (role or "").strip()
    for s in sorted(ROLE_SUFFIXES, key=len, reverse=True):
        if text.endswith(s):
            text = text[: -len(s)]
            break
    # 去掉后缀后，剩下的英文部分当作技术栈，中文部分当作方向
    stack = " ".join(_ASCII_TOKEN_RE.findall(text)).strip()
    direction = "".join(_CJK_RE.findall(text)).strip()
    return direction, stack


def expand_role_variants(
    role: str,
    keywords: Optional[Iterable[str]] = None,
    limit: int = 12,
) -> List[str]:
    """
    把目标岗位扩展成一组近义岗位名（确定性、可复现、零 API 成本）

    Args:
        role: 目标岗位名，如「前端工程师」
        keywords: 附加关键词（技术栈），如 ["React", "TypeScript"]
        limit: 最多返回多少个变体

    Returns:
        变体列表，原岗位名排在第一位
    """
    role = (role or "").strip()
    variants: List[str] = []

    def add(item: str):
        item = (item or "").strip()
        if item and item not in variants:
            variants.append(item)

    add(role)
    if not role:
        return variants[:limit]

    direction, stack = _split_role(role)

    # 1) 词根 × 后缀：前端工程师 -> 前端开发 / 前端架构师 / 前端专家 …
    if direction:
        for root in ROLE_ROOTS:
            if root in direction:
                for suf in ROLE_SUFFIXES:
                    add(f"{root}{suf}")
        # 方向词本身也算（前端 -> 前端）
        add(direction)

    # 2) 技术栈组合：Java + 开发 -> Java开发；前端 + React -> 前端React
    if stack:
        for suf in ROLE_SUFFIXES:
            add(f"{stack}{suf}")
        if direction:
            add(f"{direction}{stack}")
            add(f"{stack}{direction}")

    # 3) 关键词派生：React -> Web前端 / React开发
    for kw in list(keywords or [])[:12]:
        key = str(kw).strip().lower()
        for derived in STACK_ROLE_MAP.get(key, []):
            add(derived)

    return variants[:limit]


def _is_generic(tok: str) -> bool:
    """该 token 是否只是「工程师/开发」这类通用岗位词（不区分方向）"""
    return any(tok in g for g in ROLE_GENERIC_TOKENS)


def _split_tokens(role: str, keywords, variants) -> tuple:
    """
    把 token 分成 (判定用 token, 辅助 token)

    判定用(strong)：能区分岗位方向的，如 前端 / react / Web前端
    辅助用(weak)：工程师 / 工程 / 程师 这类通用词，只参与打分。
        否则搜「前端工程师」时，「后端开发工程师」会因为都含「工程师」而被判为命中。
    """
    strong: List[str] = []
    weak: List[str] = []
    seen = set()

    def add(tok: str, bucket: List[str]):
        tok = (tok or "").strip().lower()
        if len(tok) >= 2 and tok not in seen:
            seen.add(tok)
            bucket.append(tok)

    base = (role or "").strip()
    variant_list = [v for v in (variants or []) if v][:12]

    # 英文技术栈 token（基础岗位名 + 变体 + 关键词）——方向性强，一律判定用
    for m in _ASCII_TOKEN_RE.findall(base):
        add(m, strong)
    for v in variant_list:
        for m in _ASCII_TOKEN_RE.findall(v):
            add(m, strong)
    for kw in list(keywords or [])[:8]:
        for m in _ASCII_TOKEN_RE.findall(str(kw)):
            add(m, strong)

    # 中英混排变体整串（如 Web前端 / React开发）
    for v in variant_list:
        if _ASCII_TOKEN_RE.search(v) and _CJK_RE.search(v):
            add(v, strong)

    # 通用岗位词
    for word in ROLE_GENERIC_TOKENS:
        if word in base:
            add(word, weak)

    # 中文二元组（仅基础岗位名，避免变体扩张出噪声）
    zh = re.sub(r"[A-Za-z0-9+#.\-]+", " ", base)
    for i in range(len(zh) - 1):
        gram = zh[i:i + 2]
        if len(gram) == 2 and not _PUNCT_RE.search(gram):
            add(gram, weak if _is_generic(gram) else strong)

    return strong, weak


def role_tokens(
    role: str,
    keywords: Optional[Iterable[str]] = None,
    variants: Optional[Iterable[str]] = None,
) -> List[str]:
    """全部 token（判定用 + 辅助用），供锚点评分等场景使用"""
    strong, weak = _split_tokens(role, keywords, variants)
    return strong + [w for w in weak if w not in strong]


def role_match_tokens(
    role: str,
    keywords: Optional[Iterable[str]] = None,
    variants: Optional[Iterable[str]] = None,
) -> List[str]:
    """仅判定用 token：能区分岗位方向的那些，不包含通用岗位词"""
    strong, _ = _split_tokens(role, keywords, variants)
    return strong


def query_terms(target, limit: int = 2) -> List[str]:
    """
    构造搜索查询用的岗位词

    刻意挑选「差异大」的几个词做多轮查询，而不是取变体列表的前 N 个
    （前 N 个往往只是后缀替换，如 前端工程师 / 前端开发工程师，冗余且召回无增益）。
    排序：主岗位名 -> 最短变体(方向词) -> 含技术栈的变体。
    """
    role = (getattr(target, "role", "") or "").strip()
    variants = [v for v in (getattr(target, "role_variants", None) or []) if v]

    picks: List[str] = []

    def add(item: str):
        item = (item or "").strip()
        if item and item not in picks:
            picks.append(item)

    add(role)
    if variants and limit > 1:
        add(min(variants, key=len))
    if limit > 2:
        for v in variants:
            if _ASCII_TOKEN_RE.search(v) and _CJK_RE.search(v):
                add(v)
                break

    return picks[:limit]


def matches_role(text: str, role: str, variants=None, keywords=None) -> bool:
    """判断一段文本是否指向目标岗位（任一变体整串命中，或 token 命中）"""
    t = (text or "").lower()
    if not t:
        return False
    for term in [role, *(variants or [])]:
        term = (term or "").strip().lower()
        if len(term) >= 2 and term in t:
            return True
    return any(tok in t for tok in role_match_tokens(role, keywords, variants))
