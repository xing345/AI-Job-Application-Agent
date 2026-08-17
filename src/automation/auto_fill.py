"""
自动化表单填写模块
使用 browser-use 框架实现智能表单自动填写
"""

import asyncio
import logging
import sys
import os
from typing import Optional
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright
from pydantic import BaseModel, Field
from loguru import logger

# 添加项目根目录到 Python 路径
import sys
import os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from models.schemas import ResumeSchema, JobSchema, ApplicationLogSchema, ApplicationStatus, WorkExperience, Education, ProjectExperience


class FormFillerConfig(BaseModel):
    """表单填写器配置"""
    timeout: int = Field(30, description="操作超时时间（秒）")
    headless: bool = Field(False, description="是否以无头模式运行")
    wait_after_fill: float = Field(1.0, description="填写后等待时间（秒）")
    max_retries: int = Field(3, description="最大重试次数")
    api_key: Optional[str] = Field(None, description="browser-use API key")
    test_mode: bool = Field(True, description="测试模式，跳过 API 密钥验证")


class AutoFillResult(BaseModel):
    """自动填写结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    filled_fields: int = Field(0, description="已填写的字段数量")
    error: Optional[str] = Field(None, description="错误信息")


class AutoFillAgent:
    """自动表单填写 Agent"""

    def __init__(self, config: Optional[FormFillerConfig] = None):
        self.config = config or FormFillerConfig()
        self.browser = None
        self.logger = logger
        self.logger.add("auto_fill.log", rotation="10 MB")

    async def initialize(self):
        """初始化浏览器"""
        try:
            # 使用 Playwright 启动浏览器
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=self.config.headless)
            self.page = await self.browser.new_page()
            self.logger.info("Playwright browser initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize Playwright: {e}")
            raise

    async def cleanup(self):
        """清理浏览器资源"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
            self.logger.info("Playwright resources cleaned up")

    async def fill_application_form(
        self,
        job_url: str,
        resume_data: ResumeSchema,
        pdf_path: str,
        test_mode: bool = False
    ) -> AutoFillResult:
        """
        自动填写表单

        Args:
            job_url: 职位申请链接
            resume_data: 简历数据
            pdf_path: PDF 简历文件路径
            test_mode: 测试模式（不提交表单）

        Returns:
            AutoFillResult: 填写结果
        """
        if not self.browser:
            await self.initialize()

        try:
            self.logger.info(f"Starting to fill form for job: {job_url}")

            # 打开页面
            self.page = await self.browser.new_page()
            await self.page.goto(job_url)
            self.logger.info("Page opened successfully")

            # 等待页面加载
            await asyncio.sleep(2)

            # 填写基本信息
            filled_count = await self._fill_basic_info(resume_data)

            # 填写工作经历
            filled_count += await self._fill_work_experience(resume_data)

            # 填写教育背景
            filled_count += await self._fill_education(resume_data)

            # 填写项目经验
            filled_count += await self._fill_projects(resume_data)

            # 上传简历文件
            await self._upload_resume(pdf_path)

            # 等待填写完成
            await asyncio.sleep(self.config.wait_after_fill)

            # 安全性检查：不自动提交
            if not test_mode:
                self.logger.warning("Form filled successfully. Will not submit automatically for safety.")
                self.logger.info("请在浏览器中核对表单内容，确认无误后手动点击提交按钮。")
                self.logger.info("按下 Enter 键结束程序...")
                input()  # 等待用户确认

            return AutoFillResult(
                success=True,
                message="表单填写完成",
                filled_count=filled_count
            )

        except Exception as e:
            self.logger.error(f"Error during form filling: {e}")
            return AutoFillResult(
                success=False,
                message=f"表单填写失败: {str(e)}",
                filled_count=0,
                error=str(e)
            )

    async def _fill_basic_info(self, resume_data: ResumeSchema) -> int:
        """填写基本信息"""
        filled_count = 0
        try:
            # 姓名输入框 - 使用精确的选择器
            name_field = self.page.locator("#name")
            if await name_field.count() > 0:
                await name_field.fill(resume_data.name)
                filled_count += 1
                self.logger.info(f"Filled name: {resume_data.name}")

            # 邮箱输入框
            email_field = self.page.locator("#email")
            if await email_field.count() > 0:
                await email_field.fill(resume_data.email)
                filled_count += 1
                self.logger.info(f"Filled email: {resume_data.email}")

            # 电话输入框
            phone_field = self.page.locator("#phone")
            if await phone_field.count() > 0:
                await phone_field.fill(resume_data.phone or "")
                filled_count += 1
                self.logger.info(f"Filled phone: {resume_data.phone}")

            return filled_count

        except Exception as e:
            self.logger.warning(f"Failed to fill basic info: {e}")
            return filled_count

    async def _fill_work_experience(self, resume_data: ResumeSchema) -> int:
        """填写工作经历"""
        filled_count = 0
        try:
            if not resume_data.work_experience:
                return filled_count

            for i, experience in enumerate(resume_data.work_experience):
                # 公司名称
                company_field = self.page.locator(
                    f"input[name*='company'][name*='experience'][name*='{i}']"
                )
                if await company_field.count() > 0:
                    await company_field.fill(experience.company)
                    filled_count += 1
                    self.logger.info(f"Filled company {i}: {experience.company}")

                # 职位名称
                position_field = self.page.locator(
                    f"input[name*='position'][name*='experience'][name*='{i}']"
                )
                if await position_field.count() > 0:
                    await position_field.fill(experience.position)
                    filled_count += 1
                    self.logger.info(f"Filled position {i}: {experience.position}")

                # 开始日期
                start_date_field = self.page.locator(
                    f"input[name*='start_date'][name*='experience'][name*='{i}']"
                )
                if await start_date_field.count() > 0:
                    await start_date_field.fill(experience.start_date)
                    filled_count += 1
                    self.logger.info(f"Filled start date {i}: {experience.start_date}")

            return filled_count

        except Exception as e:
            self.logger.warning(f"Failed to fill work experience: {e}")
            return filled_count

    async def _fill_education(self, resume_data: ResumeSchema) -> int:
        """填写教育背景"""
        filled_count = 0
        try:
            if not resume_data.education:
                return filled_count

            for i, education in enumerate(resume_data.education):
                # 学校名称
                school_field = self.page.locator(
                    f"input[name*='school'][name*='education'][name*='{i}']"
                )
                if await school_field.count() > 0:
                    await school_field.fill(education.school)
                    filled_count += 1
                    self.logger.info(f"Filled school {i}: {education.school}")

                # 专业
                major_field = self.page.locator(
                    f"input[name*='major'][name*='education'][name*='{i}']"
                )
                if await major_field.count() > 0:
                    await major_field.fill(education.major)
                    filled_count += 1
                    self.logger.info(f"Filled major {i}: {education.major}")

                # 学位
                degree_field = self.page.locator(
                    f"select[name*='degree'][name*='education'][name*='{i}']"
                )
                if await degree_field.count() > 0:
                    await degree_field.select_option(education.degree.value)
                    filled_count += 1
                    self.logger.info(f"Filled degree {i}: {education.degree.value}")

            return filled_count

        except Exception as e:
            self.logger.warning(f"Failed to fill education: {e}")
            return filled_count

    async def _fill_projects(self, resume_data: ResumeSchema) -> int:
        """填写项目经验"""
        filled_count = 0
        try:
            if not resume_data.projects:
                return filled_count

            for i, project in enumerate(resume_data.projects):
                # 项目名称
                project_field = self.page.locator(
                    f"input[name*='project_name'][name*='project'][name*='{i}']"
                )
                if await project_field.count() > 0:
                    await project_field.fill(project.name)
                    filled_count += 1
                    self.logger.info(f"Filled project name {i}: {project.name}")

                # 项目描述
                description_field = self.page.locator(
                    f"textarea[name*='description'][name*='project'][name*='{i}']"
                )
                if await description_field.count() > 0:
                    await description_field.fill(project.description)
                    filled_count += 1
                    self.logger.info(f"Filled project description {i}")

            return filled_count

        except Exception as e:
            self.logger.warning(f"Failed to fill projects: {e}")
            return filled_count

    async def _upload_resume(self, pdf_path: str) -> bool:
        """上传简历文件"""
        try:
            # 查找文件上传输入框
            file_input = self.page.locator("input[type='file']")
            if await file_input.count() > 0:
                # 将相对路径转换为绝对路径
                absolute_path = str(Path(pdf_path).absolute())
                await file_input.set_input_files(absolute_path)
                self.logger.info(f"Resume uploaded: {absolute_path}")
                return True
            else:
                self.logger.warning("File input element not found")
                return False

        except Exception as e:
            self.logger.error(f"Failed to upload resume: {e}")
            return False


