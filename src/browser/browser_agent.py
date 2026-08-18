"""
浏览器漫游寻址Agent
基于browser-use和Playwright实现智能浏览器操作
"""

import asyncio
import json
import time
from typing import Dict, List, Optional, Any, AsyncGenerator
from datetime import datetime
from pathlib import Path
from loguru import logger

from browser_use.browser_service import BrowserService
from browser_use.browser import Browser
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

# 添加项目根目录到路径
import sys
import os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.utils.llm_client import get_llm_client
from src.models.schemas import BrowserAction


class BrowserState(BaseModel):
    """浏览器状态"""
    url: str = Field(default="", description="当前URL")
    content: str = Field(default="", description="页面内容")
    screenshot: Optional[str] = Field(None, description="页面截图")
    actions: List[BrowserAction] = Field(default_factory=list, description="执行的动作历史")
    current_task: str = Field(default="", description="当前任务")
    error: Optional[str] = Field(None, description="错误信息")
    completed: bool = Field(default=False, description="任务是否完成")
    results: List[Dict] = Field(default_factory=list, description="搜索结果")


class BrowserAgent:
    """浏览器漫游Agent"""

    def __init__(
        self,
        headless: bool = False,
        viewport: tuple = (1280, 720),
        user_agent: str = None
    ):
        """
        初始化浏览器Agent

        Args:
            headless: 是否无头模式
            viewport: 视口大小
            user_agent: 用户代理字符串
        """
        self.headless = headless
        self.viewport = viewport
        self.user_agent = user_agent
        self.browser = None
        self.llm_client = get_llm_client()
        self.state = BrowserState()

    async def start_browser(self):
        """启动浏览器"""
        try:
            logger.info("启动浏览器...")
            browser_service = BrowserService(
                headless=self.headless,
                viewport=self.viewport,
                user_agent=self.user_agent
            )
            self.browser = await browser_service.launch()
            logger.info("浏览器启动成功")
        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            raise

    async def stop_browser(self):
        """停止浏览器"""
        if self.browser:
            await self.browser.close()
            logger.info("浏览器已停止")

    async def navigate_to(self, url: str) -> bool:
        """导航到指定URL"""
        try:
            logger.info(f"导航到: {url}")
            await self.browser.goto(url)
            self.state.url = url

            # 获取页面内容
            content = await self.browser.get_page_content()
            self.state.content = content

            logger.info("页面加载完成")
            return True
        except Exception as e:
            logger.error(f"导航失败: {e}")
            self.state.error = str(e)
            return False

    async def search_companies(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        搜索公司信息

        Args:
            query: 搜索查询
            max_results: 最大结果数

        Returns:
            公司信息列表
        """
        self.state.current_task = f"搜索公司: {query}"
        logger.info(f"开始搜索公司: {query}")

        # 使用Tavily API搜索
        try:
            import httpx

            tavily_key = os.getenv("TAVILY_API_KEY")
            if not tavily_key:
                logger.error("未找到TAVILY_API_KEY")
                return []

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "query": f"{query} 公司官网",
                        "max_results": max_results,
                        "timeout": 10
                    },
                    headers={"Authorization": f"Bearer {tavily_key}"}
                )

                if response.status_code == 200:
                    data = response.json()
                    results = []
                    for item in data.get("results", [])[:5]:  # 只取前5个结果
                        if "tavily.com" not in item.get("url", ""):
                            results.append({
                                "title": item.get("title", ""),
                                "url": item.get("url", ""),
                                "content": item.get("content", "")[:500]
                            })

                    self.state.results = results
                    logger.info(f"找到 {len(results)} 个公司网站")
                    return results
                else:
                    logger.error(f"搜索失败: {response.status_code}")
                    return []

        except Exception as e:
            logger.error(f"搜索公司失败: {e}")
            return []

    async def find_career_page(self, company_url: str) -> Optional[str]:
        """
        在公司网站上查找招聘页面

        Args:
            company_url: 公司网站URL

        Returns:
            招聘页面URL，如果找不到返回None
        """
        logger.info(f"在 {company_url} 查找招聘页面")

        try:
            # 导航到公司网站
            if not await self.navigate_to(company_url):
                return None

            # 获取页面内容
            content = await self.browser.get_page_content()

            # 使用LLM分析页面内容
            prompt = f"""
            分析当前页面内容，查找招聘/工作/职位相关的链接。

            页面内容：
            {content[:2000]}

            请识别并返回招聘相关的链接URL。如果有多个链接，请列出所有找到的招聘页面URL。
            如果没有找到招聘页面，请返回 "no_career_page"。

            输出格式：
            {{
                "career_pages": ["url1", "url2"],
                "keywords_found": ["招聘", "工作", "职位", "careers", "jobs", "career"]
            }}
            """

            response = await self.llm_client.generate_response(prompt, json_output=True)

            if response.get("career_pages"):
                return response["career_pages"][0]  # 返回第一个找到的招聘页面
            else:
                logger.warning("未找到招聘页面")
                return None

        except Exception as e:
            logger.error(f"查找招聘页面失败: {e}")
            return None

    async def extract_job_listings(self, career_page_url: str) -> List[Dict]:
        """
        提取招聘页面上的职位列表

        Args:
            career_page_url: 招聘页面URL

        Returns:
            职位列表
        """
        logger.info(f"提取职位列表: {career_page_url}")

        try:
            # 导航到招聘页面
            if not await self.navigate_to(career_page_url):
                return []

            # 等待页面加载
            await asyncio.sleep(2)

            # 获取页面内容
            content = await self.browser.get_page_content()

            # 使用LLM分析页面内容，提取职位信息
            prompt = f"""
            从招聘页面中提取所有职位的详细信息。

            页面内容：
            {content[:3000]}

            请提取所有职位信息，包括：
            - 职位名称
            - 公司名称
            - 工作地点
            - 职位描述
            - 申请链接（如果有）

            输出JSON格式：
            {{
                "jobs": [
                    {{
                        "title": "职位名称",
                        "company": "公司名称",
                        "location": "工作地点",
                        "description": "职位描述",
                        "url": "申请链接",
                        "salary": "薪资范围（如果有）",
                        "requirements": ["要求1", "要求2"]
                    }}
                ]
            }}
            """

            response = await self.llm_client.generate_response(prompt, json_output=True)

            jobs = response.get("jobs", [])
            logger.info(f"找到 {len(jobs)} 个职位")

            # 保存结果
            for job in jobs:
                job["source_url"] = career_page_url
                job["extracted_at"] = datetime.now().isoformat()
                job["company_url"] = career_page_url

            self.state.results.extend(jobs)
            return jobs

        except Exception as e:
            logger.error(f"提取职位列表失败: {e}")
            return []

    async def browse_and_search(self, industry: str, companies: List[str]) -> Dict:
        """
        浏览和搜索职位

        Args:
            industry: 行业名称
            companies: 公司列表

        Returns:
            搜索结果
        """
        logger.info(f"开始行业浏览搜索: {industry}")
        logger.info(f"目标公司: {', '.join(companies)}")

        all_jobs = []
        processed_urls = []

        for company in companies:
            try:
                logger.info(f"处理公司: {company}")

                # 1. 搜索公司官网
                search_results = await self.search_companies(f"{company} {industry}", max_results=3)

                if not search_results:
                    logger.warning(f"未找到 {company} 的官网")
                    continue

                # 2. 尝试访问公司官网
                company_url = search_results[0]["url"]
                if company_url in processed_urls:
                    continue
                processed_urls.append(company_url)

                # 3. 查找招聘页面
                career_page = await self.find_career_page(company_url)
                if not career_page:
                    logger.warning(f"未找到 {company} 的招聘页面")
                    continue

                # 4. 提取职位列表
                jobs = await self.extract_job_listings(career_page)
                all_jobs.extend(jobs)

                logger.info(f"从 {company} 提取到 {len(jobs)} 个职位")

                # 添加延迟，避免请求过于频繁
                await asyncio.sleep(3)

            except Exception as e:
                logger.error(f"处理公司 {company} 时出错: {e}")
                continue

        logger.info(f"总共提取到 {len(all_jobs)} 个职位")

        return {
            "industry": industry,
            "companies_searched": companies,
            "total_jobs": len(all_jobs),
            "jobs": all_jobs,
            "searched_urls": processed_urls,
            "timestamp": datetime.now().isoformat()
        }

    async def save_search_results(self, results: Dict, filename: str = None):
        """保存搜索结果"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"browser_search_{timestamp}.json"

        output_path = Path(project_root) / "output" / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        logger.info(f"搜索结果已保存到: {output_path}")
        return output_path


class BrowserSearchGraph:
    """浏览器搜索LangGraph"""

    def __init__(self):
        self.browser_agent = None
        self.llm_client = get_llm_client()

    async def create_graph(self) -> StateGraph:
        """创建浏览器搜索图"""
        from langgraph.graph import StateGraph, START, END
        from typing import TypedDict, Annotated

        class GraphState(TypedDict):
            industry: str
            companies: List[str]
            search_results: Dict
            current_step: str
            error: Optional[str]

        # 创建图
        workflow = StateGraph(GraphState)

        # 添加节点
        workflow.add_node("start", self.start_node)
        workflow.add_node("search_companies", self.search_companies_node)
        workflow.add_node("browse_jobs", self.browse_jobs_node)
        workflow.add_node("complete", self.complete_node)
        workflow.add_node("failed", self.failed_node)

        # 添加边
        workflow.add_edge(START, "start")
        workflow.add_edge("start", "search_companies")
        workflow.add_edge("search_companies", "browse_jobs")
        workflow.add_edge("browse_jobs", "complete")
        workflow.add_edge("complete", END)
        workflow.add_edge("failed", END)

        return workflow

    async def start_node(self, state: dict) -> dict:
        """开始节点"""
        logger.info("开始浏览器搜索任务")
        return {
            "current_step": "开始搜索",
            "industry": state.get("industry", ""),
            "companies": state.get("companies", [])
        }

    async def search_companies_node(self, state: dict) -> dict:
        """搜索公司节点"""
        try:
            logger.info("搜索公司信息...")
            browser_agent = BrowserAgent()
            await browser_agent.start_browser()

            search_results = await browser_agent.search_companies(
                state["industry"],
                max_results=10
            )

            await browser_agent.stop_browser()

            return {
                "search_results": {
                    "companies_found": search_results,
                    "industry": state["industry"]
                },
                "current_step": "公司搜索完成"
            }
        except Exception as e:
            return {"error": str(e)}

    async def browse_jobs_node(self, state: dict) -> dict:
        """浏览职位节点"""
        try:
            logger.info("开始浏览职位...")

            if state.get("error"):
                return {"error": state["error"]}

            browser_agent = BrowserAgent()
            await browser_agent.start_browser()

            results = await browser_agent.browse_and_search(
                state["industry"],
                state["companies"]
            )

            await browser_agent.stop_browser()

            return {
                "search_results": results,
                "current_step": "职位浏览完成"
            }
        except Exception as e:
            return {"error": str(e)}

    async def complete_node(self, state: dict) -> dict:
        """完成节点"""
        logger.info("任务完成")
        return {
            "search_results": state.get("search_results", {}),
            "current_step": "任务完成"
        }

    async def failed_node(self, state: dict) -> dict:
        """失败节点"""
        logger.error("任务失败")
        return {
            "error": state.get("error", "未知错误"),
            "current_step": "任务失败"
        }

    async def run_search(self, industry: str, companies: List[str]) -> Dict:
        """运行搜索任务"""
        logger.info(f"运行浏览器搜索: {industry}")

        # 创建图
        graph = await self.create_graph()
        app = graph.compile()

        # 运行任务
        result = await app.ainvoke({
            "industry": industry,
            "companies": companies,
            "search_results": {},
            "current_step": "开始"
        })

        # 保存结果
        if result.get("search_results"):
            output_path = Path(project_root) / "output" / "browser_search_results.json"
            import json
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result["search_results"], f, ensure_ascii=False, indent=2)

        return result


# 工具函数
async def run_browser_search(industry: str, companies: List[str]) -> Dict:
    """运行浏览器搜索的快捷函数"""
    search_graph = BrowserSearchGraph()
    return await search_graph.run_search(industry, companies)


# 测试函数
async def test_browser_search():
    """测试浏览器搜索功能"""
    print("=== 测试浏览器漫游寻址 ===")

    # 测试数据
    industry = "互联网"
    companies = ["阿里巴巴", "腾讯", "字节跳动"]

    try:
        # 运行搜索
        results = await run_browser_search(industry, companies)

        print(f"✅ 搜索成功！")
        print(f"   行业: {results['search_results']['industry']}")
        print(f"   找到职位: {results['search_results']['total_jobs']} 个")
        print(f"   搜索URL: {len(results['search_results']['searched_urls'])} 个")

        # 显示前5个职位
        for i, job in enumerate(results['search_results']['jobs'][:5], 1):
            print(f"\n   {i}. {job.get('title', '未知职位')}")
            print(f"      公司: {job.get('company', '未知公司')}")
            print(f"      地点: {job.get('location', '未知')}")
            print(f"      薪资: {job.get('salary', '面议')}")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(test_browser_search())