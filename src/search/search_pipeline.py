"""
搜索管道主测试脚本
集成职位搜索、JD 抓取和匹配评估，输出经过筛选的合格投递 URL 队列
"""

import asyncio
import time
from typing import List, Dict, Any
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


@dataclass
class SearchResult:
    """搜索结果数据类"""
    url: str
    title: str
    match_result: MatchResultSchema
    matched_at: float

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

    def __init__(self, tavily_api_key: str, openai_api_key: str):
        # 初始化组件
        self.job_finder = JobFinder(JobFinderConfig(api_key=tavily_api_key))
        self.job_matcher = JobMatcher(JobMatcherConfig())

        # 配置日志
        logger.add("search_pipeline.log", rotation="10 MB")

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
        job_urls = await self.job_finder.find_job_portals(target_info)
        logger.info(f"找到 {len(job_urls)} 个招聘页面")

        if not job_urls:
            logger.warning("未找到任何招聘页面")
            return []

        # 第二阶段：抓取 JD
        logger.info("第二阶段：抓取 JD 内容...")
        jd_results = await self._batch_fetch_jd(job_urls[:20])  # 限制抓取数量

        # 第三阶段：匹配评估
        logger.info("第三阶段：进行匹配评估...")
        match_results = await self._batch_evaluate_match(
            {url: jd for url, jd in jd_results.items() if jd},
            resume
        )

        # 第四阶段：筛选和排序
        logger.info("第四阶段：筛选和排序结果...")
        final_results = self._filter_and_sort_results(match_results, min_score, max_results)

        end_time = time.time()
        logger.info(f"搜索管道完成，耗时: {end_time - start_time:.2f} 秒")

        return final_results

    async def _batch_fetch_jd(self, urls: List[str]) -> Dict[str, str]:
        """批量抓取 JD 内容"""
        from concurrent.futures import ThreadPoolExecutor

        jd_results = {}

        async def fetch_single_jd(url: str):
            logger.debug(f"正在抓取 JD: {url}")
            jd_text = await self.job_matcher.fetch_jd_text(url)
            return url, jd_text

        # 使用并发抓取提高效率
        with ThreadPoolExecutor(max_workers=5) as executor:
            loop = asyncio.get_event_loop()
            tasks = []
            for url in urls:
                task = loop.run_in_executor(executor, lambda u: asyncio.run(fetch_single_jd(u)), url)
                tasks.append(task)

            results = await asyncio.gather(*tasks)

        for url, jd_text in results:
            jd_results[url] = jd_text

        return jd_results

    async def _batch_evaluate_match(
        self,
        jd_data: Dict[str, str],
        resume: ResumeSchema
    ) -> Dict[str, MatchResultSchema]:
        """批量进行匹配评估"""
        match_results = {}

        # 使用并发评估提高效率
        tasks = []
        for url, jd_text in jd_data.items():
            if jd_text and len(jd_text) > 100:  # 只评估有效的 JD
                task = self._evaluate_single_match(url, resume, jd_text)
                tasks.append(task)

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
        max_results: int
    ) -> List[SearchResult]:
        """筛选和排序结果"""
        # 转换为 SearchResult 对象
        search_results = []
        for url, match_result in match_results.items():
            search_result = SearchResult(
                url=url,
                title=f"职位申请 - {match_result.match_summary}",
                match_result=match_result,
                matched_at=time.time()
            )
            search_results.append(search_result)

        # 筛选合格结果
        qualified_results = [
            result for result in search_results
            if result.is_qualified and result.match_result.score >= min_score
        ]

        # 按优先级排序
        qualified_results.sort(
            key=lambda x: (x.get_priority_score(), x.match_result.score),
            reverse=True
        )

        # 限制结果数量
        return qualified_results[:max_results]

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

        for i, result in enumerate(results, 1):
            report += f"""
{i}. {result.title}
   URL: {result.url}
   匹配分数: {result.match_result.score}/100
   优先级评分: {result.get_priority_score()}
   是否匹配: {"是" if result.is_qualified else "否"}
   匹配原因: {", ".join(result.match_result.reasons[:3])}
   已匹配技能: {", ".join(result.match_result.matched_skills[:5])}
"""

        if results and len(results[0].match_result.missing_skills) > 0:
            report += f"""
建议补充的技能: {", ".join(results[0].match_result.missing_skills[:10])}
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
            url="https://boards.greenhouse.io/bytedance/jobs/12345",
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
            url="https://lever.co/bytedance/jobs/67890",
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
            url="https://boards.greenhouse.io/bytedance/jobs/11111",
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