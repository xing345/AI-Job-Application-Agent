"""
智能访谈器 - 通过多轮对话收集求职者的实际情况
LLM 驱动逐项提问, 直到信息足够, 产出结构化 UserProfile (不依赖简历)
"""

import json
from typing import Dict, List, Optional, Callable, Awaitable
from loguru import logger

from src.utils.llm_client import LLMClient, get_llm_client
from .schemas import UserProfile

# 访谈要覆盖的信息维度 (loose dict 的键)
COLLECTED_KEYS = [
    "name", "email", "phone",              # 基本信息
    "skills", "skill_notes",               # 技能全览 (杂列表 + 深度说明)
    "experience", "education", "projects",  # 经历
    "certificates", "languages",            # 证书语言
    "target_hint",                          # 模糊的职业想法
    "industries", "locations", "salary",    # 偏好
    "work_type", "deal_breakers",           # 约束
]

INTERVIEW_SYSTEM_PROMPT = """你是资深的职业咨询顾问和招聘专家。你的任务是通过一轮轮对话, 全面了解求职者的实际情况。

求职者的情况: 会的东西很多很杂, 但没有明确的岗位目标, 简历也不够好。你的职责是先把他的真实情况摸清楚。

要覆盖的信息维度:
1. 基本信息: 姓名、邮箱、电话 (必收)
2. 技能全览: 所有会的东西(可能很杂很多, 尽量问全), 每项技能的熟练程度和使用场景
3. 工作经历: 每段的公司、岗位、时间、主要职责、成果、用到的技术
4. 教育背景: 学校、专业、学历、时间
5. 项目经验: 项目、角色、技术栈、成果
6. 证书与语言
7. 职业偏好: 感兴趣的行业、期望地点、期望薪资、工作形式(全职/兼职/远程)
8. 职业想法: 他/她自己对方向的模糊想法(哪怕不明确)
9. 红线: 绝对不接受的条件

提问规则:
- 每次只问 1 个问题, 口语化, 不要一次问多个。
- 顺着上一轮的回答追问细节, 特别是技能深度、经历成果、技术栈这类对岗位匹配重要的信息。
- 技能很杂时, 多花几轮把技能问全。
- 如果求职者回答"不知道/没想好/跳过", 记为空并继续下一个维度。
- 基本信息(姓名/邮箱/电话)必须收齐, 否则不要 done。

判断规则:
- 当 基本信息、技能、经历、职业偏好 这几个核心维度都有足够信息时, 设 done=true。
- 最多 15 轮, 别拖泥带水。"""


