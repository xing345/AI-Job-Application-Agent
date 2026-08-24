"""
高级爬虫：专门处理完全未知的官网结构
基于 browser-use 和 LLM 的智能导航系统
"""

import asyncio
import json
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from loguru import logger

from playwright.async_api import Page, Browser, Error as PlaywrightError
from pydantic import BaseModel, Field

# 添加项目根目录到路径
import sys
import os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.utils.llm_client import get_llm_client


class CrawlConfig(BaseModel):
    """爬虫配置"""
    max_depth: int = Field(default=5, description="最大爬取深度")
    timeout: int = Field(default=30000, description="页面加载超时")
    wait_for_selector: str = Field(default="body", description="等待加载的选择器")
    enable_javascript: bool = Field(default=True, description="启用JavaScript渲染")
    screenshot_on_error: bool = Field(default=True, description="错误时截图")
    max_retries: int = Field(default=3, description="最大重试次数")


class CrawlStep(BaseModel):
    """爬取步骤"""
    step_type: str = Field(..., description="步骤类型: navigate, click, extract, wait")
    target: str = Field(..., description="目标URL或元素选择器")
    description: str = Field(..., description="步骤描述")
    timeout: int = Field(default=10000, description="超时时间")
    expected_outcome: str = Field(default="", description="预期结果")


class CrawlResult(BaseModel):
    """爬取结果"""
    url: str = Field(..., description="最终URL")
    title: str = Field(..., description="页面标题")
    content: str = Field(..., description="页面内容")
    job_listings: List[Dict] = Field(default_factory=list, description="职位列表")
    crawl_path: List[CrawlStep] = Field(default_factory=list, description="爬取路径")
    success: bool = Field(default=True, description="是否成功")
    error: Optional[str] = Field(None, description="错误信息")
    screenshots: List[str] = Field(default_factory=list, description="截图路径")


