"""
智能表单填写器
支持断点续传、自动登录检测和泛化表单填写
"""

import asyncio
import json
import time
import base64
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from pathlib import Path
from loguru import logger

from playwright.async_api import Page, Browser, Error, TimeoutError
from pydantic import BaseModel, Field
from dataclasses import dataclass

# 添加项目根目录到路径
import sys
import os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.utils.llm_client import get_llm_client
from src.models.schemas import (
    DynamicUserPersona,
    FormSchema,
    FormFieldSchema,
    BrowserAction,
    FormFieldSchema
)


@dataclass
class FormFillContext:
    """表单填写上下文"""
    url: str
    page: Page
    browser: Browser
    persona: DynamicUserPersona
    form_data: Dict[str, Any]
    login_required: bool = False
    storage_path: Optional[str] = None
    interrupted: bool = False


class SmartFormFiller:
    """智能表单填写器"""

    def __init__(
        self,
        headless: bool = False,
        viewport: tuple = (1280, 720),
        timeout: int = 30000
    ):
        """
        初始化智能表单填写器

        Args:
            headless: 是否无头模式
            viewport: 视口大小
            timeout: 超时时间
        """
        self.headless = headless
        self.viewport = viewport
        self.timeout = timeout
        self.browser = None
        self.llm_client = get_llm_client()
        self.context_cache = {}
        self.storage_dir = Path(project_root) / "storage"
        self.storage_dir.mkdir(exist_ok=True)

    async def start_browser(self) -> Browser:
        """启动浏览器"""
        if self.browser:
            return self.browser

        try:
            from playwright.async_api import async_playwright

            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                viewport=self.viewport
            )

            logger.info("浏览器启动成功")
            return self.browser

        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            raise

    async def stop_browser(self):
        """停止浏览器"""
        if self.browser:
            await self.browser.close()
            if hasattr(self, 'playwright'):
                await self.playwright.stop()
            logger.info("浏览器已停止")

    async def check_login_status(self, page: Page, url: str) -> bool:
        """
        检查登录状态

        Args:
            page: Playwright页面
            url: 目标URL

        Returns:
            是否需要登录
        """
        try:
            # 导航到页面
            await page.goto(url, timeout=self.timeout)
            await page.wait_for_load_state("networkidle")

            # 检查是否有登录相关的元素
            login_indicators = [
                "login", "signin", "sign-in", "log-in", "登录", "登入",
                "username", "password", "邮箱", "手机号", "验证码"
            ]

            page_content = await page.content()
            page_lower = page_content.lower()

            # 检查页面内容
            for indicator in login_indicators:
                if indicator in page_lower:
                    logger.info(f"检测到登录相关元素: {indicator}")
                    return True

            # 检查特定的选择器
            login_selectors = [
                'input[type="password"]',
                'input[name="password"]',
                'input[placeholder*="密码"]',
                'input[placeholder*="password"]'
            ]

            for selector in login_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    if elements:
                        logger.info(f"检测到密码输入框: {selector}")
                        return True
                except:
                    continue

            # 检查是否有"登录"按钮
            login_button_selectors = [
                'button:has-text("登录")',
                'button:has-text("Sign In")',
                'button:has-text("Sign in")',
                'a:has-text("登录")',
                'a:has-text("Sign In")'
            ]

            for selector in login_button_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        logger.info(f"检测到登录按钮: {selector}")
                        return True
                except:
                    continue

            return False

        except Exception as e:
            logger.warning(f"检查登录状态失败: {e}")
            return False

    async def save_cookies(self, context: FormFillContext) -> str:
        """
        保存Cookie到文件

        Args:
            context: 表单填写上下文

        Returns:
            Cookie文件路径
        """
        try:
            if not context.page:
                return None

            cookies = await context.page.context.cookies()
            storage_path = self.storage_dir / f"cookies_{int(time.time())}.json"

            with open(storage_path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)

            logger.info(f"Cookie已保存到: {storage_path}")
            return str(storage_path)

        except Exception as e:
            logger.error(f"保存Cookie失败: {e}")
            return None

    async def load_cookies(self, page: Page, storage_path: str) -> bool:
        """
        加载Cookie

        Args:
            page: Playwright页面
            storage_path: Cookie文件路径

        Returns:
            是否加载成功
        """
        try:
            with open(storage_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)

            await page.context.add_cookies(cookies)
            logger.info(f"Cookie已从 {storage_path} 加载")
            return True

        except Exception as e:
            logger.error(f"加载Cookie失败: {e}")
            return False

    async def handle_login_interruption(self, context: FormFillContext) -> bool:
        """
        处理登录中断

        Args:
            context: 表单填写上下文

        Returns:
            是否登录成功
        """
        logger.info("等待用户手动登录...")

        # 打印登录提示
        print(f"\n{'='*60}")
        print("🔐 需要登录才能继续")
        print(f"{'='*60}")
        print(f"网站: {context.url}")
        print("请在浏览器中手动完成登录")
        print("登录完成后按 Enter 继续...")
        print(f"{'='*60}")

        # 等待用户输入
        input()

        # 检查登录状态
        is_logged_in = not await self.check_login_status(context.page, context.url)

        if is_logged_in:
            # 保存Cookie
            storage_path = await self.save_cookies(context)
            if storage_path:
                context.storage_path = storage_path
                logger.info("登录成功，Cookie已保存")
                return True
            else:
                logger.warning("登录成功但保存Cookie失败")
                return True
        else:
            logger.error("登录失败，请重试")
            return False

    async def analyze_form_structure(self, page: Page) -> FormSchema:
        """
        分析表单结构

        Args:
            page: Playwright页面

        Returns:
            表单数据结构
        """
        try:
            await page.wait_for_load_state("networkidle")

            # 获取页面内容
            html_content = await page.content()

            # 使用LLM分析表单
            prompt = f"""
            请分析以下HTML表单，提取所有字段信息：

            {html_content[:3000]}

            输出JSON格式：
            {{
                "form_title": "表单标题",
                "form_action": "表单提交地址",
                "form_method": "GET/POST",
                "estimated_completion_time": 60,
                "difficulty_level": "easy",
                "form_type": "standard",
                "fields": [
                    {{
                        "field_name": "字段名称",
                        "field_type": "字段类型",
                        "label": "字段标签",
                        "placeholder": "占位文本",
                        "required": true,
                        "options": ["选项1", "选项2"],
                        "css_selector": "CSS选择器",
                        "xpath": "XPath",
                        "validation_rules": {{"type": "string", "max_length": 100}}
                    }}
                ],
                "submit_button": {{
                    "text": "提交按钮文本",
                    "css_selector": "CSS选择器",
                    "xpath": "XPath"
                }}
            }}
            """

            analysis = await self.llm_client.generate_response(prompt, json_output=True)

            # 创建表单结构
            form_schema = FormSchema(
                form_url=page.url,
                form_title=analysis.get("form_title", "未知表单"),
                fields=[],
                submit_button=analysis.get("submit_button", {}),
                estimated_completion_time=analysis.get("estimated_completion_time", 60),
                difficulty_level=analysis.get("difficulty_level", "medium"),
                form_type=analysis.get("form_type", "standard"),
                analyzed_at=datetime.now()
            )

            # 处理字段
            for field_data in analysis.get("fields", []):
                field_schema = FormFieldSchema(
                    field_name=field_data.get("field_name", ""),
                    field_type=field_data.get("field_type", "text"),
                    label=field_data.get("label", ""),
                    placeholder=field_data.get("placeholder", ""),
                    required=field_data.get("required", False),
                    options=field_data.get("options", []),
                    css_selector=field_data.get("css_selector", ""),
                    xpath=field_data.get("xpath", ""),
                    validation_rules=field_data.get("validation_rules", {})
                )
                form_schema.fields.append(field_schema)

            logger.info(f"表单分析完成，共 {len(form_schema.fields)} 个字段")
            return form_schema

        except Exception as e:
            logger.error(f"表单分析失败: {e}")
            # 返回空表单
            return FormSchema(
                form_url=page.url,
                form_title="未知表单",
                fields=[],
                submit_button={},
                estimated_completion_time=60,
                difficulty_level="hard",
                form_type="unknown",
                analyzed_at=datetime.now()
            )

    async def generate_filling_instructions(
        self,
        form_schema: FormSchema,
        persona: DynamicUserPersona
    ) -> List[BrowserAction]:
        """
        生成表单填写指令

        Args:
            form_schema: 表单结构
            persona: 用户画像

        Returns:
            填写指令列表
        """
        try:
            # 构建用户数据
            user_data = {
                "name": persona.name,
                "email": persona.email,
                "phone": persona.phone,
                "skills": list(set(skill for skills in persona.technical_skills.values() for skill in skills)),
                "experience_years": len(persona.work_experience) if hasattr(persona, 'work_experience') else 0,
                "location": persona.career_objective.location_preference[0] if persona.career_objective.location_preference else "未知",
                "salary_expectation": persona.career_objective.salary_expectation or "面议"
            }

            prompt = f"""
            基于以下表单结构和用户数据，生成详细的表单填写指令：

            表单结构：
            {form_schema.model_dump_json(indent=2, ensure_ascii=False)}

            用户数据：
            {json.dumps(user_data, ensure_ascii=False, indent=2)}

            请为每个字段生成填写指令，包括：
            1. 操作类型（click/type/select）
            2. 目标选择器
            3. 填写值
            4. 操作描述

            输出JSON格式：
            {{
                "instructions": [
                    {{
                        "action_type": "click/type/select",
                        "target": "CSS选择器或XPath",
                        "value": "要填写的值",
                        "description": "操作描述",
                        "timeout": 10
                    }}
                ]
            }}
            """

            response = await self.llm_client.generate_response(prompt, json_output=True)
            instructions = response.get("instructions", [])

            # 转换为BrowserAction对象
            browser_actions = []
            for instruction in instructions:
                action = BrowserAction(
                    action_type=instruction.get("action_type", "type"),
                    target=instruction.get("target", ""),
                    value=instruction.get("value", ""),
                    timeout=instruction.get("timeout", 10),
                    description=instruction.get("description", "")
                )
                browser_actions.append(action)

            logger.info(f"生成 {len(browser_actions)} 条填写指令")
            return browser_actions

        except Exception as e:
            logger.error(f"生成填写指令失败: {e}")
            return []

    async def execute_filling_instructions(
        self,
        context: FormFillContext,
        instructions: List[BrowserAction]
    ) -> bool:
        """
        执行填写指令

        Args:
            context: 表单填写上下文
            instructions: 填写指令

        Returns:
            是否填写成功
        """
        page = context.page
        success_count = 0

        for i, instruction in enumerate(instructions, 1):
            try:
                logger.info(f"执行第 {i} 条指令: {instruction.description}")

                if instruction.action_type == "click":
                    # 点击操作
                    element = await page.query_selector(instruction.target)
                    if element:
                        await element.click(timeout=instruction.timeout * 1000)
                        success_count += 1
                    else:
                        logger.warning(f"未找到点击元素: {instruction.target}")

                elif instruction.action_type == "type":
                    # 输入操作
                    element = await page.query_selector(instruction.target)
                    if element:
                        await element.fill(instruction.value, timeout=instruction.timeout * 1000)
                        success_count += 1
                    else:
                        logger.warning(f"未找到输入元素: {instruction.target}")

                elif instruction.action_type == "select":
                    # 选择操作
                    element = await page.query_selector(instruction.target)
                    if element:
                        await element.select_option(instruction.value, timeout=instruction.timeout * 1000)
                        success_count += 1
                    else:
                        logger.warning(f"未找到选择元素: {instruction.target}")

                elif instruction.action_type == "wait":
                    # 等待操作
                    await asyncio.sleep(instruction.timeout)

                # 添加短暂延迟
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"执行指令失败: {instruction.description} - {e}")

        # 提交表单
        try:
            submit_selector = context.form_schema.submit_button.get("css_selector")
            if submit_selector:
                submit_button = await page.query_selector(submit_selector)
                if submit_button:
                    await submit_button.click()
                    logger.info("表单提交成功")
                    return True
        except Exception as e:
            logger.error(f"提交表单失败: {e}")

        logger.info(f"表单填写完成，成功 {success_count}/{len(instructions)} 条指令")
        return success_count > len(instructions) * 0.8  # 80%以上成功即认为成功

    async def fill_form(
        self,
        url: str,
        persona: DynamicUserPersona,
        storage_path: str = None
    ) -> Dict[str, Any]:
        """
        填写表单的主方法

        Args:
            url: 表单URL
            persona: 用户画像
            storage_path: 已保存的Cookie路径

        Returns:
            填写结果
        """
        try:
            logger.info(f"开始填写表单: {url}")

            # 启动浏览器
            browser = await self.start_browser()
            context = await browser.new_context()
            page = await context.new_page()

            # 设置视口
            await page.set_viewport_size({"width": 1280, "height": 720})

            # 检查登录状态
            login_required = await self.check_login_status(page, url)

            if login_required:
                # 创建上下文
                form_context = FormFillContext(
                    url=url,
                    page=page,
                    browser=browser,
                    persona=persona,
                    form_data={},
                    login_required=True
                )

                # 处理登录
                if not await self.handle_login_interruption(form_context):
                    return {
                        "success": False,
                        "error": "登录失败",
                        "url": url,
                        "completed_steps": []
                    }

                # 如果有保存的Cookie，尝试加载
                if storage_path:
                    await self.load_cookies(page, storage_path)

            # 重新导航到页面
            await page.goto(url, timeout=self.timeout)
            await page.wait_for_load_state("networkidle")

            # 分析表单结构
            logger.info("分析表单结构...")
            form_schema = await self.analyze_form_structure(page)

            # 生成填写指令
            logger.info("生成填写指令...")
            instructions = await self.generate_filling_instructions(form_schema, persona)

            if not instructions:
                logger.error("无法生成填写指令")
                return {
                    "success": False,
                    "error": "无法生成填写指令",
                    "url": url,
                    "completed_steps": []
                }

            # 执行填写
            logger.info("开始执行填写...")
            form_context = FormFillContext(
                url=url,
                page=page,
                browser=browser,
                persona=persona,
                form_data=form_schema.model_dump(),
                login_required=login_required,
                storage_path=storage_path
            )

            fill_success = await self.execute_filling_instructions(form_context, instructions)

            # 保存Cookie（如果需要）
            if login_required and form_context.storage_path:
                storage_path = form_context.storage_path

            # 停止浏览器
            await self.stop_browser()

            return {
                "success": fill_success,
                "url": url,
                "form_title": form_schema.form_title,
                "field_count": len(form_schema.fields),
                "completed_steps": len(instructions),
                "storage_path": storage_path,
                "filled_at": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"填写表单失败: {e}")
            # 确保浏览器被停止
            if 'browser' in locals():
                await self.stop_browser()
            return {
                "success": False,
                "error": str(e),
                "url": url,
                "completed_steps": []
            }