class CareerInterviewer:
    """智能访谈器"""

    def __init__(self, llm_client: Optional[LLMClient] = None, max_rounds: int = 15):
        self.llm_client = llm_client or get_llm_client()
        self.max_rounds = max_rounds

    async def run_interview(
        self,
        ask_func: Optional[Callable[[str], str]] = None,
        user_answers: Optional[List[str]] = None,
    ) -> UserProfile:
        """
        运行智能访谈

        Args:
            ask_func: 提问函数, 默认为终端 input()。可注入用于测试。
            user_answers: 预置答案列表 (测试用), 提供后按顺序消费, 用尽则终止访谈。

        Returns:
            结构化 UserProfile
        """
        ask_func = ask_func or input
        transcript: List[Dict] = []
        collected: Dict = {}
        rounds_used = 0
        answer_pool = list(user_answers or [])
        pool_idx = 0

        for round_idx in range(self.max_rounds):
            rounds_used = round_idx + 1
            prompt = self._build_turn_prompt(transcript, collected, round_idx)
            try:
                resp = await self.llm_client.generate_response(
                    prompt, system_prompt=INTERVIEW_SYSTEM_PROMPT, json_output=True
                )
            except Exception as e:
                logger.error(f"访谈第 {round_idx+1} 轮 LLM 调用失败: {e}")
                break

            if isinstance(resp, str):
                logger.warning(f"访谈 LLM 返回非 JSON, 截断处理: {resp[:80]}")
                resp = {"question": "请继续补充你的情况, 还有哪些重要经历或技能?", "done": False}

            question = (resp.get("question") or "").strip()
            done = bool(resp.get("done"))
            if isinstance(resp.get("collected"), dict):
                collected = self._merge_collected(collected, resp["collected"])

            if done:
                break

            if not question:
                question = "请继续补充你的情况。"

            print(f"\n🧑‍💼 顾问: {question}")

            # 取答案: 测试预置答案优先, 否则询问用户
            if answer_pool:
                if pool_idx >= len(answer_pool):
                    logger.info("预置答案已用尽, 提前结束访谈")
                    break
                answer = answer_pool[pool_idx].strip()
                pool_idx += 1
                print(f"💬 你: {answer}")
            else:
                answer = ask_func("💬 你: ").strip()

            if answer.lower() in ("退出", "quit", "exit", "q"):
                logger.info("用户主动退出访谈")
                break
            if answer == "":
                answer = "(未回答)"

            transcript.append({"role": "question", "content": question})
            transcript.append({"role": "answer", "content": answer})

        logger.info(f"智能访谈完成, 共 {rounds_used} 轮")
        return await self._normalize_profile(collected, transcript)

    # ------------------------------------------------------------------ #
    def _build_turn_prompt(self, transcript: List[Dict], collected: Dict, round_idx: int) -> str:
        """构建单轮提问 prompt (无状态, 每次携带全部上下文)"""
        conv = "\n".join(
            f"顾问: {t['content']}" if t["role"] == "question" else f"求职者: {t['content']}"
            for t in transcript
        ) or "(对话尚未开始)"

        return f"""这是第 {round_idx + 1} 轮访谈。

到目前为止的对话:
{conv}

目前已收集的信息 (JSON):
{json.dumps(collected, ensure_ascii=False, indent=2) or "{}"}

请决定本轮动作, 严格输出 JSON, 字段如下:
{{
  "question": "你要问求职者的下一个问题 (只问一个; 若信息已足够则留空)",
  "done": true/false,
  "collected": {{
    将你已知的求职者信息累积到这里, 每次返回都要带上之前所有已知内容。字段键参考:
    {", ".join(COLLECTED_KEYS)}
    skills 是数组; experience/education/projects 是数组, 每项是 {{company/school/name, role, time, detail, tech}} 形式的对象; 其余为字符串或数组。
  }}
}}

规则:
- 基本信息 (name/email/phone) 未收齐时, done 必须为 false。
- done 为 true 时, collected 需包含核心维度信息。"""

    def _merge_collected(self, old: Dict, new: Dict) -> Dict:
        """合并两轮 collected (数组字段累加, 标量覆盖)"""
        merged = dict(old)
        for key, value in (new or {}).items():
            if isinstance(value, list) and isinstance(merged.get(key), list):
                merged[key] = merged[key] + [v for v in value if v]
            elif value not in (None, "", []):
                merged[key] = value
        return merged

    async def _normalize_profile(self, collected: Dict, transcript: List[Dict]) -> UserProfile:
        """把 loose collected 规范化为严格 UserProfile JSON"""
        conv = "\n".join(
            f"顾问: {t['content']}" if t["role"] == "question" else f"求职者: {t['content']}"
            for t in transcript
        )
        prompt = f"""请把一次职业访谈收集到的求职者信息, 规范化为严格的 UserProfile JSON。

访谈对话原文 (可用来补全遗漏的细节):
{conv}

访谈中收集到的原始信息 (JSON):
{json.dumps(collected, ensure_ascii=False, indent=2) or "{}"}

要求:
- 只依据对话与收集到的信息, 不要编造。
- 缺失的字段给空值/空数组。
- skills 里保留所有提到的技能 (可能很杂); skill_notes 里写技能熟练度与使用场景的总结。
- 规范输出完整 JSON 对象。"""

        # 规范化输出可能较长, 使用更大 max_tokens 的客户端
        normalize_llm = LLMClient(max_tokens=8000)
        try:
            result = await normalize_llm.generate_structured_response(
                prompt,
                UserProfile,
                system_prompt="你是结构化信息整理专家。输出必须是合法的 UserProfile JSON。",
            )
            return result
        except Exception as e:
            logger.error(f"画像规范化失败, 使用宽松回退: {e}")
            # 宽松回退: 直接尝试用已有 collected 构造
            return UserProfile.model_validate({
                "name": collected.get("name", ""),
                "email": collected.get("email", ""),
                "phone": collected.get("phone", ""),
                "all_skills": collected.get("skills", []) or [],
                "skill_notes": collected.get("skill_notes", ""),
                "target_hint": collected.get("target_hint", ""),
                "locations": collected.get("locations", []) or [],
                "industries_interest": collected.get("industries", []) or [],
                "salary_expectation": collected.get("salary", ""),
                "work_type": collected.get("work_type", ""),
                "deal_breakers": collected.get("deal_breakers", []) or [],
                "certificates": collected.get("certificates", []) or [],
                "languages": collected.get("languages", []) or [],
            })
