"""
职位搜索器模块
使用 Tavily API 搜索目标公司/职位的招聘页面
"""

import asyncio
from typing import List
from datetime import datetime
from tavily import TavilyClient

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from src.models.instruction_schemas import TargetInstructionSchema
from src.search.query_expander import matches_role, query_terms

# 国内招聘平台（排序优先级：越靠前越优先）
CN_PLATFORM_PRIORITY = [
    "bosszhipin.com", "zhipin.com", "lagou.com", "liepin.com",
    "zhaopin.com", "51job.com",
]

# 非招聘性质的站点（内容站/百科/社媒/应用商店/电商/海外聚合站），命中即排除
NOISE_DOMAINS = [
    "wikipedia", "baike", "wiki", "zhihu.com", "csdn.net", "jianshu.com",
    "juejin.cn", "cnblogs", "segmentfault", "bilibili.com", "weibo.com",
    "douban.com", "xiaohongshu.com", "youtube.com", "play.google.com",
    "apps.apple.com", "taobao.com", "jd.com", "amazon.",
    "tianyancha.com", "qcc.com", "kanzhun.com",
    "glassdoor", "indeed.com", "linkedin.com",
]

# 非招聘页面路径特征（新闻/博客/帮助/法务等）
EXCLUDE_URL_PATTERNS = [
    "/blog", "/news", "/about", "/contact", "/privacy", "/terms",
    "/legal", "/investor", "/press", "/help", "/support",
]


class JobFinderConfig:
    """搜索器配置"""
    def __init__(self, api_key: str):
        self.api_key = api_key or ""
        self._client = None  # 惰性创建, 避免空 key 时构造即报错
        self.timeout = 30
        self.max_results = 20

    @property
    def client(self) -> TavilyClient:
        if self._client is None:
            self._client = TavilyClient(api_key=self.api_key)
        return self._client


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

            # 去重并排序（dict.fromkeys 保序，避免 set 迭代顺序不稳定导致结果不可复现）
            unique_urls = list(dict.fromkeys(job_urls))
            unique_urls.sort(key=self._sort_key)

            return unique_urls[:self.config.max_results]

        except Exception as e:
            print(f"搜索过程中发生错误: {e}")
            return []

    def _build_search_query(self, target_info: TargetInstructionSchema) -> str:
        """
        构造搜索查询

        不再用 site: 白名单锁死域名——那套只覆盖海外 ATS，国内岗位必然搜不到。
        改为自然语言查询，由 _is_job_page 负责把噪声站点挡在后面。
        """
        parts: List[str] = []
        if target_info.company:
            parts.append(target_info.company)
        # 主岗位名 + 同义变体，扩大召回
        parts.extend(query_terms(target_info, limit=2))
        if target_info.location:
            parts.append(target_info.location)
        parts.append("招聘")

        # 添加关键词
        if target_info.keywords:
            parts.append(" ".join(str(k) for k in target_info.keywords))

        query = " ".join(p for p in parts if p)

        if target_info.remote_only:
            query += " 远程"

        if target_info.exclude_keywords:
            exclude_terms = ' '.join(str(k) for k in target_info.exclude_keywords)
            query += f" -{exclude_terms}"

        return query

    async def _search_with_tavily(self, query: str) -> dict:
        """使用 Tavily API 搜索（带 API key 鉴权；TavilyClient 为同步实现，用线程隔离避免阻塞事件循环）"""
        try:
            if not self.config.api_key:
                print("未配置 TAVILY_API_KEY（请在 .env 中设置），已跳过 Tavily 搜索")
                return {"results": []}

            result = await asyncio.to_thread(
                self.config.client.search,
                query=query,
                search_depth="basic",
                max_results=self.config.max_results,
                include_answer=False,
                include_raw_content=False,
            )
            return result if isinstance(result, dict) else {"results": []}

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
        """
        判断是否为可投递的招聘页面

        域名不做白名单（那套只认海外 ATS），改为「命中噪声站点才拦」；
        岗位名改为模糊匹配：变体整串命中或 token 命中即可，不再要求一字不差。
        """
        url_lower = (url or "").lower()
        if not url_lower.startswith("http"):
            return False

        # 排除非招聘性质的站点与页面
        if any(d in url_lower for d in NOISE_DOMAINS):
            return False
        if any(p in url_lower for p in EXCLUDE_URL_PATTERNS):
            return False

        title = (title or "").lower()
        description = (description or "").lower()

        # 若指定了公司名，标题/描述/域名至少一处出现
        company_lower = (target_info.company or "").strip().lower()
        if company_lower and company_lower not in title \
                and company_lower not in description and company_lower not in url_lower:
            return False

        # 若指定了职位名，模糊命中即可（字段为空时不做该限定，避免必然过滤掉所有结果）
        role = (target_info.role or "").strip()
        if role:
            blob = f"{title} {description} {url_lower}"
            if not matches_role(
                blob, role,
                getattr(target_info, "role_variants", None),
                target_info.keywords,
            ):
                return False

        return True

    def _sort_key(self, url: str) -> int:
        """URL 排序键：国内招聘平台优先，其余（含公司自有招聘站）排后面"""
        u = (url or "").lower()
        for i, domain in enumerate(CN_PLATFORM_PRIORITY):
            if domain in u:
                return i
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