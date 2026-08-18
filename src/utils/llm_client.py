"""
LLM客户端工具
封装OpenAI API调用，支持各种交互模式
"""

import os
import json
import asyncio
from typing import Dict, List, Optional, Any, AsyncGenerator
from datetime import datetime
from loguru import logger

from openai import AsyncOpenAI
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class LLMClient:
    """LLM客户端封装"""

    def __init__(
        self,
        model: str = "gpt-4-turbo-preview",
        api_key: str = None,
        base_url: str = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        timeout: int = 30
    ):
        """
        初始化LLM客户端

        Args:
            model: 使用的模型名称
            api_key: OpenAI API密钥
            base_url: 自定义API基础URL
            temperature: 生成温度
            max_tokens: 最大生成长度
            timeout: 请求超时时间
        """
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        # 初始化OpenAI客户端
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("未提供OpenAI API密钥")

        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or os.getenv("OPENAI_BASE_URL")
        )

    async def generate_response(
        self,
        prompt: str,
        system_prompt: str = None,
        json_output: bool = False,
        messages: List[Dict] = None,
        tools: List[Dict] = None,
        tool_choice: str = None
    ) -> str | Dict:
        """
        生成响应

        Args:
            prompt: 用户提示
            system_prompt: 系统提示
            json_output: 是否要求JSON输出
            messages: 消息历史
            tools: 可用工具
            tool_choice: 工具选择策略

        Returns:
            生成的响应文本或字典
        """
        try:
            # 构建消息列表
            if messages is None:
                messages = []

            if system_prompt:
                messages.insert(0, {"role": "system", "content": system_prompt})

            messages.append({"role": "user", "content": prompt})

            # 构建请求参数
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "timeout": self.timeout
            }

            # 如果要求JSON输出
            if json_output:
                kwargs["response_format"] = {"type": "json_object"}

            # 如果有工具
            if tools:
                kwargs["tools"] = tools
                if tool_choice:
                    kwargs["tool_choice"] = tool_choice

            # 发送请求
            logger.info(f"调用LLM: {self.model}")
            response = await self.client.chat.completions.create(**kwargs)

            # 处理响应
            content = response.choices[0].message.content

            # 如果是JSON输出，尝试解析
            if json_output:
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    logger.warning("JSON输出解析失败，返回原始文本")
                    return content

            return content

        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            raise

    async def generate_structured_response(
        self,
        prompt: str,
        schema: BaseModel,
        system_prompt: str = None
    ) -> BaseModel:
        """
        生成结构化响应

        Args:
            prompt: 用户提示
            schema: Pydantic模型
            system_prompt: 系统提示

        Returns:
            结构化数据对象
        """
        try:
            # 构建JSON Schema
            json_schema = schema.model_json_schema()

            # 构建系统提示
            if system_prompt:
                system_prompt = f"{system_prompt}\n\n请按以下JSON格式输出：\n{json.dumps(json_schema, indent=2, ensure_ascii=False)}"
            else:
                system_prompt = f"请按以下JSON格式输出：\n{json.dumps(json_schema, indent=2, ensure_ascii=False)}"

            # 生成响应
            response = await self.generate_response(
                prompt,
                system_prompt=system_prompt,
                json_output=True
            )

            # 创建对象
            return schema.model_validate(response)

        except Exception as e:
            logger.error(f"结构化响应生成失败: {e}")
            raise

    async def stream_response(
        self,
        prompt: str,
        system_prompt: str = None,
        messages: List[Dict] = None
    ) -> AsyncGenerator[str, None]:
        """
        流式生成响应

        Args:
            prompt: 用户提示
            system_prompt: 系统提示
            messages: 消息历史

        Yields:
            生成的文本片段
        """
        try:
            # 构建消息列表
            if messages is None:
                messages = []

            if system_prompt:
                messages.insert(0, {"role": "system", "content": system_prompt})

            messages.append({"role": "user", "content": prompt})

            # 构建流式请求
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "timeout": self.timeout,
                "stream": True
            }

            # 发送流式请求
            logger.info(f"开始流式生成: {self.model}")
            stream = await self.client.chat.completions.create(**kwargs)

            # 处理流式响应
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logger.error(f"流式生成失败: {e}")
            raise

    async def generate_with_retry(
        self,
        prompt: str,
        max_retries: int = 3,
        **kwargs
    ) -> str | Dict:
        """
        带重试机制的生成

        Args:
            prompt: 用户提示
            max_retries: 最大重试次数
            **kwargs: 其他generate_response参数

        Returns:
            生成的响应
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                return await self.generate_response(prompt, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(f"第{attempt + 1}次尝试失败: {e}")

                # 等待一段时间后重试
                await asyncio.sleep(2 ** attempt)

        logger.error(f"所有重试失败，最后错误: {last_error}")
        raise last_error

    async def batch_generate(
        self,
        prompts: List[str],
        system_prompt: str = None,
        concurrent_limit: int = 5
    ) -> List[str]:
        """
        批量生成响应

        Args:
            prompts: 提示列表
            system_prompt: 系统提示
            concurrent_limit: 并发限制

        Returns:
            响应列表
        """
        semaphore = asyncio.Semaphore(concurrent_limit)
        tasks = []

        async def generate_with_semaphore(prompt: str) -> str:
            async with semaphore:
                return await self.generate_response(prompt, system_prompt=system_prompt)

        # 创建所有任务
        for prompt in prompts:
            task = asyncio.create_task(generate_with_semaphore(prompt))
            tasks.append(task)

        # 等待所有任务完成
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"第{i + 1}个请求失败: {result}")
                final_results.append(f"[生成失败: {result}]")
            else:
                final_results.append(result)

        return final_results

    async def evaluate_match(
        self,
        persona: Dict,
        job_description: str,
        threshold: float = 70.0
    ) -> Dict:
        """
        评估匹配度

        Args:
            persona: 用户画像
            job_description: 职位描述
            threshold: 匹配阈值

        Returns:
            匹配结果
        """
        prompt = f"""
        请评估以下用户与职位的匹配度。

        用户画像：
        {json.dumps(persona, ensure_ascii=False, indent=2)}

        职位描述：
        {job_description}

        请从以下维度进行评估：
        1. 技能匹配度（权重40%）
        2. 经验匹配度（权重30%）
        3. 职业目标匹配度（权重20%）
        4. 薪资期望匹配度（权重10%）

        输出JSON格式：
        {{
            "match_score": 0-100的匹配分数,
            "match_level": "优秀/良好/一般/不匹配",
            "strengths": ["优势匹配点1", "优势匹配点2"],
            "weaknesses": ["劣势不匹配点1", "劣势不匹配点2"],
            "recommendation": "推荐/考虑/不推荐",
            "reason": "详细匹配分析",
            "negotiation_points": ["可协商的要点"]
        }}
        """

        result = await self.generate_response(prompt, json_output=True)
        result["is_qualified"] = result["match_score"] >= threshold
        return result

    async def extract_form_fields(self, html_content: str) -> Dict:
        """
        从HTML中提取表单字段

        Args:
            html_content: HTML内容

        Returns:
            表单字段信息
        """
        prompt = f"""
        请从以下HTML中提取所有表单字段信息：

        {html_content[:4000]}  # 限制长度避免超过token限制

        请输出JSON格式，包含：
        {{
            "form_title": "表单标题",
            "form_action": "表单提交地址",
            "fields": [
                {{
                    "name": "字段名称",
                    "type": "字段类型",
                    "label": "字段标签",
                    "required": true/false,
                    "options": ["选项1", "选项2"] (如果是select/radio),
                    "css_selector": "CSS选择器",
                    "xpath": "XPath",
                    "validation_rules": {{"规则": "要求"}}
                }}
            ]
        }}
        """

        return await self.generate_response(prompt, json_output=True)

    async def generate_form_filling_instructions(
        self,
        field_info: Dict,
        user_data: Dict
    ) -> List[Dict]:
        """
        生成表单填写指令

        Args:
            field_info: 字段信息
            user_data: 用户数据

        Returns:
            填写指令列表
        """
        prompt = f"""
        基于以下字段信息和用户数据，生成表单填写指令：

        字段信息：
        {json.dumps(field_info, ensure_ascii=False, indent=2)}

        用户数据：
        {json.dumps(user_data, ensure_ascii=False, indent=2)}

        为每个字段生成填写指令：
        {{
            "field_name": "字段名",
            "action": "click/type/select",
            "value": "要填写的值",
            "selector": "CSS选择器",
            "description": "操作描述",
            "validation": "验证方法"
        }}
        """

        instructions = await self.generate_response(prompt, json_output=True)
        if isinstance(instructions, dict) and "instructions" in instructions:
            return instructions["instructions"]
        return instructions


# 全局客户端实例
_client_instance = None


def get_llm_client() -> LLMClient:
    """获取全局LLM客户端实例"""
    global _client_instance
    if _client_instance is None:
        _client_instance = LLMClient()
    return _client_instance


def create_llm_client(**kwargs) -> LLMClient:
    """创建新的LLM客户端"""
    return LLMClient(**kwargs)