class AdvancedCrawler:
    """高级爬虫：处理完全未知的官网结构"""

    def __init__(self, config: CrawlConfig = None):
        self.config = config or CrawlConfig()
        self.browser = None
        self.llm_client = get_llm_client()
        self.screenshot_dir = Path(project_root) / "screenshots"
        self.screenshot_dir.mkdir(exist_ok=True)

    async def start_browser(self) -> Browser:
        """启动浏览器"""
        from playwright.async_api import async_playwright

        if self.browser:
            return self.browser

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=False,  # 默认显示浏览器以便调试
            viewport={"width": 1280, "height": 720}
        )

        logger.info("浏览器启动成功")
        return self.browser

    async def stop_browser(self):
        """停止浏览器"""
        if self.browser:
            await self.browser.close()
            if hasattr(self, 'playwright'):
                await self.playwright.stop()
            logger.info("浏览器已停止")

    async def take_screenshot(self, page: Page, filename: str = None) -> str:
        """截图"""
        if not filename:
            timestamp = int(time.time())
            filename = f"crawl_{timestamp}.png"

        screenshot_path = self.screenshot_dir / filename
        await page.screenshot(path=str(screenshot_path))
        logger.info(f"截图已保存: {screenshot_path}")
        return str(screenshot_path)

    async def analyze_page_structure(self, page: Page) -> Dict:
        """
        分析页面结构，识别可能的招聘相关元素
        """
        try:
            # 获取页面内容
            content = await page.content()
            title = await page.title()
            url = page.url

            # 使用LLM分析页面结构
            prompt = f"""
            请分析以下页面的结构，识别所有可能的招聘相关元素：

            页面标题: {title}
            当前URL: {url}
            页面内容: {content[:5000]}

            请识别：
            1. 导航菜单中的招聘相关链接
            2. 页面标题中的招聘关键词
            3. 可能的招聘页面链接
            4. 按钮中的招聘相关文本
            5. 页面结构类型（首页、关于我们、产品页等）

            输出JSON格式：
            {{
                "page_type": "页面类型",
                "navigation_links": [{{"text": "链接文本", "url": "目标URL"}}],
                "recruitment_indicators": ["指示词1", "指示词2"],
                "possible_job_links": [{{"text": "链接文本", "selector": "CSS选择器"}}],
                "recommended_action": "建议操作"
            }}
            """

            result = await self.llm_client.generate_response(prompt, json_output=True)
            return result

        except Exception as e:
            logger.error(f"页面结构分析失败: {e}")
            return {
                "page_type": "unknown",
                "navigation_links": [],
                "recruitment_indicators": [],
                "possible_job_links": [],
                "recommended_action": "continue"
            }

    async def find_recruitment_paths(self, page: Page) -> List[CrawlStep]:
        """
        查找通往招聘页面的路径
        """
        try:
            # 分析当前页面
            analysis = await self.analyze_page_structure(page)

            # 构建可能的爬取步骤
            steps = []

            # 1. 检查当前页面是否已经是招聘页面
            if analysis["page_type"] == "recruitment":
                return []

            # 2. 查找导航链接
            nav_links = analysis.get("navigation_links", [])
            for link in nav_links:
                if self._is_recruitment_related(link["text"]):
                    steps.append(CrawlStep(
                        step_type="click",
                        target=f"text={link['text']}",
                        description=f"点击招聘相关链接: {link['text']}",
                        expected_outcome="进入招聘页面"
                    ))

            # 3. 查找页面内的招聘相关元素
            possible_links = analysis.get("possible_job_links", [])
            for link in possible_links[:5]:  # 限制数量
                steps.append(CrawlStep(
                    step_type="click",
                    target=link.get("selector", f"text={link['text']}"),
                    description=f"点击可能的招聘链接: {link['text']}",
                    expected_outcome="找到招聘页面"
                ))

            # 4. 查找常见的招聘页面路径
            common_paths = [
                ("text=加入我们", "点击'加入我们'链接"),
                ("text=招聘", "点击'招聘'链接"),
                ("text=人才招聘", "点击'人才招聘'链接"),
                ("text=招贤纳士", "点击'招贤纳士'链接"),
                ("text=Careers", "点击'Careers'链接"),
                ("text=Join Us", "点击'Join Us'链接"),
                ("text=Work at", "点击'Work at'链接")
            ]

            for text, desc in common_paths:
                steps.append(CrawlStep(
                    step_type="click",
                    target=f"text={text}",
                    description=desc,
                    expected_outcome="找到招聘页面"
                ))

            return steps

        except Exception as e:
            logger.error(f"查找招聘路径失败: {e}")
            return []

    def _is_recruitment_related(self, text: str) -> bool:
        """判断文本是否与招聘相关"""
        recruitment_keywords = [
            "招聘", "招贤纳士", "加入我们", "人才", "职业", "工作",
            "Careers", "Join Us", "Work at", "Jobs", "Hiring",
            "Talent", "Recruitment", "Vacancies"
        ]
        return any(keyword.lower() in text.lower() for keyword in recruitment_keywords)

    async def execute_crawl_steps(self, page: Page, steps: List[CrawlStep]) -> List[CrawlStep]:
        """
        执行爬取步骤
        """
        executed_steps = []

        for step in steps:
            try:
                logger.info(f"执行步骤: {step.description}")

                if step.step_type == "click":
                    # 尝试多种方式定位元素
                    element = await page.query_selector(step.target)
                    if not element:
                        # 尝试文本定位
                        element = await page.query_selector(f"text={step.target}")
                    if element:
                        await element.click(timeout=step.timeout)
                        executed_steps.append(step)
                        await asyncio.sleep(1)  # 等待页面加载
                    else:
                        logger.warning(f"未找到元素: {step.target}")

                elif step.step_type == "wait":
                    await asyncio.sleep(step.timeout / 1000)
                    executed_steps.append(step)

            except Exception as e:
                logger.error(f"执行步骤失败: {step.description} - {e}")
                if self.config.screenshot_on_error:
                    await self.take_screenshot(page, f"error_{int(time.time())}.png")

        return executed_steps

    async def extract_job_listings(self, page: Page) -> List[Dict]:
        """
        从页面提取职位列表
        """
        try:
            content = await page.content()
            title = await page.title()

            # 使用LLM提取职位信息
            prompt = f"""
            请从以下页面中提取所有职位信息：

            页面标题: {title}
            页面内容: {content[:8000]}

            请提取以下字段：
            - 职位名称
            - 公司名称
            - 工作地点
            - 职位描述
            - 申请链接（如果有）
            - 薪资范围（如果有）
            - 要求（列表形式）

            输出JSON格式：
            {{
                "company_name": "公司名称",
                "page_title": "页面标题",
                "jobs": [
                    {{
                        "title": "职位名称",
                        "location": "工作地点",
                        "description": "职位描述",
                        "url": "申请链接",
                        "salary": "薪资范围",
                        "requirements": ["要求1", "要求2"]
                    }}
                ]
            }}
            """

            result = await self.llm_client.generate_response(prompt, json_output=True)
            return result.get("jobs", [])

        except Exception as e:
            logger.error(f"提取职位列表失败: {e}")
            return []

    async def crawl_unknown_website(self, start_url: str) -> CrawlResult:
        """
        爬取完全未知的网站，自动找到招聘页面
        """
        logger.info(f"开始爬取未知网站: {start_url}")

        try:
            # 启动浏览器
            browser = await self.start_browser()
            context = await browser.new_context()
            page = await context.new_page()

            # 导航到起始页面
            await page.goto(start_url, timeout=self.config.timeout)
            await page.wait_for_load_state("networkidle")

            # 保存初始页面
            initial_screenshot = await self.take_screenshot(page, "initial_page.png")

            # 爬取路径
            crawl_path = []
            current_url = start_url
            current_depth = 0

            while current_depth < self.config.max_depth:
                logger.info(f"爬取深度 {current_depth}: {current_url}")

                # 分析当前页面
                analysis = await self.analyze_page_structure(page)

                # 检查是否已经是招聘页面
                if analysis["page_type"] == "recruitment":
                    # 提取职位列表
                    job_listings = await self.extract_job_listings(page)
                    logger.info(f"找到 {len(job_listings)} 个职位")
                    return CrawlResult(
                        url=page.url,
                        title=analysis.get("page_type", "未知"),
                        content="",
                        job_listings=job_listings,
                        crawl_path=crawl_path,
                        success=True
                    )

                # 查找可能的招聘路径
                steps = await self.find_recruitment_paths(page)

                if not steps:
                    logger.warning("未找到更多招聘相关链接")
                    break

                # 执行步骤
                executed_steps = await self.execute_crawl_steps(page, steps)
                crawl_path.extend(executed_steps)

                if not executed_steps:
                    logger.warning("没有成功执行的步骤")
                    break

                # 检查是否到达招聘页面
                await page.wait_for_load_state("networkidle")
                current_url = page.url
                current_depth += 1

                # 截图记录
                await self.take_screenshot(page, f"step_{current_depth}.png")

            # 如果循环结束仍未找到，返回最后一次分析的结果
            job_listings = await self.extract_job_listings(page)
            return CrawlResult(
                url=page.url,
                title=analysis.get("page_type", "未知"),
                content="",
                job_listings=job_listings,
                crawl_path=crawl_path,
                success=len(job_listings) > 0
            )

        except Exception as e:
            logger.error(f"爬取失败: {e}")
            if self.config.screenshot_on_error and 'page' in locals():
                await self.take_screenshot(page, "final_error.png")
            return CrawlResult(
                url=start_url,
                title="未知",
                content="",
                job_listings=[],
                crawl_path=crawl_path,
                success=False,
                error=str(e)
            )

        finally:
            await self.stop_browser()


# 工具函数
async def crawl_unknown_website(start_url: str, config: CrawlConfig = None) -> CrawlResult:
    """爬取未知网站的快捷函数"""
    crawler = AdvancedCrawler(config)
    return await crawler.crawl_unknown_website(start_url)


# 测试函数
async def test_advanced_crawler():
    """测试高级爬虫"""
    print("=== 测试高级爬虫功能 ===")

    try:
        # 测试URL
        test_urls = [
            "https://example.com",  # 测试页面
            "https://httpbin.org/html"  # 简单HTML页面
        ]

        for url in test_urls:
            print(f"\n测试URL: {url}")
            result = await crawl_unknown_website(url)

            print(f"结果:")
            print(f"   URL: {result.url}")
            print(f"   标题: {result.title}")
            print(f"   成功: {result.success}")
            print(f"   职位数: {len(result.job_listings)}")
            print(f"   步骤数: {len(result.crawl_path)}")

            if result.job_listings:
                print("   职位列表:")
                for i, job in enumerate(result.job_listings[:3], 1):
                    print(f"     {i}. {job.get('title', '未知')}")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(test_advanced_crawler())