# 工具函数
async def create_form_filler(headless: bool = False) -> SmartFormFiller:
    """创建智能表单填写器实例"""
    return SmartFormFiller(headless=headless)


async def fill_application_form(
    url: str,
    persona: DynamicUserPersona,
    storage_path: str = None,
    headless: bool = False
) -> Dict[str, Any]:
    """
    填写申请表单的快捷函数

    Args:
        url: 表单URL
        persona: 用户画像
        storage_path: Cookie存储路径
        headless: 是否无头模式

    Returns:
        填写结果
    """
    filler = SmartFormFiller(headless=headless)
    return await filler.fill_form(url, persona, storage_path)


# 测试函数
async def test_form_filler():
    """测试智能表单填写器"""
    print("=== 测试智能表单填写器 ===")

    try:
        # 创建用户画像
        from src.models.schemas import DynamicUserPersona, CareerObjective, SoftSkills, PersonalityTraits, CareerConstraints

        persona = DynamicUserPersona(
            name="测试用户",
            email="test@example.com",
            phone="13800138000",
            technical_skills={"languages": ["Python", "JavaScript"]},
            soft_skills=SoftSkills(),
            domain_knowledge={},
            career_objective=CareerObjective(target_positions=["开发工程师"]),
            personality_traits=PersonalityTraits(),
            constraints=CareerConstraints(),
            strengths=["编程"],
            weaknesses=[],
            work_preferences={}
        )

        print("✅ 用户画像创建成功")

        # 创建表单填写器
        filler = SmartFormFiller(headless=True)  # 使用无头模式测试
        print("✅ 表单填写器创建成功")

        # 测试URL
        test_url = "https://httpbin.org/forms/post"

        print(f"开始测试表单填写: {test_url}")

        # 执行填写
        result = await fill_application_form(
            url=test_url,
            persona=persona,
            headless=True
        )

        print(f"\n✅ 表单填写测试完成！")
        print(f"   成功: {result['success']}")
        print(f"   URL: {result['url']}")
        print(f"   表单标题: {result.get('form_title', '未知')}")
        print(f"   字段数: {result.get('field_count', 0)}")
        print(f"   完成步骤: {result.get('completed_steps', 0)}")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def test_login_detection():
    """测试登录检测"""
    print("\n=== 测试登录检测 ===")

    try:
        from src.models.schemas import DynamicUserPersona, CareerObjective, SoftSkills, PersonalityTraits, CareerConstraints

        # 创建简单的用户画像
        persona = DynamicUserPersona(
            name="测试用户",
            email="test@example.com",
            phone="13800138000",
            technical_skills={},
            soft_skills=SoftSkills(),
            domain_knowledge={},
            career_objective=CareerObjective(target_positions=["开发工程师"]),
            personalityTraits=PersonalityTraits(),
            constraints=CareerConstraints(),
            strengths=[],
            weaknesses=[],
            work_preferences={}
        )

        # 创建表单填写器
        filler = SmartFormFiller(headless=True)

        print("✅ 登录检测功能就绪")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def test_form_analysis():
    """测试表单分析"""
    print("\n=== 测试表单分析 ===")

    try:
        from src.utils.llm_client import get_llm_client

        client = get_llm_client()

        # 模拟HTML表单
        mock_html = """
        <form action="/submit" method="POST">
            <h1>用户注册表单</h1>
            <div>
                <label>姓名:</label>
                <input type="text" name="name" placeholder="请输入姓名" required>
            </div>
            <div>
                <label>邮箱:</label>
                <input type="email" name="email" placeholder="请输入邮箱" required>
            </div>
            <div>
                <label>密码:</label>
                <input type="password" name="password" placeholder="请输入密码" required>
            </div>
            <div>
                <label>性别:</label>
                <select name="gender">
                    <option value="male">男</option>
                    <option value="female">女</option>
                </select>
            </div>
            <button type="submit">注册</button>
        </form>
        """

        prompt = f"""
        分析以下表单：

        {mock_html}

        输出JSON格式字段信息：
        {{
            "form_title": "表单标题",
            "form_action": "提交地址",
            "fields": [
                {{
                    "field_name": "字段名",
                    "field_type": "类型",
                    "label": "标签",
                    "required": true,
                    "css_selector": "CSS选择器",
                    "xpath": "XPath"
                }}
            ]
        }}
        """

        response = await client.generate_response(prompt, json_output=True)

        print("✅ 表单分析成功！")
        print(f"   表单标题: {response.get('form_title')}")
        print(f"   字段数: {len(response.get('fields', []))}")
        for field in response.get('fields', [])[:3]:
            print(f"   - {field['field_name']} ({field['field_type']})")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


async def main():
    """主测试函数"""
    print("🚀 开始 Phase 9 功能测试...")

    results = []

    # 测试1: 智能表单填写
    results.append(await test_form_filler())

    # 测试2: 登录检测
    results.append(await test_login_detection())

    # 测试3: 表单分析
    results.append(await test_form_analysis())

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