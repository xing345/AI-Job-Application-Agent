"""
岗位方向诊断器 - 根据求职者实际情况, 分析推荐 3-5 个岗位方向并给出建议
核心价值: 技能多而杂、目标不明确的人, 也能得到清晰可执行的方向
"""

import json
from typing import Optional
from loguru import logger

from src.utils.llm_client import LLMClient, get_llm_client
from .schemas import UserProfile, CareerAnalysisResult

ANALYZER_SYSTEM_PROMPT = """你是资深的职业规划顾问与招聘市场分析专家。你的任务是根据求职者的实际情况, 帮他理出 3-5 个清晰、可执行、有市场的岗位方向, 并给出具体建议。

求职者的典型情况: 会的东西很多很杂, 但没有明确的岗位目标, 简历也不够好。你需要的不是泛泛而谈, 而是:
1. 从他的技能/经历里找出真正能打的组合, 落到具体职位名。
2. 每个方向都要有明确的搜索关键词, 方便后续直接搜索岗位。
3. 结合市场现实说明可行性 (哪些方向需求大、好入门、竞争如何)。
4. 给出可执行建议: 简历怎么改、怎么投、需要补什么。"""


class CareerDirectionAnalyzer:
    """岗位方向诊断器"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or get_llm_client()

    async def analyze(self, profile: UserProfile) -> CareerAnalysisResult:
        """分析推荐岗位方向"""
        prompt = f"""请基于求职者的实际情况, 给出 3-5 个最合适的岗位方向及建议。

求职者实际情况 (JSON):
{json.dumps(profile.model_dump(), ensure_ascii=False, indent=2)}

要求:
- 方向要具体到可搜索的职位名, 不要写 "程序员" 这种大而空的名字。
- 每个方向的 keywords 要覆盖该方向在国内/主流招聘平台常见的搜索词 (中英文均可)。
- skill_highlights 必须来自他真实会的东西, 不要凭空编造。
- priority 按 1-5 标注推荐优先级, 5 最高。
- 总体建议 overall_advice 要覆盖: 先主攻哪个方向、简历怎么调整、投递策略。"""

        try:
            result = await self.llm_client.generate_structured_response(
                prompt,
                CareerAnalysisResult,
                system_prompt=ANALYZER_SYSTEM_PROMPT,
            )
            logger.info(f"岗位方向诊断完成, 共 {len(result.directions)} 个方向")
            return result
        except Exception as e:
            logger.error(f"岗位方向诊断失败: {e}")
            raise
