"""
搜索管道主测试脚本
集成职位搜索、JD 抓取和匹配评估，输出经过筛选的合格投递 URL 队列
"""

import asyncio
import time
from typing import List, Dict
from dataclasses import dataclass
from loguru import logger

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from src.models.instruction_schemas import TargetInstructionSchema
from src.models.schemas import ResumeSchema, WorkExperience, Education
from src.search.job_finder import JobFinder, JobFinderConfig
from src.search.job_matcher import JobMatcher, JobMatcherConfig, MatchResultSchema
from src.search.browser_job_finder import BrowserJobFinder


@dataclass
class SearchResult:
    """搜索结果数据类"""
    url: str
    title: str
    match_result: MatchResultSchema
    matched_at: float
    # 是否达到了本轮的最低分门槛。False 表示这是「降级返回」的结果：
    # 一个达标的都没有时，宁可把最接近的几个岗位标出来，也不返回空列表
    above_threshold: bool = True

    @property
    def is_qualified(self) -> bool:
        """是否为合格投递目标"""
        return self.match_result.score >= 60  # 分数 >= 60 认为基本匹配

    def get_priority_score(self) -> int:
        """获取优先级分数"""
        # 基础分数
        base_score = self.match_result.score

        # 根据匹配技能数量调整
        skill_bonus = len(self.match_result.matched_skills) * 2

        # 根据缺少技能数量扣分
        skill_penalty = len(self.match_result.missing_skills) * 5

        # 总分
        total_score = base_score + skill_bonus - skill_penalty

        return max(0, total_score)


