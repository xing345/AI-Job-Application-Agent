"""
完全未知官网结构处理演示
展示如何利用 browser-use 和 LLM 让 Agent 自己找到"加入我们"并提取岗位列表
"""

import asyncio
import json
from datetime import datetime

# 添加项目根目录到路径
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.browser.browser_agent import BrowserAgent
from src.browser.advanced_crawler import AdvancedCrawler, CrawlConfig


class UnknownWebsiteProcessor:
    """完全未知官网处理器"""

    def __init__(self):
        self.browser_agent = BrowserAgent(headless=False)  # 显示浏览器便于观察
        self.advanced_crawler = None

    async def process_unknown_website(self, company_name: str, website_url: str) -> dict:
        """
        处理完全未知的官网结构

        Args:
            company_name: 公司名称
            website_url: 网站URL

        Returns:
            处理结果
        """
        print(f"\n{'='*80}")
        print(f"🔍 开始处理未知网站: {company_name} - {website_url}")
        print(f"{'='*80}")

        results = {
            "company": company_name,
            "website_url": website_url,
            "timestamp": datetime.now().isoformat(),
            "strategies_used": [],
            "career_pages_found": [],
            "jobs_extracted": [],
            "total_steps": 0,
            "execution_time": 0
        }

        start_time = datetime.now()

        try:
            # 启动浏览器
            await self.browser_agent.start_browser()

            # 记录处理过程
            process_log = []

            # === 策略1: 直接内容分析 ===
            print(f"\n📋 策略1: 直接内容分析")
            print("-" * 40)
            result1 = await self._strategy_direct_analysis(website_url)
            process_log.append(f"策略1 - 直接分析: {'✅ 成功' if result1 else '❌ 失败'}")
            results["strategies_used"].append({
                "name": "Direct Content Analysis",
                "success": result1 is not None,
                "result": result1
            })
            if result1:
                results["career_pages_found"].append({
                    "strategy": "直接分析",
                    "url": result1,
                    "method": "LLM内容识别"
                })

            # === 策略2: 智能导航点击 ===
            print(f"\n🖱️  策略2: 智能导航点击")
            print("-" * 40)
            result2 = await self._strategy_smart_navigation(website_url)
            process_log.append(f"策略2 - 智能导航: {'✅ 成功' if result2 else '❌ 失败'}")
            results["strategies_used"].append({
                "name": "Smart Navigation Clicking",
                "success": result2 is not None,
                "result": result2
            })
            if result2:
                results["career_pages_found"].append({
                    "strategy": "智能导航",
                    "url": result2,
                    "method": "元素点击识别"
                })

            # === 策略3: 高级爬虫 ===
            print(f"\n🕷️  策略3: 高级爬虫算法")
            print("-" * 40)
            result3 = await self._strategy_advanced_crawler(website_url)
            process_log.append(f"策略3 - 高级爬虫: {'✅ 成功' if result3 else '❌ 失败'}")
            results["strategies_used"].append({
                "name": "Advanced Crawler",
                "success": result3 is not None,
                "result": result3
            })
            if result3:
                results["career_pages_found"].append({
                    "strategy": "高级爬虫",
                    "url": result3["url"],
                    "method": "智能路径探索",
                    "jobs_count": len(result3["jobs"])
                })

            # === 汇总结果 ===
            end_time = datetime.now()
            results["execution_time"] = (end_time - start_time).total_seconds()
            results["total_steps"] = len(process_log)

            print(f"\n{'='*80}")
            print(f"📊 处理结果汇总")
            print(f"{'='*80}")

            # 显示策略执行日志
            print("\n📋 执行日志:")
            for log in process_log:
                print(f"   {log}")

            # 显示找到的招聘页面
            if results["career_pages_found"]:
                print(f"\n🎯 找到 {len(results['career_pages_found'])} 个招聘页面:")
                for i, page in enumerate(results["career_pages_found"], 1):
                    print(f"\n   {i}. {page['strategy']} - {page['method']}")
                    print(f"      URL: {page['url']}")
                    if "jobs_count" in page:
                        print(f"      职位数: {page['jobs_count']}")

            # 显示提取的职位
            all_jobs = []
            for strategy in results["strategies_used"]:
                if strategy["success"] and isinstance(strategy["result"], dict):
                    if "jobs" in strategy["result"]:
                        all_jobs.extend(strategy["result"]["jobs"])

            if all_jobs:
                print(f"\n📝 共提取到 {len(all_jobs)} 个职位:")
                for i, job in enumerate(all_jobs[:5], 1):  # 只显示前5个
                    print(f"\n   {i}. {job.get('title', '未知职位')}")
                    print(f"      公司: {job.get('company', company_name)}")
                    if job.get('location'):
                        print(f"      地点: {job['location']}")
                    if job.get('salary'):
                        print(f"      薪资: {job['salary']}")
                    print(f"      描述: {job.get('description', '')[:100]}...")

                if len(all_jobs) > 5:
                    print(f"\n   ... 还有 {len(all_jobs) - 5} 个职位")

            return results

        except Exception as e:
            print(f"\n❌ 处理失败: {e}")
            results["error"] = str(e)
            return results

        finally:
            await self.browser_agent.stop_browser()

    async def _strategy_direct_analysis(self, url: str) -> str:
        """策略1: 直接内容分析"""
        try:
            print("   🔍 分析页面内容，识别招聘相关元素...")

            # 导航到页面
            if not await self.browser_agent.navigate_to(url):
                print("   ❌ 页面导航失败")
                return None

            # 使用原始方法分析
            career_page = await self.browser_agent.find_career_page(url)
            if career_page:
                print("   ✅ 通过直接分析找到招聘页面")
                return career_page
            else:
                print("   ❌ 未找到招聘页面")
                return None

        except Exception as e:
            print(f"   ❌ 策略1失败: {e}")
            return None

    async def _strategy_smart_navigation(self, url: str) -> str:
        """策略2: 智能导航点击"""
        try:
            print("   🎯 使用智能导航点击，寻找招聘链接...")

            # 重新导航到主页
            if not await self.browser_agent.navigate_to(url):
                return None

            # 这里直接调用browser_agent的增强方法
            career_page = await self.browser_agent._find_career_by_navigation_clicking()
            if career_page:
                print("   ✅ 通过智能导航点击找到招聘页面")
                return career_page
            else:
                print("   ❌ 智能导航未找到招聘页面")
                return None

        except Exception as e:
            print(f"   ❌ 策略2失败: {e}")
            return None

    async def _strategy_advanced_crawler(self, url: str) -> dict:
        """策略3: 高级爬虫"""
        try:
            print("   🕸️  启动高级爬虫算法，智能探索网站结构...")

            # 创建高级爬虫配置
            config = CrawlConfig(
                max_depth=5,
                timeout=30000,
                enable_javascript=True,
                screenshot_on_error=True,
                max_retries=3
            )

            # 使用高级爬虫
            self.advanced_crawler = AdvancedCrawler(config)
            result = await self.advanced_crawler.crawl_unknown_website(url)

            if result.success and result.job_listings:
                print(f"   ✅ 高级爬虫找到 {len(result.job_listings)} 个职位")
                print(f"      爬取路径: {len(result.crawl_path)} 个步骤")
                print(f"      最终URL: {result.url}")
                return {
                    "url": result.url,
                    "jobs": result.job_listings,
                    "crawl_steps": len(result.crawl_path)
                }
            else:
                print("   ❌ 高级爬虫未找到职位")
                return None

        except Exception as e:
            print(f"   ❌ 策略3失败: {e}")
            return None

    async def save_results(self, results: dict, filename: str = None):
        """保存结果到文件"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"unknown_website_processing_{timestamp}.json"

        output_path = project_root / "output" / filename
        output_path.parent.mkdir(exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)

        print(f"\n💾 结果已保存到: {output_path}")
        return output_path


async def demo_unknown_website_processing():
    """演示处理未知网站"""
    print("🚀 完全未知官网结构处理演示")
    print("展示如何利用 browser-use 和 LLM 让 Agent 自己找到'加入我们'并提取岗位列表")

    # 创建处理器
    processor = UnknownWebsiteProcessor()

    # 测试一些已知的网站（注意：这些是示例网站，实际使用时请替换为真实的公司网站）
    test_cases = [
        {
            "name": "示例公司1",
            "url": "https://example.com"  # 替换为真实网站
        },
        # 可以添加更多测试案例
        # {
        #     "name": "阿里巴巴",
        #     "url": "https://www.alibaba.com"
        # },
        # {
        #     "name": "腾讯",
        #     "url": "https://www.tencent.com"
        # }
    ]

    all_results = []

    for case in test_cases:
        print(f"\n{'='*80}")
        print(f"🏢 处理: {case['name']}")
        print(f"{'='*80}")

        result = await processor.process_unknown_website(case["name"], case["url"])
        all_results.append(result)

        # 保存每个案例的结果
        await processor.save_results(result, f"unknown_site_{case['name']}.json")

    # 保存完整结果
    final_results = {
        "demo_date": datetime.now().isoformat(),
        "total_companies": len(test_cases),
        "successful_companies": len([r for r in all_results if r["career_pages_found"]]),
        "results": all_results
    }

    await processor.save_results(final_results, "complete_unknown_site_demo.json")

    # 总结
    print(f"\n{'='*80}")
    print(f"🎉 演示完成")
    print(f"{'='*80}")
    print(f"📊 处理总结:")
    print(f"   总计公司: {len(test_cases)}")
    print(f"   成功找到招聘页面: {len([r for r in all_results if r['career_pages_found']])}")
    print(f"   成功率: {len([r for r in all_results if r['career_pages_found']]) / len(test_cases) * 100:.1f}%")

    return all_results


if __name__ == "__main__":
    # 运行演示
    results = asyncio.run(demo_unknown_website_processing())

    print(f"\n{'='*80}")
    print("✅ 演示完成！")
    print("💡 提示：在实际使用时，请将测试URL替换为您想要处理的真实公司网站")
    print("🔧 您可以通过调整 CrawlConfig 参数来优化爬取效果")
    print(f"{'='*80}")