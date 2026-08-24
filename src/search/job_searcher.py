"""
JobSearcher - 搜索层薄封装

组合 SearchPipeline，为 AgentOrchestrator 提供 search_jobs(persona) 接口。
负责把 DynamicUserPersona 转换为 TargetInstructionSchema + ResumeSchema，
并把 SearchResult 归一化为职位字典列表。
"""

import os
from typing import Dict, List, Any

from loguru import logger

from src.models.instruction_schemas import TargetInstructionSchema
from src.models.schemas import ResumeSchema
from src.search.search_pipeline import SearchPipeline


class JobSearcher:
    """职位搜索器"""

    def __init__(self, config: Dict[str, Any] = None):
        config = config or {}

        # 兼容两种配置形态：顶层 config 或 search 段
        self.tavily_api_key = (
            config.get("tavily_api_key")
            or (config.get("search") or {}).get("tavily_api_key")
            or os.getenv("TAVILY_API_KEY")
            or ""
        )
        self.openai_api_key = (
            config.get("openai_api_key")
            or (config.get("llm") or {}).get("api_key")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
        self.base_url = (
            (config.get("llm") or {}).get("base_url")
            or os.getenv("OPENAI_BASE_URL")
            or None
        )
        self.llm_model = (
            (config.get("llm") or {}).get("model")
            or os.getenv("OPENAI_MODEL")
            or None
        )

        self.pipeline = SearchPipeline(
            self.tavily_api_key,
            self.openai_api_key,
            base_url=self.base_url,
            model=self.llm_model,
        )

    async def search_jobs(self, persona) -> List[Dict]:
        """
        根据用户画像搜索职位

        Args:
            persona: DynamicUserPersona 用户画像

        Returns:
            职位字典列表，每个包含 url/title/description/match_result/match_score
        """
        target_info, resume = self._build_search_inputs(persona)
        logger.info(
            f"开始职位搜索: {target_info.role}"
            f" ({target_info.location or '不限地点'})"
        )

        results = await self.pipeline.run_search_pipeline(target_info, resume)

        jobs = []
        for r in results:
            jobs.append({
                "url": r.url,
                "title": r.title,
                "description": r.match_result.match_summary or r.title,
                "match_result": r.match_result,
                "match_score": r.match_result.score,
            })

        logger.info(f"JobSearcher 搜索完成，返回 {len(jobs)} 个职位")
        return jobs

    def _build_search_inputs(self, persona) -> tuple:
        """把用户画像转换为搜索管道需要的输入"""
        objective = persona.career_objective
        target_positions = objective.target_positions or ["软件工程师"]
        locations = objective.location_preference or []
        skills = list(persona.technical_skills or [])

        target_info = TargetInstructionSchema(
            company="",  # 未指定公司，全局搜索
            role=target_positions[0],
            location=locations[0] if locations else None,
            keywords=skills,
        )

        resume = ResumeSchema(
            name=persona.name,
            email=persona.email,
            phone=persona.phone,
            summary=f"求职目标: {'、'.join(target_positions)}",
            skills=skills,
            work_experience=[],
            education=[],
            projects=[],
        )

        return target_info, resume
