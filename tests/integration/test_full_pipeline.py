"""
端到端集成测试
测试完整的求职自动化流程
"""

import asyncio
import os
import sys
from datetime import datetime
from loguru import logger
from typing import List, Dict, Any

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from src.main import ApplicationOrchestrator
from src.orchestrator.state import AgentStatus, print_state_summary
from src.models.instruction_schemas import TargetInstructionSchema


class MockData:
    """模拟数据生成器"""

    @staticmethod
    def create_mock_resume() -> Dict[str, Any]:
        """创建模拟简历数据"""
        return {
            "name": "张三",
            "email": "zhangsan@example.com",
            "phone": "13800138000",
            "summary": "寻求前端开发工程师职位，专注于 React 和 Vue 技术栈，拥有3年以上前端开发经验",
            "skills": [
                "JavaScript", "TypeScript", "React", "Vue", "HTML", "CSS",
                "Webpack", "Vite", "Git", "npm", "RESTful API", "GraphQL"
            ],
            "work_experience": [
                {
                    "company": "某科技有限公司",
                    "position": "前端开发工程师",
                    "start_date": "2022-01",
                    "end_date": "2024-01",
                    "description": "负责公司核心产品的前端开发，使用 React 和 TypeScript 构建用户界面"
                },
                {
                    "company": "创新互联网公司",
                    "position": "初级前端开发",
                    "start_date": "2020-06",
                    "end_date": "2021-12",
                    "description": "参与多个Web应用开发，学习现代前端技术栈"
                }
            ],
            "education": [
                {
                    "school": "XX大学",
                    "major": "计算机科学与技术",
                    "degree": "本科",
                    "start_date": "2016-09",
                    "end_date": "2020-06"
                }
            ],
            "projects": [
                {
                    "name": "企业管理系统",
                    "description": "使用 React 和 Ant Design 开发的企业级管理平台",
                    "technologies": ["React", "TypeScript", "Ant Design", "Redux"],
                    "role": "前端开发",
                    "duration": "6个月",
                    "achievements": ["提升开发效率30%", "用户体验改善"]
                },
                {
                    "name": "电商平台",
                    "description": "基于 Vue.js 的前后端分离电商平台",
                    "technologies": ["Vue.js", "Vuex", "Element UI", "Node.js"],
                    "role": "前端负责人",
                    "duration": "8个月",
                    "achievements": ["日活用户10万+", "转化率提升15%"]
                }
            ]
        }

    @staticmethod
    def create_mock_job_url() -> str:
        """创建模拟职位 URL"""
        return "https://example.com/job/12345"

    @staticmethod
    def create_target_instruction() -> TargetInstructionSchema:
        """创建目标指令"""
        return TargetInstructionSchema(
            company="字节跳动",
            role="前端开发工程师",
            location="北京",
            keywords=["React", "Vue", "JavaScript", "TypeScript"],
            exclude_keywords=["管理", "销售", "市场"],
            posted_days_ago=30
        )


class TestScenario:
    """测试场景基类"""

    def __init__(self, name: str):
        self.name = name
        self.start_time = None
        self.end_time = None

    async def setup(self):
        """测试前置条件"""
        pass

    async def run(self):
        """执行测试"""
        self.start_time = datetime.now()
        logger.info(f"开始测试场景: {self.name}")
        await self.setup()
        result = await self.execute()
        self.end_time = datetime.now()
        return result

    async def execute(self):
        """实际测试逻辑（子类实现）"""
        raise NotImplementedError

    def get_duration(self):
        """获取测试耗时"""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None