class SearchPipeline:
    """搜索管道"""

    def __init__(
        self,
        tavily_api_key: str,
        openai_api_key: str,
        base_url: str = None,
        model: str = None,
        use_browser: bool = True,
        headless: bool = True,
        interactive: bool = True,
        use_company_sites: bool = True,
        max_companies: int = 5,
        target_companies: List[str] = None
    ):
        # 初始化组件
        self.job_finder = JobFinder(JobFinderConfig(api_key=tavily_api_key))
        self.job_matcher = JobMatcher(
            JobMatcherConfig(openai_api_key=openai_api_key, base_url=base_url, model=model)
        )

        # 真实浏览器职位发现器（方案B：开浏览器遍历招聘站抽取职位链接）
        self.use_browser = use_browser
        # 公司自有招聘官网通道
        self.use_company_sites = use_company_sites and use_browser
        self.target_companies = target_companies or None
        self.max_companies = max_companies
        self.jd_concurrency = 5  # JD 抓取并发上限
        self.browser_finder = (
            BrowserJobFinder(
                tavily_api_key=tavily_api_key,
                headless=headless,
                interactive=interactive,
                max_companies=max_companies,
            )
            if use_browser else None
        )

        # 配置日志
        logger.add("search_pipeline.log", rotation="10 MB")

    def set_target_companies(self, companies: List[str] = None) -> None:
        """运行时更新目标公司名单（搜索前用户指定），无需重建整条管道"""
        self.target_companies = [c for c in (companies or []) if c and c.strip()] or None
        logger.info(
            f"目标公司已更新: {self.target_companies or '不限（按岗位自动发现）'}"
        )

    async def run_search_pipeline(
        self,
        target_info: TargetInstructionSchema,
        resume: ResumeSchema,
        min_score: int = 60,
        max_results: int = 10
    ) -> List[SearchResult]:
        """
        运行完整的搜索管道

        Args:
            target_info: 目标指令
            resume: 简历数据
            min_score: 最低匹配分数
            max_results: 最大返回结果数

        Returns:
            List[SearchResult]: 经过筛选的搜索结果列表
        """
        start_time = time.time()
        logger.info(f"开始搜索管道: {target_info.company} - {target_info.role}")

        # 第一阶段：搜索职位
        logger.info("第一阶段：搜索职位...")
        job_items = await self._discover_job_urls(target_info)
        logger.info(f"找到 {len(job_items)} 个招聘页面")

        if not job_items:
            logger.warning("未找到任何招聘页面")
            return []

        # 每个通道各发现了多少，出问题时能一眼看出卡在哪
        self._log_channel_stats(job_items)

        # 第二阶段：抓取 JD
        logger.info("第二阶段：抓取 JD 内容...")
        fetch_items = job_items[:20]  # 限制抓取数量
        jd_results = await self._batch_fetch_jd(fetch_items)

        # 第三阶段：匹配评估
        logger.info("第三阶段：进行匹配评估...")
        match_results = await self._batch_evaluate_match(jd_results, resume, fetch_items)

        if not match_results:
            logger.warning("所有候选页面均无法评估（抓取失败且无标题可用）")
            return []

        # 第四阶段：筛选和排序
        logger.info("第四阶段：筛选和排序结果...")
        final_results = self._filter_and_sort_results(match_results, min_score, max_results, fetch_items)

        end_time = time.time()
        logger.info(
            f"搜索管道完成，耗时: {end_time - start_time:.2f} 秒，"
            f"评估 {len(match_results)} 个岗位，返回 {len(final_results)} 个"
            f"（其中 {sum(1 for r in final_results if not r.above_threshold)} 个未达门槛）"
        )

        return final_results

    @staticmethod
    def _log_channel_stats(job_items: List[Dict]) -> None:
        """按通道统计发现数量，便于定位「搜不到」卡在哪一步"""
        stats: Dict[str, int] = {}
        for item in job_items:
            channel = item.get("channel") or "unknown"
            stats[channel] = stats.get(channel, 0) + 1
        if stats:
            detail = "、".join(f"{k}={v}" for k, v in stats.items())
            logger.info(f"各通道发现职位数: {detail}")

    async def _discover_job_urls(self, target_info: TargetInstructionSchema) -> List[Dict]:
        """
        三通道职位发现：通道0 公司自有招聘官网 / 通道2 浏览器招聘门户 / 通道1 Tavily

        Returns:
            [{"url", "title", "company", "channel"}]，保序去重（公司官网优先）。
            保留标题是为了在后面对 JD 抓取失败时还能用标题兜底评估，而不是直接丢弃岗位。
        """
        merged: List[Dict] = []
        seen = set()

        def merge(items: List[Dict], channel: str):
            for item in items or []:
                url = (item or {}).get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                item.setdefault("channel", channel)
                merged.append(item)

        # 通道0：进入公司自有招聘官网找岗
        if self.use_company_sites and self.browser_finder:
            logger.info("通道0：进入公司自有招聘官网找岗...")
            try:
                company_jobs = await self.browser_finder.discover_company_careers(
                    target_info, known_companies=self.target_companies
                )
                merge(company_jobs, "company_site")
                logger.info(f"公司官网通道发现 {len(company_jobs)} 个职位链接")
            except Exception as e:
                logger.error(f"公司官网通道失败，继续后续通道: {e}")

        # 通道2：真实浏览器遍历招聘站
        if self.use_browser and self.browser_finder:
            logger.info("通道2：真实浏览器遍历招聘站找岗...")
            try:
                browser_jobs = await self.browser_finder.discover(target_info)
                merge(browser_jobs, "job_portal")
                logger.info(f"浏览器通道发现 {len(browser_jobs)} 个职位链接")
            except Exception as e:
                logger.error(f"浏览器找岗失败，回退到 Tavily 通道: {e}")

        # 通道1：Tavily 搜索
        logger.info("通道1：Tavily 搜索招聘页面...")
        tavily_urls = await self.job_finder.find_job_portals(target_info)
        merge([{"url": u, "title": "", "company": ""} for u in tavily_urls], "tavily")
        logger.info(f"Tavily 通道发现 {len(tavily_urls)} 个招聘页面")

        return merged

    async def _batch_fetch_jd(self, items: List[Dict]) -> Dict[str, str]:
        """
        批量抓取 JD 内容

        交给 JobMatcher 的批量接口，复用同一个浏览器实例并限制并发；
        抓取失败的返回空串，由 _batch_evaluate_match 用职位标题兜底。
        """
        # XHR 接口已带回完整 JD（SPA 站点）时直接使用，不再渲染详情页（常抓空）
        prefetched = {
            it["url"]: (it.get("description") or "")
            for it in items
            if it.get("url") and len(it.get("description") or "") >= 100
        }
        urls = [it["url"] for it in items if it.get("url") and it["url"] not in prefetched]
        if not urls:
            return prefetched
        fetched = await self.job_matcher.fetch_jd_texts(
            urls, concurrency=self.jd_concurrency
        )
        fetched.update(prefetched)
        return fetched

    @staticmethod
    def _weak_jd(title: str, url: str) -> str:
        """JD 抓取失败时的兜底文本：至少让真实岗位带着标题进入评估"""
        if not title:
            return ""
        return (
            f"职位名称: {title}\n来源链接: {url}\n"
            "（未能抓取到职位正文，仅依据标题判断岗位相关性）"
        )

    async def _batch_evaluate_match(
        self,
        jd_data: Dict[str, str],
        resume: ResumeSchema,
        items: List[Dict] = None,
    ) -> Dict[str, MatchResultSchema]:
        """批量进行匹配评估（JD 过短/抓取失败时回退用职位标题，不再直接丢掉岗位）"""
        titles = {
            it["url"]: (it.get("title") or "")
            for it in (items or []) if it.get("url")
        }

        match_results = {}
        tasks = []
        for url, jd_text in jd_data.items():
            text = jd_text if (jd_text and len(jd_text) > 100) else \
                self._weak_jd(titles.get(url, ""), url)
            if not text:
                logger.debug(f"跳过无法评估的页面（无 JD 且无标题）: {url}")
                continue
            tasks.append(self._evaluate_single_match(url, resume, text))

        if tasks:
            results = await asyncio.gather(*tasks)
            for url, result in results:
                match_results[url] = result

        return match_results

    async def _evaluate_single_match(
        self,
        url: str,
        resume: ResumeSchema,
        jd_text: str
    ) -> tuple[str, MatchResultSchema]:
        """评估单个匹配"""
        logger.debug(f"正在评估匹配度: {url}")
        result = await self.job_matcher.evaluate_match(resume, jd_text)
        return url, result

    def _filter_and_sort_results(
        self,
        match_results: Dict[str, MatchResultSchema],
        min_score: int,
        max_results: int,
        items: List[Dict] = None,
    ) -> List[SearchResult]:
        """
        筛选和排序结果

        达标结果照常返回；若一个达标的都没有，则降级返回分数最高的 Top-N 并标
        above_threshold=False —— 用户需要看到「最接近的几个岗位 + 实际分数」，
        而不是一个空列表（空列表无法区分「没抓到」和「抓到了但都不合适」）。
        """
        titles = {it.get("url"): (it.get("title") or "") for it in (items or []) if it.get("url")}
        # 转换为 SearchResult 对象（优先用发现阶段抓到的真实职位标题）
        search_results = []
        for url, match_result in match_results.items():
            search_result = SearchResult(
                url=url,
                title=titles.get(url) or f"职位申请 - {match_result.match_summary}",
                match_result=match_result,
                matched_at=time.time(),
                above_threshold=match_result.score >= min_score,
            )
            search_results.append(search_result)

        # 筛选合格结果
        qualified_results = [
            result for result in search_results if result.above_threshold
        ]

        if qualified_results:
            qualified_results.sort(
                key=lambda x: (x.get_priority_score(), x.match_result.score),
                reverse=True
            )
            return qualified_results[:max_results]

        # 降级：全部低于门槛
        degraded = sorted(
            search_results, key=lambda x: x.match_result.score, reverse=True
        )[:max_results]
        if degraded:
            logger.warning(
                f"没有岗位达到 {min_score} 分门槛，降级返回最接近的 "
                f"{len(degraded)} 个岗位（最高 {degraded[0].match_result.score} 分）"
            )
        return degraded

    def generate_report(self, results: List[SearchResult]) -> str:
        """生成搜索报告"""
        if not results:
            return "未找到符合条件的职位。"

        report = f"""
=== 搜索结果报告 ===
总查询职位数: {len(results)}
合格职位数: {len([r for r in results if r.is_qualified])}
最高匹配分数: {max(r.match_result.score for r in results)}

=== 推荐投递目标 ===
"""

        if all(not r.above_threshold for r in results):
            report += "\n⚠️ 本轮没有岗位达到最低分门槛，以下为最接近的岗位（未达门槛）\n"

        for i, result in enumerate(results, 1):
            matched = "、".join(result.match_result.matched_skills[:6]) or "无"
            missing = "、".join(result.match_result.missing_skills[:10]) or "无明显差距"
            report += f"""
{i}. {result.title}
   URL: {result.url}
   匹配分数: {result.match_result.score}/100
   优先级评分: {result.get_priority_score()}
   是否匹配: {"是" if result.is_qualified else "否"}
   匹配原因: {", ".join(result.match_result.reasons[:3])}
   已具备技能: {matched}
   欠缺技能: {missing}
"""

        return report


