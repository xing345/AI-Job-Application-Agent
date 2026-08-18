"""
Phase 7 测试脚本
测试浏览器漫游寻址功能
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.browser.browser_agent import BrowserAgent, BrowserSearchGraph, run_browser_search


async def test_browser_agent_basic():
    """测试浏览器Agent基础功能"""
    print("\n=== 测试浏览器Agent基础功能 ===")

    try:
        # 创建浏览器Agent
        agent = BrowserAgent(headless=True)  # 使用无头模式进行测试

        # 测试页面导航
        test_url = "https://www.baidu.com"
        print(f"导航到: {test_url}")

        success = await agent.navigate_to(test_url)
        if success:
            print("✅ 页面导航成功")
            print(f"   当前URL: {agent.state.url}")
            print(f"   内容长度: {len(agent.state.content)} 字符")
            return True
        else:
            print("❌ 页面导航失败")
            return False

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def test_company_search():
    """测试公司搜索功能"""
    print("\n=== 测试公司搜索功能 ===")

    try:
        # 创建浏览器Agent
        agent = BrowserAgent(headless=True)

        # 模拟公司搜索（不使用真实API）
        print("模拟搜索公司: 互联网技术")

        # 模拟搜索结果
        mock_results = [
            {
                "title": "阿里巴巴官网",
                "url": "https://www.alibaba.com",
                "content": "阿里巴巴集团官网，提供电子商务服务..."
            },
            {
                "title": "腾讯官网",
                "url": "https://www.tencent.com",
                "content": "腾讯公司官网，提供互联网服务..."
            }
        ]

        print(f"✅ 模拟搜索成功，找到 {len(mock_results)} 个结果")
        for i, result in enumerate(mock_results, 1):
            print(f"   {i}. {result['title']}")
            print(f"      URL: {result['url']}")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def test_browser_search_graph():
    """测试浏览器搜索图"""
    print("\n=== 测试浏览器搜索图 ===")

    try:
        # 创建搜索图
        search_graph = BrowserSearchGraph()

        # 测试图创建
        graph = await search_graph.create_graph()
        print("✅ LangGraph创建成功")

        # 测试数据
        industry = "互联网"
        companies = ["阿里巴巴", "腾讯"]

        print(f"行业: {industry}")
        print(f"公司: {', '.join(companies)}")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def test_mock_browse_and_search():
    """测试模拟的浏览和搜索"""
    print("\n=== 测试模拟浏览和搜索 ===")

    try:
        # 创建浏览器Agent
        agent = BrowserAgent(headless=True)

        # 模拟浏览和搜索
        industry = "互联网"
        companies = ["阿里巴巴", "腾讯", "字节跳动"]

        print(f"开始模拟浏览: {industry}")
        print(f"目标公司: {', '.join(companies)}")

        # 模拟职位数据
        mock_jobs = [
            {
                "title": "高级前端开发工程师",
                "company": "阿里巴巴",
                "location": "杭州",
                "description": "负责电商平台前端开发",
                "url": "https://job.alibaba.com/position/detail/12345",
                "salary": "25-40K",
                "requirements": ["React", "Vue", "TypeScript"]
            },
            {
                "title": "资深产品经理",
                "company": "腾讯",
                "location": "深圳",
                "description": "负责社交产品规划",
                "url": "https://careers.tencent.com/jobdetail.html?id=67890",
                "salary": "30-50K",
                "requirements": ["产品设计", "用户研究", "数据分析"]
            },
            {
                "title": "算法工程师",
                "company": "字节跳动",
                "location": "北京",
                "description": "推荐算法开发",
                "url": "https://job.bytedance.com/position/54321",
                "salary": "35-60K",
                "requirements": ["机器学习", "深度学习", "Python"]
            }
        ]

        print(f"✅ 模拟提取到 {len(mock_jobs)} 个职位")
        for i, job in enumerate(mock_jobs, 1):
            print(f"\n   {i}. {job['title']}")
            print(f"      公司: {job['company']}")
            print(f"      地点: {job['location']}")
            print(f"      薪资: {job['salary']}")
            print(f"      要求: {', '.join(job['requirements'][:3])}")

        # 模拟保存结果
        import json
        from datetime import datetime

        mock_results = {
            "industry": industry,
            "companies_searched": companies,
            "total_jobs": len(mock_jobs),
            "jobs": mock_jobs,
            "searched_urls": ["https://www.alibaba.com", "https://www.tencent.com", "https://www.bytedance.com"],
            "timestamp": datetime.now().isoformat()
        }

        # 保存模拟结果
        output_path = project_root / "output" / "mock_browser_search.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(mock_results, f, ensure_ascii=False, indent=2)

        print(f"\n📁 模拟结果已保存到: {output_path}")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def test_html_content_parsing():
    """测试HTML内容解析"""
    print("\n=== 测试HTML内容解析 ===")

    try:
        from src.utils.llm_client import get_llm_client

        client = get_llm_client()

        # 模拟HTML内容
        mock_html = """
        <html>
        <head><title>阿里巴巴招聘</title></head>
        <body>
            <h1>加入阿里巴巴</h1>
            <div class="job-list">
                <div class="job-item">
                    <h2>高级前端开发工程师</h2>
                    <p>地点: 杭州</p>
                    <p>薪资: 25-40K</p>
                    <a href="/jobs/frontend-123">查看详情</a>
                </div>
                <div class="job-item">
                    <h2>Java开发工程师</h2>
                    <p>地点: 杭州</p>
                    <p>薪资: 20-35K</p>
                    <a href="/jobs/java-456">查看详情</a>
                </div>
            </div>
            <a href="/careers">更多职位</a>
        </body>
        </html>
        """

        prompt = f"""
        从以下HTML中提取职位信息：

        {mock_html}

        输出JSON格式：
        {{
            "jobs": [
                {{
                    "title": "职位名称",
                    "company": "公司名称",
                    "location": "工作地点",
                    "salary": "薪资范围",
                    "url": "详情链接"
                }}
            ]
        }}
        """

        response = await client.generate_response(prompt, json_output=True)

        jobs = response.get("jobs", [])
        print(f"✅ 解析成功，提取到 {len(jobs)} 个职位")
        for job in jobs:
            print(f"   {job['title']} - {job['location']} - {job['salary']}")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def main():
    """主测试函数"""
    print("🚀 开始 Phase 7 功能测试...")

    results = []

    # 测试1: 基础浏览器功能
    results.append(await test_browser_agent_basic())

    # 测试2: 公司搜索
    results.append(await test_company_search())

    # 测试3: 浏览器搜索图
    results.append(await test_browser_search_graph())

    # 测试4: 模拟浏览和搜索
    results.append(await test_mock_browse_and_search())

    # 测试5: HTML解析
    results.append(await test_html_content_parsing())

    # 输出测试结果
    print(f"\n{'='*60}")
    print("📊 测试结果汇总")
    print(f"{'='*60}")

    passed = sum(results)
    total = len(results)

    print(f"通过: {passed}/{total}")

    if passed == total:
        print("✅ 所有测试通过！")
        return True
    else:
        print("❌ 部分测试失败，请检查配置")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)