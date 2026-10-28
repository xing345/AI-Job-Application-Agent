"""标题语义初筛节点。

两层过滤策略：
1. 规则预过滤：用关键词快速排除明显非技术岗（行政/财务/销售等），
   保留明显技术岗（开发/工程师/算法等），减少 LLM 调用量。
2. LLM 精筛：对拿不准的岗位，每 20 个打包一次 LLM 语义判断。

不要求字面一致，意思相关就算。拿不准的进 LLM，不误杀。
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import List, Tuple

from src.agent.state import AgentState
from src.llm import client as llm
from src.llm.prompts import title_screen_prompt
from src.models.match import TitleScreenResult
from src.models.job import JobPosting
from src.storage import state_db

logger = logging.getLogger(__name__)

BATCH_SIZE = 20

# ============================================================
# 规则预过滤关键词
# ============================================================

# 明显技术类关键词（直接保留，不进 LLM）
TECH_KEYWORDS = [
    # 通用技术
    "开发", "工程师", "程序员", "架构师", "研发", "技术",
    "前端", "后端", "全栈", "客户端", "服务端", "中台",
    "数据库", "运维", "测试", "DevOps", "SRE", "DBA",
    "网络", "通信", "安全", "渗透", "攻防",
    # AI / 算法
    "算法", "AI", "人工智能", "大模型", "LLM", "Agent", "智能体",
    "机器学习", "深度学习", "NLP", "CV", "计算机视觉", "语音",
    "RAG", "Prompt", "AIGC", "推荐", "搜索", "数据挖掘",
    "研究员", "算法工程师", "AI工程师", "机器学习工程师",
    # 数据 / 云
    "数据", "大数据", "数据分析", "数据开发", "数仓", "ETL",
    "云计算", "云原生", "容器", "K8s", "微服务",
    # 区块链 / Web3
    "区块链", "Web3", "Solidity", "智能合约",
    # 具体技术方向
    "Web", "小程序", "APP", "iOS", "Android", "安卓", "苹果",
    "嵌入式", "硬件", "芯片", "FPGA", "ASIC", "驱动",
    "Java", "Python", "Go", "C++", "Rust", "Node", "前端开发",
    "后端开发", "全栈开发", "客户端开发", "游戏开发", "图形",
    "渲染", "引擎", "音视频", "编解码", "流媒体",
    "QA", "测试开发", "自动化测试", "性能测试",
    # 注意："质量"太宽泛已移除；"质检"/"品控"是非技术类，在 NON_TECH_KEYWORDS 中
    "平台", "基础架构", "基础设施", "中间件", "分布式",
    "高并发", "高性能", "系统", "软件", "程序员",
    "XR", "VR", "AR", "元宇宙", "机器人", "自动驾驶",
    "量化", "风控建模", "反欺诈", "知识图谱",
]

# 明显非技术类关键词（直接排除，不进 LLM）
NON_TECH_KEYWORDS = [
    # 行政/人事/财务
    "行政", "人事", "HR", "人力资源", "财务", "会计", "出纳", "审计", "税务",
    # 销售/市场/品牌
    "销售", "客户经理", "商务", "BD", "市场", "品牌", "公关", "推广", "营销",
    "渠道", "招商", "加盟", "直销", "分销", "经纪",
    # 运营/内容/设计
    "运营", "内容运营", "用户运营", "产品运营", "活动运营", "社群运营",
    "新媒体", "文案", "编辑", "记者", "编导", "策划",
    "设计", "UI", "UX", "视觉", "平面", "美工", "插画",
    "摄影", "剪辑", "后期", "动画", "原画", "3D建模",
    # 法务/合规/风控（非技术类）
    "法务", "律师", "合规", "风控专员", "内控",
    # 供应链/采购/物流
    "供应链", "采购", "物流", "仓储", "运输", "报关", "跟单",
    # 客服/质检/支持
    "客服", "售后", "咨询顾问", "客户成功", "技术支持", "IT支持", "帮助台",
    "质检", "品控", "质量专员",
    # 生产/制造/工程（非软件类）
    "生产", "制造", "工艺", "车间", "产线", "操作工", "装配",
    "机械", "电气", "土木", "建筑", "结构", "给排水", "暖通",
    # 医疗/教育/培训
    "医生", "护士", "医师", "药师", "检验", "影像", "康复",
    "教师", "老师", "教授", "讲师", "教练", "培训", "教务", "课程顾问",
    # 金融/投资/保险（非技术类）
    "投资", "金融", "银行", "证券", "基金", "保险", "信贷", "理财", "柜员",
    # 地产/物业/酒店/餐饮
    "地产", "房产", "物业", "工程管理", "酒店", "餐饮", "厨师", "服务员",
    "店长", "导购", "收银", "前台", "接待",
    # 零售/电商（非技术类）
    "零售", "电商运营", "淘宝", "京东", "拼多多", "直播", "主播", "网红",
    "达人", "选品", "店铺",
    # 其他非技术
    "管培生", "储备干部", "管理培训生", "总经理", "总监", "经理助理",
    "秘书", "助理", "文员", "办事员", "专员", "主管", "组长",
    "司机", "保安", "保洁", "环卫", "绿化", "园艺",
    "翻译", "口译", "笔译", "本地化",
    "艺人", "模特", "演员", "歌手", "舞蹈", "音乐",
    "体育", "健身", "教练", "裁判",
    "农业", "林业", "牧业", "渔业", "养殖", "种植",
    "地质", "勘探", "采矿", "石油", "能源", "环保", "环境",
    "纺织", "服装", "鞋类", "箱包", "珠宝", "化妆品",
    "出版", "印刷", "包装", "图书", "期刊", "杂志",
    "博物馆", "图书馆", "档案馆", "文化馆",
    "社工", "志愿者", "公益", "慈善",
    "军人", "警察", "消防", "城管", "海关", "边检",
]


def rule_prefilter(jobs: List[JobPosting]) -> Tuple[List[JobPosting], List[JobPosting], List[JobPosting]]:
    """规则预过滤：将岗位分为三类。

    Returns:
        (tech_jobs, non_tech_jobs, uncertain_jobs)
        - tech_jobs: 明显技术类，直接保留
        - non_tech_jobs: 明显非技术类，直接排除
        - uncertain_jobs: 拿不准，进 LLM 精筛
    """
    tech_jobs: List[JobPosting] = []
    non_tech_jobs: List[JobPosting] = []
    uncertain_jobs: List[JobPosting] = []

    for job in jobs:
        title = job.title or ""
        title_lower = title.lower()

        # 先检查是否明显非技术（排除优先，避免"运营开发"被误判为非技术）
        is_non_tech = False
        for kw in NON_TECH_KEYWORDS:
            if kw.lower() in title_lower:
                # 特殊情况：某些词在技术语境下也是技术岗
                # 如"技术支持"虽然含"支持"，但通常算技术相关
                # 如"游戏运营"含"运营"，但可能是技术运营
                # 这里简单处理：如果同时包含技术关键词，则不算非技术
                has_tech = any(tkw.lower() in title_lower for tkw in TECH_KEYWORDS)
                if not has_tech:
                    is_non_tech = True
                    break

        if is_non_tech:
            non_tech_jobs.append(job)
            continue

        # 检查是否明显技术类
        is_tech = False
        for kw in TECH_KEYWORDS:
            if kw.lower() in title_lower:
                is_tech = True
                break

        if is_tech:
            tech_jobs.append(job)
        else:
            uncertain_jobs.append(job)

    return tech_jobs, non_tech_jobs, uncertain_jobs


async def screen_batch(titles: List[str], target_directions: List[str], run_id: str = "") -> TitleScreenResult:
    """批量判断一组标题的语义相关性。"""
    messages = title_screen_prompt(target_directions, titles)
    result = await llm.chat_structured(messages, TitleScreenResult, temperature=0.1, run_id=run_id)
    return result


# ============================================================
# 深度处理优先级：按标题与核心目标方向的相关度排序并限量
# ============================================================

# 核心 AI 应用/Agent 方向（最高优先）
CORE_AI_KEYWORDS = [
    "agent", "智能体", "ai应用", "大模型应用", "llm应用", "aigc应用",
    "ai agent", "aigc", "ai开发", "ai工程师", "ai全栈", "ai平台",
    "ai infra", "大模型应用开发", "rag", "copilot", "智能助手", "对话系统",
    "大模型工程师", "llm工程师", "ai产品", "智能应用",
]
# AI / 算法（高优先）
AI_KEYWORDS = [
    "大模型", "llm", "人工智能", "机器学习", "深度学习", "nlp",
    "自然语言", "多模态", "计算机视觉", "知识图谱", "算法工程师", "算法平台",
    "ai", "生成式",
]
# 全栈（AI 全栈方向，中高）
FULLSTACK_KEYWORDS = ["全栈", "前后端", "web全栈"]
# 后端 / 服务端（中）
BACKEND_KEYWORDS = ["后端", "服务端", "后台", "server", "java", "golang", "go"]
# 前端 / 客户端（中低）
FRONTEND_KEYWORDS = ["前端", "客户端", "ios", "android"]
# 降权：偏理论研究 / 数据构建（非工程应用）
RESEARCH_DOWN_KEYWORDS = [
    "预训练", "数据构建", "数据集", "dataset", "课题", "benchmark", "范式研究",
    "理论研究", "算法研究", "研究员", "科学家", "博士后", "实验室", "基础研究",
    "数据挖掘研究", "评测研究",
]
# 降权：硬件 / 非软件 / 运维测试
HARDWARE_DOWN_KEYWORDS = [
    "硬件", "芯片", "服务器", "fpga", "asic", "板卡", "机房",
    "运维", "测试", "qa", "sre",
]
# 非技术角色（即使标题带 AI 也要强降权，只投技术开发岗）
NON_TECH_ROLE_KEYWORDS = [
    "运营", "市场", "营销", "投放", "品牌", "公关", "销售", "商务",
    "产品经理", "客户经理", "策划", "文案", "推广", "渠道", "招商",
    "人力", "财务", "行政", "法务", "客服", "培训生", "管培",
]
# 工程开发标记（含这些词时不算纯非技术角色）
ENGINEERING_MARKERS = ["工程师", "开发", "研发", "技术", "架构", "工程", "算法", "研究员", "科学家"]


def _contains(t: str, kw: str) -> bool:
    """标题包含判断；英文词按词边界匹配，避免 ai 命中 detail。t 已 lower。"""
    kw = kw.lower()
    if kw.isascii() and any(c.isalpha() for c in kw):
        return re.search(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])", t) is not None
    return kw in t


def title_priority_score(title: str) -> int:
    """按标题给深度处理优先级打分，越高越优先。"""
    t = (title or "").lower()
    score = 0
    if any(_contains(t, k) for k in CORE_AI_KEYWORDS):
        score += 100
    if any(_contains(t, k) for k in AI_KEYWORDS):
        score += 60
    if any(_contains(t, k) for k in FULLSTACK_KEYWORDS):
        score += 55
    if any(_contains(t, k) for k in BACKEND_KEYWORDS):
        score += 40
    if any(_contains(t, k) for k in FRONTEND_KEYWORDS):
        score += 30
    if any(_contains(t, k) for k in RESEARCH_DOWN_KEYWORDS):
        score -= 45
    if any(_contains(t, k) for k in HARDWARE_DOWN_KEYWORDS):
        score -= 50
    if "实习" in t or _contains(t, "intern"):
        score -= 40  # 应届找全职，实习岗明显降权（含中文"实习"与英文 intern）
    # 纯非技术角色（标题无任何工程开发标记），即使带 AI 也强降权踢出深度列表
    if any(_contains(t, k) for k in NON_TECH_ROLE_KEYWORDS) and not any(
            m in t for m in ENGINEERING_MARKERS):
        score -= 150
    return score


def _norm_title_for_dedup(title: str) -> str:
    """规范化标题用于去重：仅去空白/大小写，不截断，避免误合并不同岗位。"""
    return re.sub(r"\s+", "", (title or "").lower())


# 青云计划/课题研究类岗位（category_path 含"青云"），以博士为主，对本科用户强降权
QINGYUN_DOWN = 130

# 海外地点（用户目标为国内城市），含这些地点的岗位降权，避免海外实习/研究岗挤占名额
OVERSEAS_LOCATIONS = [
    "london", "singapore", "united kingdom", "united states", "usa",
    "hong kong", "korea", "japan", "malaysia", "海外",
]


def job_priority_score(job: JobPosting) -> int:
    """标题方向分 + 青云课题降权 + 海外地点降权。"""
    score = title_priority_score(job.title)
    if "青云" in (job.category_path or ""):
        score -= QINGYUN_DOWN
    loc = (job.location or "").lower()
    if any(w in loc for w in OVERSEAS_LOCATIONS):
        score -= 90
    return score


def prioritize_jobs(jobs: List[JobPosting], max_deep: int) -> List[JobPosting]:
    """按方向相关度降序；同标题（多城市/批次）只留最靠前一个，再取前 max_deep。

    青云课题（博士导向）对本科用户强降权，确保普通 AI 开发/全栈岗优先进入深度处理。
    """
    ordered = sorted(jobs, key=job_priority_score, reverse=True)
    seen_titles: set[str] = set()
    unique: List[JobPosting] = []
    for j in ordered:
        key = _norm_title_for_dedup(j.title)
        if key in seen_titles:
            continue
        seen_titles.add(key)
        unique.append(j)
    if max_deep and max_deep > 0:
        return unique[:max_deep]
    return unique


def get_max_deep() -> int:
    try:
        return max(0, int(os.environ.get("JOB_AGENT_MAX_DEEP", "80")))
    except ValueError:
        return 80


async def run(state: AgentState) -> AgentState:
    """LangGraph 节点：标题语义初筛（规则预过滤 + LLM 精筛）。"""
    if not state.discovered_jobs:
        state.add_error("screen_titles", "没有可筛选的岗位")
        return state

    site_name = state.site_name or "unknown"

    # 缓存复用：该站点已完整初筛过（无 -1 标记），直接加载通过岗位
    if site_name != "unknown":
        cached = await state_db.get_cached_screened(site_name)
        if cached is not None:
            cached_jobs = [
                JobPosting(
                    title=r.get("job_title") or "",
                    company=r.get("company") or "",
                    location=r.get("location") or "",
                    detail_url=r["job_url"],
                    category_path=r.get("category_path") or "",
                    site_name=r.get("site_name") or site_name,
                ) for r in cached]
            max_deep = get_max_deep()
            state.screened_jobs = prioritize_jobs(cached_jobs, max_deep)
            logger.info("Cache: %d screened -> %d after priority (site=%s)",
                        len(cached_jobs), len(state.screened_jobs), site_name)
            print(f"\n[标题初筛] 缓存 {len(cached_jobs)} 个通过岗位，按方向取前 {len(state.screened_jobs)} 个进入深度匹配（--max-deep 调整）")
            return state

    target_directions: List[str] = []
    if state.profile and state.profile.target_directions:
        target_directions = state.profile.target_directions
    else:
        target_directions = ["软件开发", "AI", "后端", "前端", "算法"]

    jobs = state.discovered_jobs
    total = len(jobs)

    # 第一层：规则预过滤
    tech_jobs, non_tech_jobs, uncertain_jobs = rule_prefilter(jobs)
    logger.info("规则预过滤: 总%d -> 技术%d + 非技术%d + 待定%d",
                total, len(tech_jobs), len(non_tech_jobs), len(uncertain_jobs))

    # 第二层：LLM 精筛（只处理拿不准的）
    related_from_llm: List[JobPosting] = []
    if uncertain_jobs:
        titles = [j.title for j in uncertain_jobs]
        logger.info("LLM 精筛: %d 个待定岗位，每 %d 个一批...", len(titles), BATCH_SIZE)

        related_indices: set[int] = set()

        for start in range(0, len(titles), BATCH_SIZE):
            batch = titles[start : start + BATCH_SIZE]
            batch_indices = list(range(start, start + len(batch)))

            try:
                result = await screen_batch(batch, target_directions, state.run_id)
                for rel_idx in result.related_indices:
                    if 0 <= rel_idx < len(batch_indices):
                        related_indices.add(batch_indices[rel_idx])
                logger.info("Batch %d-%d: %d related, %d unrelated",
                            start, start + len(batch), len(result.related_indices), len(result.unrelated_indices))
            except Exception as e:
                # LLM 调用失败时，保守地把这批全部算相关（不误杀）
                state.add_error("screen_titles", f"batch {start} 失败，全部保留: {e}")
                related_indices.update(batch_indices)

        related_from_llm = [uncertain_jobs[i] for i in sorted(related_indices)]
        llm_filtered = len(uncertain_jobs) - len(related_from_llm)
        logger.info("LLM 精筛完成: %d -> %d（过滤 %d）", len(uncertain_jobs), len(related_from_llm), llm_filtered)
    else:
        llm_filtered = 0

    # 合并：规则技术类 + LLM 判定相关（全部初筛通过岗位）
    screened_all = tech_jobs + related_from_llm

    # 记录初筛结果到库（-1 -> 1/0），供重跑复用（标记全部，不截断）
    if site_name != "unknown":
        await state_db.mark_screen_results(
            site_name,
            [j.detail_url for j in jobs],
            [j.detail_url for j in screened_all])

    # 按目标方向相关度排序并限量，得到进入深度抓取 JD + 匹配的岗位
    max_deep = get_max_deep()
    screened = prioritize_jobs(screened_all, max_deep)
    state.screened_jobs = screened

    total_filtered = total - len(screened)
    logger.info("初筛完成: 总%d -> 初筛通过%d，按方向取前%d（规则排除%d + LLM排除%d）",
                total, len(screened_all), len(screened),
                len(non_tech_jobs), llm_filtered)
    print(f"\n[标题初筛] {total} -> 初筛通过 {len(screened_all)}，按方向取前 {len(screened)} 个进入深度匹配（规则排除 {len(non_tech_jobs)}，LLM排除 {llm_filtered}；--max-deep 调整数量）")

    # 自动保存初筛结果到 output 目录，便于断点续跑和复用
    try:
        os.makedirs("output", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = f"output/screened_jobs_{site_name}_{ts}.json"
        jobs_data = []
        for job in screened:
            jobs_data.append({
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "detail_url": job.detail_url,
                "category_path": job.category_path,
                "site_name": job.site_name,
            })
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump({
                "site": site_name,
                "generated_at": datetime.now().isoformat(),
                "total_discovered": total,
                "total_screened": len(screened),
                "jobs": jobs_data,
            }, f, ensure_ascii=False, indent=2)
        logger.info("初筛结果已保存: %s (%d个岗位)", save_path, len(screened))
    except Exception as e:
        logger.warning("保存初筛结果失败: %s", e)

    return state