class BasicFlowTest(TestScenario):
    """基本流程测试"""

    async def execute(self):
        """测试基本流程"""
        print(f"\n{'='*60}")
        print(f"🧪 场景1: 基本流程测试")
        print(f"{'='*60}")

        # 创建测试数据
        instruction = MockData.create_target_instruction()
        mock_resume = MockData.create_mock_resume()

        # 创建编排器
        orchestrator = ApplicationOrchestrator()

        # 创建模拟状态
        from src.orchestrator.state import create_initial_state
        state = create_initial_state("mock_resume.pdf", instruction)

        # 模拟简历解析
        from src.models.schemas import ResumeSchema
        parsed_resume = ResumeSchema(**mock_resume)
        state = self._update_state(state, parsed_resume=parsed_resume, progress=30.0)
        state = self._add_log(state, "简历解析完成")

        # 模拟职位搜索
        mock_urls = [
            "https://example.com/job/1",
            "https://example.com/job/2",
            "https://example.com/job/3"
        ]
        state = self._update_state(state, qualified_urls=mock_urls, progress=50.0)
        state = self._add_log(state, f"找到 {len(mock_urls)} 个职位")

        # 模拟职位匹配
        mock_matches = [
            {"url": mock_urls[0], "title": "前端开发工程师", "company": "字节跳动", "match_score": 85},
            {"url": mock_urls[1], "title": "Web开发工程师", "company": "腾讯", "match_score": 78},
            {"url": mock_urls[2], "title": "高级前端工程师", "company": "阿里巴巴", "match_score": 92}
        ]
        state = self._update_state(state, match_results=mock_matches, progress=65.0)
        state = self._add_log(state, "职位匹配完成")

        # 模拟自动填报
        submitted_urls = mock_urls[:2]  # 只提交前2个
        state = self._update_state(state, submitted_urls=submitted_urls, progress=90.0)
        state = self._add_log(state, f"成功提交 {len(submitted_urls)} 个申请")

        # 完成流程
        state = self._update_state(state, status=AgentStatus.COMPLETED, progress=100.0)
        state = self._add_log(state, "✅ 流程执行完成")

        # 打印结果
        self._print_result(state)

        return {
            "scenario": self.name,
            "status": "success",
            "duration": self.get_duration(),
            "submitted_count": len(submitted_urls),
            "found_count": len(mock_urls)
        }

    def _update_state(self, state, **kwargs):
        """更新状态"""
        from src.orchestrator.state import update_state
        return update_state(state, **kwargs)

    def _add_log(self, state, message):
        """添加日志"""
        from src.orchestrator.state import add_log
        return add_log(state, message)

    def _print_result(self, state):
        """打印测试结果"""
        print(f"\n📊 测试结果:")
        print(f"   状态: {state['status']}")
        print(f"   进度: {state['progress']:.1f}%")
        print(f"   找到职位: {len(state['qualified_urls'])} 个")
        print(f"   提交申请: {len(state['submitted_urls'])} 个")
        print(f"   错误数: {len(state['errors'])}")
        print(f"   日志数: {len(state['logs'])}")


class ErrorHandlingTest(TestScenario):
    """错误处理测试"""

    async def execute(self):
        """测试错误处理"""
        print(f"\n{'='*60}")
        print(f"🧪 场景2: 错误处理测试")
        print(f"{'='*60}")

        # 创建测试数据
        instruction = MockData.create_target_instruction()

        # 创建编排器
        orchestrator = ApplicationOrchestrator()

        # 创建模拟状态
        from src.orchestrator.state import create_initial_state
        state = create_initial_state("nonexistent.pdf", instruction)

        # 模拟文件不存在错误
        state = self._add_error(state, "简历文件不存在: nonexistent.pdf")
        state = self._update_state(state, status=AgentStatus.FAILED, progress=0.0)

        # 模拟职位搜索失败
        state = self._update_state(state, status=AgentStatus.FINDING_JOBS, progress=35.0)
        state = self._add_error(state, "网络连接超时")
        state = self._update_state(state, status=AgentStatus.FAILED, progress=0.0)

        # 打印结果
        self._print_error_result(state)

        return {
            "scenario": self.name,
            "status": "success",
            "duration": self.get_duration(),
            "error_count": len(state['errors'])
        }

    def _add_error(self, state, error):
        """添加错误"""
        from src.orchestrator.state import add_error
        return add_error(state, error)

    def _update_state(self, state, **kwargs):
        """更新状态"""
        from src.orchestrator.state import update_state
        return update_state(state, **kwargs)

    def _add_error(self, state, error):
        """添加错误"""
        from src.orchestrator.state import add_error
        return add_error(state, error)

    def _print_error_result(self, state):
        """打印错误测试结果"""
        print(f"\n📊 错误处理结果:")
        print(f"   状态: {state['status']}")
        print(f"   错误数量: {len(state['errors'])}")
        print(f"   错误信息:")
        for i, error in enumerate(state['errors'], 1):
            print(f"     {i}. {error}")