async def main():
    """测试入口函数"""
    # 配置表单填写器
    config = FormFillerConfig(
        headless=False,  # 显示浏览器界面
        timeout=30
    )

    # 创建表单填写器实例
    filler = AutoFillAgent(config)

    try:
        # 初始化浏览器
        await filler.initialize()

        # 创建测试简历数据
        test_resume = ResumeSchema(
            name="张三",
            email="zhangsan@example.com",
            phone="13800138000",
            summary="5年全栈开发经验，熟悉前后端技术栈",
            skills=["Python", "JavaScript", "React", "Django", "Docker"],
            work_experience=[
                WorkExperience(
                    company="ABC科技有限公司",
                    position="高级前端工程师",
                    start_date="2021-01",
                    end_date="2023-12",
                    description="负责公司核心产品的前端开发"
                )
            ],
            education=[
                Education(
                    school="北京大学",
                    major="计算机科学与技术",
                    degree="本科",
                    start_date="2017-09",
                    end_date="2021-06"
                )
            ],
            projects=[
                ProjectExperience(
                    name="电商平台重构",
                    description="使用React和Node.js重构公司电商平台",
                    technologies=["React", "Node.js", "MongoDB"],
                    role="技术负责人",
                    duration="6个月"
                )
            ]
        )

        # 测试职位URL（使用本地测试页面）
        test_job_url = "file:///D:/x/ai agent/test_page.html"

        # 测试PDF路径（使用相对路径）
        test_pdf_path = "./resumes/test_resume.pdf"

        # 执行自动填写
        result = await filler.auto_fill_form(
            job_url=test_job_url,
            resume_data=test_resume,
            pdf_path=test_pdf_path,
            test_mode=True
        )

        print("\n=== 测试结果 ===")
        print(f"成功: {result.success}")
        print(f"消息: {result.message}")
        print(f"已填写字段数: {result.filled_fields}")
        if result.error:
            print(f"错误: {result.error}")

    except Exception as e:
        print(f"测试过程中发生错误: {e}")
    finally:
        # 清理资源
        await filler.cleanup()


if __name__ == "__main__":
    asyncio.run(main())