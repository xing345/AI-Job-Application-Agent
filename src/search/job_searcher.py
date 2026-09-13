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
from src.search.query_expander import expand_role_variants
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

        search_cfg = config.get("search") or {}
        browser_cfg = config.get("browser") or {}
        use_browser = bool(search_cfg.get("use_browser", True))
        use_company_sites = bool(search_cfg.get("use_company_sites", True))
        max_companies = int(search_cfg.get("max_companies", 5))
        target_companies = search_cfg.get("target_companies") or None
        browser_headless = bool(browser_cfg.get("headless", True))

        self.pipeline = SearchPipeline(
            self.tavily_api_key,
            self.openai_api_key,
            base_url=self.base_url,
            model=self.llm_model,
            use_browser=use_browser,
            headless=browser_headless,
            interactive=True,
            use_company_sites=use_company_sites,
            max_companies=max_companies,
            target_companies=target_companies,
        )

    def set_target_companies(self, companies: List[str] = None) -> None:
        """运行时更新目标公司名单（搜索前由 Agent 询问用户后调用）"""
        self.pipeline.set_target_companies(companies)

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
                # False = 本轮没有达标岗位时降级返回的「最接近岗位」
                "above_threshold": r.above_threshold,
            })

        degraded = sum(1 for j in jobs if not j["above_threshold"])
        logger.info(
            f"JobSearcher 搜索完成，返回 {len(jobs)} 个职位"
            + (f"（其中 {degraded} 个未达门槛）" if degraded else "")
        )
        return jobs

    def _build_search_inputs(self, persona) -> tuple:
        """把用户画像转换为搜索管道需要的输入（兼容 DynamicUserPersona 模型与 dict）"""
        if isinstance(persona, dict):
            name = persona.get("name") or ""
            email = persona.get("email") or ""
            phone = persona.get("phone")
            objective = persona.get("career_objective") or {}
            target_positions = objective.get("target_positions") or ["软件工程师"]
            locations = objective.get("location_preference") or []
            raw_skills = persona.get("technical_skills") or {}
        else:
            name = persona.name
            email = persona.email
            phone = persona.phone
            objective = persona.career_objective
            target_positions = objective.target_positions or ["软件工程师"]
            locations = objective.location_preference or []
            raw_skills = persona.technical_skills or {}

        # technical_skills 契约: dict[类别 -> 技能列表]; 兼容旧 list 数据
        if isinstance(raw_skills, dict):
            skills = [
                s for values in raw_skills.values()
                for s in (values or []) if isinstance(s, str)
            ]
        else:
            skills = [s for s in raw_skills if isinstance(s, str)]
        skills = list(dict.fromkeys(skills))

        # 岗位名扩展出近义变体，避免「前端工程师」搜不到「Web前端开发」这类岗位
        role_variants = expand_role_variants(target_positions[0], skills)

        target_info = TargetInstructionSchema(
            company="",  # 未指定公司，全局搜索
            role=target_positions[0],
            location=locations[0] if locations else None,
            keywords=skills,
            role_variants=role_variants,
        )

        resume = ResumeSchema(
            name=name,
            email=email,
            phone=phone,
            summary=f"求职目标: {'、'.join(target_positions)}",
            skills=skills,
            work_experience=[],
            education=[],
            projects=[],
        )

        return target_info, resume
