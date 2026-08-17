"""
职位搜索器模块
使用 Tavily API 搜索目标公司/职位的招聘页面
"""

import asyncio
import re
from typing import List, Optional
from datetime import datetime
import httpx
from tavily import TavilyClient

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from src.models.instruction_schemas import TargetInstructionSchema


class JobFinderConfig:
    """搜索器配置"""
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = TavilyClient(api_key=api_key)
        self.timeout = 30
        self.max_results = 20
        self.supported_domains = [
            "greenhouse.io",
            "lever.co",
            "myworkdayjobs.com",
            "ashbyhq.com",
            "recruitee.com",
            "careers.smartrecruiters.com",
            "jobapply.novartis.com"
        ]


class JobSearchResult:
    """搜索结果"""
    def __init__(self, url: str, title: str, description: str, source: str):
        self.url = url
        self.title = title
        self.description = description
        self.source = source
        self.created_at = datetime.now()


class JobFinder:
    """职位搜索器"""

    def __init__(self, config: JobFinderConfig):
        self.config = config

    async def find_job_portals(self, target_info: TargetInstructionSchema) -> List[str]:
        """
        查找目标公司的招聘页面 URL

        Args:
            target_info: 目标指令信息

        Returns:
            List[str]: 招聘页面 URL 列表
        """
        try:
            # 构造搜索查询
            query = self._build_search_query(target_info)

            # 使用 Tavily API 搜索
            results = await self._search_with_tavily(query)

            # 过滤和提取招聘页面
            job_urls = self._extract_job_urls(results, target_info)

            # 去重并排序
            unique_urls = list(set(job_urls))
            unique_urls.sort(key=self._sort_key)

            return unique_urls[:self.config.max_results]

        except Exception as e:
            print(f"搜索过程中发生错误: {e}")
            return []

    def _build_search_query(self, target_info: TargetInstructionSchema) -> str:
        """构造搜索查询"""
        # 构建基础查询
        base_query = f"{target_info.company} {target_info.role}"

        # 添加关键词
        if target_info.keywords:
            base_query += f" {' '.join(target_info.keywords)}"

        # 构建网站限定查询
        site_conditions = []
        for domain in self.config.supported_domains:
            site_conditions.append(f"site:{domain}")

        # 组合完整查询
        if target_info.remote_only:
            base_query += " remote work"

        if target_info.exclude_keywords:
            exclude_terms = ' '.join(target_info.exclude_keywords)
            exclude_query = f" -{exclude_terms}"
            return f"{' OR '.join(site_conditions)} {base_query}{exclude_query}"
        else:
            return f"{' OR '.join(site_conditions)} {base_query}"

    async def _search_with_tavily(self, query: str) -> dict:
        """使用 Tavily API 搜索"""
        try:
            # 异步 HTTP 请求
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "query": query,
                        "max_results": self.config.max_results
                    }
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            print(f"Tavily API 搜索失败: {e}")
            return {"results": []}

    def _extract_job_urls(self, search_results: dict, target_info: TargetInstructionSchema) -> List[str]:
        """从搜索结果中提取招聘页面 URL"""
        urls = []

        if "results" not in search_results:
            return urls

        for result in search_results["results"]:
            url = result.get("url", "")
            title = result.get("title", "").lower()
            description = result.get("snippet", "").lower()

            # 检查是否为招聘页面
            if self._is_job_page(url, title, description, target_info):
                urls.append(url)
                print(f"找到招聘页面: {url}")

        return urls

    def _is_job_page(self, url: str, title: str, description: str, target_info: TargetInstructionSchema) -> bool:
        """判断是否为招聘页面"""
        # 检查 URL 中的域名
        if not any(domain in url for domain in self.config.supported_domains):
            return False

        # 检查标题和描述中是否包含关键词
        company_lower = target_info.company.lower()
        role_lower = target_info.role.lower()

        # 必须包含公司名称
        if company_lower not in title and company_lower not in description:
            return False

        # 必须包含职位名称
        if role_lower not in title and role_lower not in description:
            return False

        # 排除一些非招聘相关的页面
        exclude_patterns = [
            "blog",
            "news",
            "about",
            "contact",
            "privacy",
            "terms",
            "legal",
            "investor",
            "press"
        ]

        for pattern in exclude_patterns:
            if pattern in url:
                return False

        return True

    def _sort_key(self, url: str) -> int:
        """URL 排序键"""
        # 按域名优先级排序
        domain_priority = {
            "greenhouse.io": 0,
            "lever.co": 1,
            "myworkdayjobs.com": 2,
            "ashbyhq.com": 3,
            "recruitee.com": 4,
            "careers.smartrecruiters.com": 5,
            "jobapply.novartis.com": 6
        }

        for domain in domain_priority:
            if domain in url:
                return domain_priority[domain]

        return 999


async def test_job_finder():
    """测试函数"""
    # 创建配置
    config = JobFinderConfig(api_key="your_tavily_api_key_here")
    finder = JobFinder(config)

    # 创建目标指令
    target_info = TargetInstructionSchema(
        company="字节跳动",
        role="前端工程师",
        location="北京",
        keywords=["React", "TypeScript"],
        posted_days_ago=30
    )

    # 执行搜索
    print(f"正在搜索 {target_info.company} 的 {target_info.role} 职位...")
    job_urls = await finder.find_job_portals(target_info)

    print(f"\n找到 {len(job_urls)} 个招聘页面:")
    for i, url in enumerate(job_urls, 1):
        print(f"{i}. {url}")


if __name__ == "__main__":
    asyncio.run(test_job_finder())