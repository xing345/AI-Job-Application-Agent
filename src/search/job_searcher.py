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
from src.search.query_expander import expand_role_variants, infer_direction
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
        llm_cfg = config.get("llm") or {}
        use_browser = bool(search_cfg.get("use_browser", True))
        use_company_sites = bool(search_cfg.get("use_company_sites", True))
        max_companies = int(search_cfg.get("max_companies", 5))
        target_companies = search_cfg.get("target_companies") or None
        browser_headless = bool(browser_cfg.get("headless", True))
        # 进入 JD 阶段的候选上限、最终返回岗位上限（可在 config.search 调整）
        jd_fetch_limit = int(search_cfg.get("jd_fetch_limit", 40))
        max_final_results = int(search_cfg.get("max_results_per_search", 15))
        # 默认按官网类别+列表遍历找岗；use_tavily_search=true 才额外开关键词搜索
        use_tavily_search = bool(search_cfg.get("use_tavily_search", False))
        # 招聘类型：默认只找校招（campus），可在 config.search.recruit_type 改为 social/all
        self.recruit_type = (search_cfg.get("recruit_type") or "campus").strip().lower()

        # 找岗/抓 JD 的成本上限（全部可配置，避免「为多抓岗位而无上限地抓」）
        max_jobs_per_site = int(search_cfg.get("max_jobs_per_site", 25))
        max_list_pages = int(search_cfg.get("max_list_pages", 4))
        max_card_clicks = int(search_cfg.get("max_card_clicks", 16))
        max_api_objects = int(search_cfg.get("max_api_objects", 200))
        jd_concurrency = int(search_cfg.get("jd_concurrency", 3))
        # 默认关闭站内关键词搜索：按官网类别 + 列表遍历找岗
        portal_keyword_search = bool(search_cfg.get("portal_keyword_search", False))

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
            jd_fetch_limit=jd_fetch_limit,
            max_final_results=max_final_results,
            use_tavily_search=use_tavily_search,
            max_jobs_per_site=max_jobs_per_site,
            max_list_pages=max_list_pages,
            max_card_clicks=max_card_clicks,
            max_api_objects=max_api_objects,
            jd_concurrency=jd_concurrency,
            portal_keyword_search=portal_keyword_search,
            nav_advisor_config=search_cfg.get("nav_advisor") or {},
            llm_config=llm_cfg,
            browser_config=browser_cfg,
        )
        logger.info(
            f"找岗成本上限: 每站最多 {max_jobs_per_site} 个岗位/翻 {max_list_pages} 页/"
            f"点 {max_card_clicks} 张卡片/认 {max_api_objects} 条接口职位，"
            f"JD 抓取 {jd_fetch_limit} 个（并发 {jd_concurrency}），"
            f"最终返回 {max_final_results} 个"
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
        primary_role = target_positions[0]
        role_variants = expand_role_variants(primary_role, skills)

        # 模糊方向 -> 岗位大类/标题词族（纯规则、零 API 成本），
        # 下传给浏览器阶段：只看职位标题就能判断与目标方向是否相关
        direction = infer_direction(primary_role, skills)
        # 相关性词集 = 方向词族（已并集）∪ 岗位名变体 ∪ 角色本身：
        # 这样「Web前端开发」「React开发」这类与目标同义的岗位名也判相关，不会被丢掉
        title_kws = list(dict.fromkeys(
            list(direction["title_keywords"]) + list(role_variants) + [primary_role]
        ))
        logger.info(
            f"方向推断: 「{primary_role}」-> {direction['category']}/{direction['label']}"
            f"（标题相关词集 {len(title_kws)} 个 = 方向词族 + 岗位变体）"
        )

        target_info = TargetInstructionSchema(
            company="",  # 未指定公司，全局搜索
            role=primary_role,
            location=locations[0] if locations else None,
            keywords=skills,
            role_variants=role_variants,
            direction_family=direction["key"],
            direction_category=direction["category"],
            title_keywords=title_kws,
            recruit_type=self.recruit_type,
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
