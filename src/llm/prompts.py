"""所有 LLM Prompt 模板集中管理。

不散落各模块，统一在此维护。
"""
from __future__ import annotations

import json
from typing import List


# ============================================================
# 1. 标题语义初筛
# ============================================================

def title_screen_prompt(target_directions: List[str], titles: List[str]) -> List[dict]:
    """批量判断岗位标题是否与目标方向语义相关。

    一次处理最多 20 个标题。
    优化：针对技术类候选人，更精准地识别技术岗 vs 非技术岗。
    """
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    target_str = "、".join(target_directions) if target_directions else "软件开发/AI相关"

    system = (
        "你是岗位筛选专家，候选人目标是技术类方向。根据候选人目标方向，批量判断岗位标题是否语义相关。\n"
        "规则：\n"
        "1. 不要求标题字面一致，意思相关就算。例如目标'AI Agent开发'，则"
        "'大模型应用工程师'、'LLM开发'、'智能体研发'、'对话系统工程师'、'RAG工程师'都算相关。\n"
        "2. 明显技术类岗位都算相关：开发、工程师、算法、前端、后端、全栈、客户端、运维、测试、"
        "数据库、安全、AI、大模型、机器学习、数据、云计算、区块链、嵌入式、硬件、芯片、音视频、游戏开发等。\n"
        "3. 明显非技术类岗位排除：行政、人事、HR、财务、会计、销售、市场、品牌、公关、文案、"
        "运营（非技术运营）、设计、法务、供应链、采购、客服、质检、生产、制造、建筑、医疗、教育、"
        "培训、金融、投资、保险、地产、物业、酒店、餐饮、零售、物流、司机、保安、保洁、管培生等。\n"
        "4. 拿不准的判断标准：\n"
        "   - 如果标题中包含技术关键词（开发/工程师/算法/技术/研发/代码/编程/系统/平台/数据/AI/模型等），算相关\n"
        "   - 如果标题明显是职能/业务/支持类（专员/主管/经理/助理/顾问/协调/专员等且无技术关键词），算不相关\n"
        "   - 实在无法判断时，算相关（进入下一层用 JD 判断，不要误杀）\n"
        "5. 只输出 JSON，不要解释。"
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
    """读完整 JD + 简历，输出结构化匹配结果。

    优化点：
    1. 先识别 JD 中的硬性要求和加分项
    2. 逐条评估候选人是否满足
    3. 评分必须有依据，区分硬性要求满足度和加分项
    4. matched_points/missing_points 格式：[硬性/加分] 内容
    5. direction_match 严格定义：必须是技术开发岗，非技术岗不算
    6. JD 内容失效时强制 direction_match=False，低分
    """
    system = (
        "你是资深招聘匹配专家。阅读完整 JD 和候选人简历，按以下步骤输出匹配评估：\n\n"
        "步骤0：JD 有效性校验（必须先做）\n"
        "- 如果 JD 内容过短（<100字），或主要是网站导航/页脚文本（如包含'首页''岗位投递''校招答疑''切换到社招'等导航词，且没有'岗位职责''任职要求''工作职责'等关键词），判定为 JD 提取失败。\n"
        "- JD 提取失败时：score=0-20，direction_match=false，hard_requirements_total=0，hard_requirements_met=0，reason说明'JD内容失效，无法匹配'。\n\n"
        "步骤1：分析 JD，识别要求\n"
        "- 从 JD 的任职要求中识别【硬性要求】（必须满足，如学历、年限、核心技能）\n"
        "- 识别【加分项】（优先考虑但非必须，如特定框架经验、行业背景）\n\n"
        "步骤2：逐条评估\n"
        "- 对每条硬性要求，判断候选人是否满足\n"
        "- 对每条加分项，判断候选人是否具备\n\n"
        "步骤3：方向匹配判断（direction_match，严格标准）\n"
        "- direction_match=true 的条件：岗位必须是【技术开发/算法/工程类岗位】，且方向与候选人目标（AI Agent开发、AI应用开发、AI全栈、大模型应用、后端开发）一致。\n"
        "- 以下岗位即使 JD 提到 AI，direction_match 也必须为 false：\n"
        "  * 市场/营销/商务/销售/运营类（如'国际化生态平台''游戏运营''市场品牌'）\n"
        "  * 产品/策划类（如'技术策划''产品经理'，除非明确是AI产品经理且要求技术背景）\n"
        "  * 美术/设计/音频/表现类（如'音频算法''3D美术''游戏特效'，除非明确是算法研发岗）\n"
        "  * 人力资源/行政/财务/法务/综合类\n"
        "- 实习生岗位：如果候选人是应届毕业生找全职工作，实习生岗位 direction_match 应更谨慎，除非岗位明确面向应届毕业生且可转正。\n\n"
        "步骤4：评分（0-100），评分依据：\n"
        "- 硬性要求满足度是基础分（占70%）：全部满足≥70分，每缺1条硬性要求扣10-15分\n"
        "- 加分项是提升分（占30%）：满足的加分项越多分数越高\n"
        "- direction_match=false 直接扣20分以上，且最高不超过60分\n"
        "- 简历完全不相关给0-30分\n"
        "- JD 提取失败给0-20分\n\n"
        "输出字段：\n"
        "- score: 0-100 综合匹配度\n"
        "- direction_match: 岗位方向是否与候选人目标一致（bool，严格按步骤3判断）\n"
        "- direction_reason: 方向判断理由，必须说明岗位类型和判断依据\n"
        "- hard_requirements_total: JD 中识别出的硬性要求总数\n"
        "- hard_requirements_met: 候选人满足的硬性要求数量\n"
        "- matched_points: 候选人满足的要求，格式：[硬性] 内容 或 [加分] 内容\n"
        "- missing_points: 候选人不满足的要求，格式：[硬性] 内容 或 [加分] 内容\n"
        "- reason: 综合匹配理由，必须包含评分依据（硬性要求满足X/Y条，加分项满足Z条，方向是否匹配）\n\n"
        "必须看 JD 实际内容判断，不要只看标题。只输出 JSON。"
    )

    user = (
        f"【岗位标题】{job_title}\n\n"
        f"【岗位 JD】\n{jd_text}\n\n"
        f"【候选人简历】\n{resume_text}\n\n"
        "请按步骤分析并输出匹配结果 JSON。"
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
        "3. 开放式问题（为什么加入我们、个人优势、自我介绍、AI 协作经历、常用 AI 工具等）"
        "必须结合 JD 中的具体要求和候选人真实项目生成针对性回答，不要用通用模板。\n"
        "4. 简历/画像中确实没有、也无法合理推断的字段填 null，不要编造"
        "（如论文、导师、紧急联系人、个人照片等）。\n"
        "5. 对 type 为 select/combobox/radio 的字段，value 必须严格等于该字段 options 中"
        "列出的某一项的完整文本；options 为空时再按语义填写。\n"
        "6. 必须为输入字段列表中的【每一个】字段输出一条记录，index 与输入一一对应、"
        "顺序一致，不得遗漏、合并或新增。\n"
        "7. 只输出 JSON。"
    )

    try:
        n_fields = len(json.loads(fields_json))
    except Exception:
        n_fields = None

    user = (
        f"【岗位标题】{job_title}\n\n"
        f"【岗位 JD】\n{jd_text}\n\n"
        f"【候选人画像】\n{profile_summary}\n\n"
        f"【候选人简历】\n{resume_text}\n\n"
        f"【表单字段列表（JSON）】\n{fields_json}\n\n"
        f"请为上述每个字段（共 {n_fields} 个）输出："
        "{\"fields\": [{\"index\": 序号, \"semantic_type\": 语义分类, \"value\": 填写值或null}]}，"
        f"fields 数组必须恰好包含 {n_fields} 条。"
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
