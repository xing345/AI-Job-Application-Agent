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


# ====================================================================== #
# 模糊方向 -> 岗位大类/方向词族
#
# 用户往往只知道一个模糊方向（如「AI应用开发」），说不出准确岗位名。
# infer_direction() 负责把模糊输入归到一个「方向词族」，
# title_direction_relevance() 再用词族去判断招聘列表里的每个职位标题
# 是否与该方向相关 —— 不要求标题精确出现用户输入的岗位名。
# ====================================================================== #

# 标题里「像一个技术职位」的通用职业词
TITLE_OCCUPATION_WORDS = (
    "工程师", "开发", "架构师", "算法", "研究员", "科学家", "分析师",
    "技术专家", "研发", "测试", "运维",
    "engineer", "developer", "architect", "scientist", "researcher",
    "analyst", "intern",
)

# 方向词族：triggers 用于识别「用户想找什么方向」（匹配用户输入），
# title_keywords 用于识别「招聘列表里的标题属于这个方向」（覆盖面要宽）。
# 顺序即优先级：越具体的方向越靠前（AI 先于泛技术）。
DIRECTION_FAMILIES = [
    {
        "key": "ai",
        "category": "技术类",
        "label": "AI/算法",
        "triggers": [
            "ai", "人工智能", "大模型", "llm", "机器学习", "深度学习", "算法",
            "nlp", "自然语言", "计算机视觉", "aigc", "生成式", "智能体",
            "agent", "多模态", "神经网络", "gpt", "智能", "模型",
        ],
        "title_keywords": [
            "ai", "人工智能", "大模型", "llm", "机器学习", "深度学习",
            "算法", "nlp", "自然语言", "计算机视觉", "cv", "图像算法",
            "语音", "aigc", "生成式", "智能体", "agent", "多模态",
            "模型", "gpt", "神经网络", "推理引擎", "训练框架", "数据挖掘",
            "推荐算法", "搜索算法", "知识图谱", "diffusion", "cuda",
            "机器学习平台", "ai应用", "应用算法", "智能", "机器人",
        ],
    },
    {
        "key": "frontend",
        "category": "技术类",
        "label": "前端",
        "triggers": ["前端", "web前端", "react", "vue", "gui开发"],
        "title_keywords": [
            "前端", "web", "react", "vue", "javascript", "typescript",
            "h5", "gui", "客户端界面",
        ],
    },
    {
        "key": "backend",
        "category": "技术类",
        "label": "后端/服务端",
        "triggers": ["后端", "服务端", "java", "go", "golang", "python开发", "服务器开发"],
        "title_keywords": [
            "后端", "服务端", "java", "golang", "go开发", "python",
            "c++", "rust", "php", "服务开发", "平台开发",
        ],
    },
    {
        "key": "mobile",
        "category": "技术类",
        "label": "移动端/客户端",
        "triggers": ["移动端", "客户端", "android", "ios", "flutter"],
        "title_keywords": ["android", "ios", "移动端", "客户端", "flutter", "鸿蒙"],
    },
    {
        "key": "data",
        "category": "技术类",
        "label": "数据",
        "triggers": ["大数据", "数据分析", "数据开发", "数据科学", "数仓", "bi"],
        "title_keywords": [
            "大数据", "数据分析", "数据开发", "数据科学", "数仓",
            "数据工程", "etl", "bi工程师", "数据库",
        ],
    },
    {
        "key": "qa",
        "category": "技术类",
        "label": "测试/质量",
        "triggers": ["测试", "qa", "质量保障", "测试开发"],
        "title_keywords": ["测试", "qa", "质量", "test", "sdet"],
    },
    {
        "key": "devops",
        "category": "技术类",
        "label": "运维/SRE",
        "triggers": ["运维", "devops", "sre", "云原生"],
        "title_keywords": ["运维", "devops", "sre", "云原生", "基础架构", "网络安全", "安全工程师"],
    },
    {
        "key": "product",
        "category": "产品类",
        "label": "产品",
        "triggers": ["产品经理", "产品"],
        "title_keywords": ["产品经理", "产品策划", "产品助理", "product manager"],
    },
    {
        "key": "design",
        "category": "设计类",
        "label": "设计",
        "triggers": ["设计", "ui", "交互", "视觉"],
        "title_keywords": ["设计", "ui", "交互", "视觉", "ux", "designer"],
    },
    {
        "key": "operation",
        "category": "运营类",
        "label": "运营",
        "triggers": ["运营"],
        "title_keywords": ["运营", "内容策划", "增长"],
    },
]

# 兜底：用户输入含这些词但没命中任何具体方向时，归为泛技术类
_GENERIC_TECH_TRIGGERS = (
    "开发", "工程师", "技术", "软件", "编程", "研发", "it", "互联网", "程序",
)

# 泛技术类的标题职业词（无明确方向时，任何技术职位都先保留，交给 JD 匹配阶段细判）
GENERIC_TECH_TITLE_KEYWORDS = list(TITLE_OCCUPATION_WORDS)


def infer_direction(role: str, keywords: Optional[Iterable[str]] = None) -> dict:
    """
    从用户的模糊方向输入推断岗位大类与方向词族（纯规则、零 API 成本）

    Args:
        role: 用户填的目标方向/岗位，如「AI应用开发」「前端」
        keywords: 简历技能（可辅助判断方向），如 ["PyTorch", "LangChain"]

    Returns:
        {"key", "category", "label", "triggers", "title_keywords"}
        无法归入具体方向时 key=None；title_keywords 始终是 list（可能为空）。
    """
    blob = " ".join(
        [str(role or ""), *[str(k) for k in (keywords or [])]]
    ).lower()

    best, best_hits = None, 0
    for fam in DIRECTION_FAMILIES:
        hits = sum(1 for trig in fam["triggers"] if trig.lower() in blob)
        if hits > best_hits:
            best, best_hits = fam, hits

    if best is not None:
        return {
            "key": best["key"],
            "category": best["category"],
            "label": best["label"],
            "triggers": list(best["triggers"]),
            "title_keywords": list(best["title_keywords"]),
        }

    is_tech = any(t in blob for t in _GENERIC_TECH_TRIGGERS)
    return {
        "key": None,
        "category": "技术类" if is_tech else "综合类",
        "label": "泛技术" if is_tech else "未分类",
        "triggers": [],
        "title_keywords": list(GENERIC_TECH_TITLE_KEYWORDS) if is_tech else [],
    }


def title_direction_relevance(title: str, title_keywords: Optional[Iterable[str]]) -> tuple:
    """
    判断一个职位标题与方向词族的相关程度

    Returns:
        (strong_hits, is_occupation):
        strong_hits   —— 命中方向词族的次数（0 表示标题与该方向不相关）
        is_occupation —— 标题本身是否像一个职位（含通用职业词）
    """
    t = (title or "").lower()
    kws = [str(k).lower() for k in (title_keywords or []) if k]
    strong_hits = sum(1 for kw in kws if kw in t)
    is_occupation = any(w in t for w in TITLE_OCCUPATION_WORDS)
    return strong_hits, is_occupation
