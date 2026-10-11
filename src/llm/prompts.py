"""所有 LLM Prompt 模板集中管理。

不散落各模块，统一在此维护。
"""
from __future__ import annotations

from typing import List


# ============================================================
# 1. 标题语义初筛
# ============================================================

def title_screen_prompt(target_directions: List[str], titles: List[str]) -> List[dict]:
    """批量判断岗位标题是否与目标方向语义相关。

    一次处理最多 20 个标题。
    """
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    target_str = "、".join(target_directions) if target_directions else "软件开发/AI相关"

    system = (
        "你是岗位筛选专家。根据候选人目标方向，批量判断岗位标题是否语义相关。\n"
        "规则：\n"
        "1. 不要求标题字面一致，意思相关就算。例如目标'AI Agent开发'，则"
        "'大模型应用工程师'、'LLM开发'、'智能体研发'、'对话系统工程师'、'RAG工程师'都算相关。\n"
        "2. 明显不相干的（行政、财务、销售、HR、文案、市场、运营、设计、法务、供应链）排除。\n"
        "3. 拿不准的算相关，进入下一层用 JD 判断，不要误杀。\n"
        "4. 只输出 JSON，不要解释。"
    )

    user = (
        f"候选人目标方向：{target_str}\n\n"
        f"岗位标题列表：\n{numbered}\n\n"
        "请输出 JSON：{\"related_indices\": [相关的序号列表], \"unrelated_indices\": [不相关的序号列表]}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ============================================================
# 2. JD 深度匹配
# ============================================================

def job_match_prompt(resume_text: str, job_title: str, jd_text: str) -> List[dict]:
    """读完整 JD + 简历，输出结构化匹配结果。"""
    system = (
        "你是资深招聘匹配专家。阅读完整 JD 和候选人简历，输出匹配评估。\n"
        "评估维度：\n"
        "- score: 0-100 综合匹配度\n"
        "- direction_match: 岗位方向是否与候选人目标一致（bool）+ 理由\n"
        "- matched_points: 候选人满足的要求，逐条列出\n"
        "- missing_points: 候选人不满足或缺失的要求，逐条列出\n"
        "- reason: 综合匹配理由\n"
        "必须看 JD 实际内容判断，不要只看标题。只输出 JSON。"
    )

    user = (
        f"【岗位标题】{job_title}\n\n"
        f"【岗位 JD】\n{jd_text}\n\n"
        f"【候选人简历】\n{resume_text}\n\n"
        "请输出匹配结果 JSON。"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ============================================================
# 3. 表单字段语义理解 + 值生成
# ============================================================

def fill_fields_prompt(
    resume_text: str,
    profile_summary: str,
    job_title: str,
    jd_text: str,
    fields_json: str,
) -> List[dict]:
    """理解表单字段语义，从简历+画像提取值，开放式问题结合 JD 生成回答。"""
    system = (
        "你是求职申请表填写专家。根据候选人简历、画像和目标岗位 JD，"
        "为每个表单字段生成填写值。\n"
        "规则：\n"
        "1. 看 label 文本判断字段含义，不依赖 name 属性。\n"
        "2. 从简历和画像中提取对应值。\n"
        "3. 开放式问题（为什么加入我们、个人优势、自我介绍等）必须结合 JD 中的具体要求生成针对性回答，"
        "不要用通用模板。\n"
        "4. 不确定的字段填 null，不要编造。\n"
        "5. select/radio 字段，value 必须是 options 中的一个精确值。\n"
        "6. 只输出 JSON，字段顺序与输入一致。"
    )

    user = (
        f"【岗位标题】{job_title}\n\n"
        f"【岗位 JD】\n{jd_text}\n\n"
        f"【候选人画像】\n{profile_summary}\n\n"
        f"【候选人简历】\n{resume_text}\n\n"
        f"【表单字段列表（JSON）】\n{fields_json}\n\n"
        "请为每个字段输出：{\"fields\": [{\"index\": 序号, \"semantic_type\": 语义分类, \"value\": 填写值或null}]}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ============================================================
# 4. 投递配额排序
# ============================================================

def quota_sort_prompt(
    target_directions: List[str],
    resume_summary: str,
    jobs_summary: str,
    max_count: int,
) -> List[dict]:
    """当候选岗位超过配额时，LLM 辅助排序推荐。"""
    target_str = "、".join(target_directions) if target_directions else "软件开发"

    system = (
        "你是投递策略专家。候选人在该公司有投递数量上限，请从候选岗位中选出最优的一批。\n"
        "决策规则：\n"
        "1. 优先选择与目标方向一致的岗位（即使匹配度略低）。\n"
        "2. 目标方向岗位不足时，用高匹配度岗位补足。\n"
        "3. 考虑岗位多样性，不要全选同一类。\n"
        "4. 每个选择给出理由。\n"
        "只输出 JSON。"
    )

    user = (
        f"【候选人目标方向】{target_str}\n\n"
        f"【候选人简历摘要】\n{resume_summary}\n\n"
        f"【候选岗位列表】\n{jobs_summary}\n\n"
        f"【最多选择】{max_count} 个岗位\n\n"
        "请输出：{\"recommended\": [岗位序号列表], \"reasoning\": \"选择理由\"}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ============================================================
# 5. 自然语言转 UserProfile（验收用）
# ============================================================

def text_to_profile_prompt(text: str) -> List[dict]:
    """把自然语言简历文本转成结构化 UserProfile JSON。"""
    system = (
        "你是简历解析专家。把候选人的自然语言描述转成结构化 JSON。\n"
        "字段包括：name, phone, email, education(school/major/degree/start_date/end_date), "
        "work_experience(company/position/start_date/end_date/responsibilities/achievements), "
        "projects(name/role/tech_stack/description/achievements), skills, "
        "target_cities, target_directions, expected_salary, available_date, self_introduction。\n"
        "没有的信息留空或空数组。只输出 JSON。"
    )

    user = f"【简历文本】\n{text}\n\n请输出结构化 JSON。"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