async def test_search_pipeline():
    """测试搜索管道"""
    print("=== 职位搜索管道测试 ===\n")

    # 配置 API 密钥（请替换为您的实际密钥）
    tavily_api_key = "your_tavily_api_key_here"
    openai_api_key = "your_openai_api_key_here"

    # 如果没有配置密钥，使用模拟数据测试
    if tavily_api_key == "your_tavily_api_key_here" or openai_api_key == "your_openai_api_key_here":
        print("⚠️  未配置 API 密钥，使用模拟数据测试...")
        await test_with_mock_data()
        return

    # 创建管道
    pipeline = SearchPipeline(tavily_api_key, openai_api_key)

    # 创建目标指令
    target_info = TargetInstructionSchema(
        company="字节跳动",
        role="前端工程师",
        location="北京",
        keywords=["React", "TypeScript", "Node.js"],
        posted_days_ago=30,
        remote_only=False
    )

    # 创建测试简历
    resume = ResumeSchema(
        name="李明",
        email="liming@example.com",
        phone="13912345678",
        summary="4年前端开发经验，精通 React 生态，具备大型项目开发经验",
        skills=["React", "TypeScript", "JavaScript", "CSS3", "HTML5", "Node.js", "Webpack", "Git"],
        work_experience=[
            WorkExperience(
                company="某互联网公司",
                position="高级前端工程师",
                start_date="2020-03",
                end_date="2024-03",
                description="负责公司核心产品的前端架构设计和开发"
            )
        ],
        education=[
            Education(
                school="清华大学",
                major="软件工程",
                degree="本科",
                start_date="2016-09",
                end_date="2020-06"
            )
        ]
    )

    # 运行搜索管道
    print(f"正在搜索 {target_info.company} 的 {target_info.role} 职位...")
    results = await pipeline.run_search_pipeline(
        target_info=target_info,
        resume=resume,
        min_score=60,
        max_results=5
    )

    # 生成报告
    report = pipeline.generate_report(results)
    print(report)