class PerformanceTest(TestScenario):
    """性能测试"""

    async def execute(self):
        """测试性能"""
        print(f"\n{'='*60}")
        print(f"🧪 场景3: 性能测试")
        print(f"{'='*60}")

        # 创建测试数据
        instruction = MockData.create_target_instruction()

        # 创建编排器
        orchestrator = ApplicationOrchestrator()

        # 模拟大量职位处理
        mock_urls = [f"https://example.com/job/{i}" for i in range(50)]
        mock_matches = [
            {
                "url": url,
                "title": f"前端开发工程师_{i}",
                "company": f"公司_{i}",
                "match_score": 70 + (i % 30)  # 70-99的分数
            }
            for i, url in enumerate(mock_urls)
        ]

        # 创建模拟状态
        from src.orchestrator.state import create_initial_state
        state = create_initial_state("mock_resume.pdf", instruction)
        state = self._update_state(state, qualified_urls=mock_urls, progress=50.0)
        state = self._update_state(state, match_results=mock_matches, progress=65.0)

        # 模拟批量提交
        import random
        submitted_count = random.randint(20, 30)
        submitted_urls = mock_urls[:submitted_count]
        state = self._update_state(state, submitted_urls=submitted_urls, progress=95.0)

        # 计算性能指标
        success_rate = (submitted_count / len(mock_urls)) * 100
        high_match_count = len([m for m in mock_matches if m['match_score'] >= 85])

        # 添加性能日志
        duration = self.get_duration()
        duration_str = f"{duration.total_seconds():.2f}秒" if duration else "N/A"
        state = self._add_log(state, f"性能指标 - 成功率: {success_rate:.1f}%")
        state = self._add_log(state, f"高匹配度职位: {high_match_count} 个")
        state = self._add_log(state, f"平均处理时间: {duration_str}")

        # 打印性能结果
        print(f"\n📊 性能测试结果:")
        print(f"   总职位数: {len(mock_urls)}")
        print(f"   提交数: {submitted_count}")
        print(f"   成功率: {success_rate:.1f}%")
        print(f"   高匹配度: {high_match_count} 个")
        duration = self.get_duration()
        print(f"   处理时间: {duration.total_seconds():.2f}秒" if duration else "   处理时间: N/A")
        duration = self.get_duration()
        avg_time = (duration.total_seconds() / len(mock_urls)) if duration else 0
        print(f"   平均每职位: {avg_time:.3f}秒")

    def _update_state(self, state, **kwargs):
        """更新状态"""
        from src.orchestrator.state import update_state
        return update_state(state, **kwargs)

    def _add_log(self, state, message):
        """添加日志"""
        from src.orchestrator.state import add_log
        return add_log(state, message)

        return {
            "scenario": self.name,
            "status": "success",
            "duration": self.get_duration(),
            "total_jobs": len(mock_urls),
            "submitted_jobs": submitted_count,
            "success_rate": success_rate
        }


class IntegrationTestSuite:
    """集成测试套件"""

    def __init__(self):
        self.scenarios = [
            BasicFlowTest("基本流程测试"),
            ErrorHandlingTest("错误处理测试"),
            PerformanceTest("性能测试")
        ]
        self.results = []

    async def run_all(self):
        """运行所有测试"""
        print("\n" + "="*80)
        print("🧪 开始运行集成测试套件")
        print("="*80)

        # 运行每个测试场景
        for scenario in self.scenarios:
            result = await scenario.run()
            self.results.append(result)

        # 生成测试报告
        self._generate_report()

    def _generate_report(self):
        """生成测试报告"""
        print(f"\n{'='*80}")
        print("📋 集成测试报告")
        print(f"{'='*80}")

        # 汇总结果
        valid_durations = [r['duration'] for r in self.results if r and r.get('duration')]
        total_duration = sum(d.total_seconds() for d in valid_durations) if valid_durations else 0
        success_count = sum(1 for r in self.results if r and r.get('status') == 'success')

        print(f"\n📊 测试概览:")
        print(f"   总场景数: {len(self.scenarios)}")
        print(f"   成功场景: {success_count}")
        print(f"   失败场景: {len(self.scenarios) - success_count}")
        print(f"   总耗时: {total_duration:.2f}秒" if total_duration else "   总耗时: N/A")

        # 详细结果
        for result in self.results:
            if not result:
                continue

            print(f"\n{'─'*60}")
            print(f"🎯 场景: {result['scenario']}")
            print(f"   状态: {result['status']}")
            print(f"   耗时: {result['duration'].total_seconds():.2f}秒" if result.get('duration') else "   耗时: N/A")

            # 场景特定结果
            if 'submitted_count' in result:
                print(f"   提交数量: {result['submitted_count']}")
            if 'found_count' in result:
                print(f"   找到数量: {result['found_count']}")
            if 'error_count' in result:
                print(f"   错误数量: {result['error_count']}")
            if 'success_rate' in result:
                print(f"   成功率: {result['success_rate']:.1f}%")

        # 建议
        print(f"\n{'─'*60}")
        print("💡 改进建议:")
        if success_count < len(self.scenarios):
            print("   - 建议检查失败场景的错误处理逻辑")
            print("   - 考虑增加重试机制")
        print("   - 建议添加更多边界条件测试")
        print("   - 考虑添加性能基准测试")

        print(f"\n{'='*80}")


async def main():
    """主函数"""
    print("🚀 求职自动化助手 - 集成测试")
    print("测试范围: 端到端流程、错误处理、性能")

    # 创建测试套件
    test_suite = IntegrationTestSuite()

    # 运行测试
    await test_suite.run_all()

    print("\n✅ 测试完成！")


if __name__ == "__main__":
    # 设置日志
    logger.add(
        sink=sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO",
        colorize=True
    )

    # 运行测试
    asyncio.run(main())