async def test_with_mock_data():
    """使用模拟数据测试"""
    print("\n=== 模拟数据测试 ===")

    # 模拟搜索结果
    mock_results = [
        SearchResult(
            url="https://jobs.bytedance.com/experienced/position/12345/detail",
            title="字节跳动 - 前端工程师",
            match_result=MatchResultSchema(
                score=85,
                is_match=True,
                reasons=["技能匹配度高", "工作经验充足"],
                matched_skills=["React", "TypeScript", "JavaScript"],
                missing_skills=["Vue.js"],
                match_summary="前端开发职位匹配度高"
            ),
            matched_at=time.time()
        ),
        SearchResult(
            url="https://jobs.bytedance.com/experienced/position/67890/detail",
            title="字节跳动 - 高级前端工程师",
            match_result=MatchResultSchema(
                score=75,
                is_match=True,
                reasons=["匹配较好，但有额外要求"],
                matched_skills=["React", "TypeScript"],
                missing_skills=["Node.js", "Webpack"],
                match_summary="部分匹配，可考虑申请"
            ),
            matched_at=time.time()
        ),
        SearchResult(
            url="https://jobs.bytedance.com/experienced/position/11111/detail",
            title="字节跳动 - Web 开发工程师",
            match_result=MatchResultSchema(
                score=45,
                is_match=False,
                reasons=["技能不够匹配"],
                matched_skills=["CSS", "HTML"],
                missing_skills=["React", "TypeScript", "Vue"],
                match_summary="匹配度较低，不建议申请"
            ),
            matched_at=time.time()
        )
    ]

    # 创建报告
    pipeline = SearchPipeline("", "")
    report = pipeline.generate_report(mock_results)
    print(report)

    # 显示优先级排序
    print("\n=== 按优先级排序 ===")
    sorted_results = sorted(mock_results, key=lambda x: x.get_priority_score(), reverse=True)
    for i, result in enumerate(sorted_results, 1):
        print(f"{i}. {result.title}")
        print(f"   分数: {result.match_result.score} | 优先级: {result.get_priority_score()}")
        print(f"   URL: {result.url}")
        print()


if __name__ == "__main__":
    asyncio.run(test_search_pipeline())
