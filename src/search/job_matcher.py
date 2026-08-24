"""
职位匹配器模块
抓取 JD 文本并评估简历匹配度
"""

import asyncio
import json
import re
from typing import List, Optional
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field, HttpUrl
from loguru import logger
from openai import OpenAI

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from src.models.schemas import ResumeSchema
from src.models.instruction_schemas import TargetInstructionSchema


class MatchResultSchema(BaseModel):
    """匹配结果数据模型"""
    score: int = Field(ge=0, le=100, description="匹配分数（0-100）")
    is_match: bool = Field(..., description="是否匹配")
    reasons: List[str] = Field(default_factory=list, description="匹配原因")
    missing_skills: List[str] = Field(default_factory=list, description="缺少的技能")
    matched_skills: List[str] = Field(default_factory=list, description="匹配的技能")
    match_summary: str = Field("", description="匹配总结")


class JobMatcherConfig:
    """匹配器配置"""
    def __init__(self, openai_api_key: str = None, base_url: str = None, model: str = None):
        # 未显式传入时从 config.json 的 llm 段读取（环境变量兜底）
        llm_cfg = {}
        try:
            config_path = os.path.join(project_root, "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    llm_cfg = json.load(f).get("llm", {}) or {}
        except Exception:
            pass

        self.openai_api_key = (
            openai_api_key or llm_cfg.get("api_key") or os.getenv("OPENAI_API_KEY") or ""
        )
        self.base_url = base_url or llm_cfg.get("base_url") or os.getenv("OPENAI_BASE_URL") or None
        self.model = model or llm_cfg.get("model") or os.getenv("OPENAI_MODEL") or "gpt-4o"
        self.llm_client = (
            OpenAI(api_key=self.openai_api_key, base_url=self.base_url)
            if self.openai_api_key else None
        )
        self.playwright_timeout = 30
        self.retry_attempts = 3


class JobMatcher:
    """职位匹配器"""

    def __init__(self, config: JobMatcherConfig):
        self.config = config
        self.logger = logger.bind(module="job_matcher")

    async def fetch_jd_text(self, url: str) -> str:
        """
        抓取页面中的 JD 文本内容

        Args:
            url: 招聘页面 URL

        Returns:
            str: JD 文本内容
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    await page.goto(url, timeout=self.config.playwright_timeout)
                    await asyncio.sleep(2)  # 等待页面加载

                    # 获取页面标题和内容
                    title = await page.title()
                    page_text = await page.inner_text("body")

                    # 清理文本
                    jd_text = self._clean_jd_text(f"{title}\n{page_text}")

                    self.logger.info(f"成功抓取 JD: {url}")
                    return jd_text[:5000]  # 限制文本长度

                except Exception as e:
                    self.logger.error(f"抓取 JD 失败: {url}, 错误: {e}")
                    return f"页面加载失败: {str(e)}"
                finally:
                    await browser.close()

        except Exception as e:
            self.logger.error(f"Playwright 启动失败: {e}")
            return f"无法访问页面: {str(e)}"

    def _clean_jd_text(self, text: str) -> str:
        """清理 JD 文本"""
        # 移除导航菜单、页脚等干扰内容
        text = re.sub(r'<[^>]+>', '', text)  # 移除 HTML 标签

        # 移除常见的非招聘内容
        skip_patterns = [
            r'\b社交媒体\b', r'\b社交媒体登录\b', r'\b扫码\b', r'\b下载\b',
            r'\b招聘官登录\b', r'\b创建账户\b', r'\b忘记密码\b',
            r'\b相关搜索\b', r'\b你可能还想搜索\b'
        ]

        for pattern in skip_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        # 清理多余的空白
        text = re.sub(r'\s+', ' ', text).strip()

        # 截取关键段落
        paragraphs = text.split('\n')
        job_description = ""

        # 寻找包含职位描述的部分
        for para in paragraphs:
            if any(keyword in para.lower() for keyword in [
                '职位描述', 'job description', 'responsibilities',
                '任职要求', 'requirements', '我们希望你',
                'responsibilities', 'qualifications', 'about the role'
            ]) and len(para) > 50:
                job_description += para + '\n'
            elif len(para) > 100:  # 保留较长的段落
                job_description += para + '\n'

        return job_description.strip()

    async def evaluate_match(self, resume: ResumeSchema, jd_text: str) -> MatchResultSchema:
        """
        评估简历与 JD 的匹配度

        Args:
            resume: 简历数据
            jd_text: JD 文本

        Returns:
            MatchResultSchema: 匹配结果
        """
        try:
            if not jd_text or len(jd_text) < 100:
                return MatchResultSchema(
                    score=0,
                    is_match=False,
                    reasons=["JD 文本无效或太短"],
                    missing_skills=["无法解析 JD"],
                    matched_skills=[],
                    match_summary="无法分析 JD 文本"
                )

            # 构建评估提示
            evaluation_prompt = self._build_evaluation_prompt(resume, jd_text)

            # 使用 LLM 进行评估
            result = await self._llm_evaluate(evaluation_prompt)

            # 解析结果
            return self._parse_evaluation_result(result, resume)

        except Exception as e:
            self.logger.error(f"匹配评估失败: {e}")
            return MatchResultSchema(
                score=0,
                is_match=False,
                reasons=["评估过程中发生错误"],
                missing_skills=["评估失败"],
                matched_skills=[],
                match_summary=f"评估错误: {str(e)}"
            )

    def _build_evaluation_prompt(self, resume: ResumeSchema, jd_text: str) -> str:
        """构建 LLM 评估提示"""
        # 构建简历概要
        resume_summary = f"""
        姓名: {resume.name}
        邮箱: {resume.email}
        电话: {resume.phone or '未提供'}

        个人简介: {resume.summary}

        技能列表: {', '.join(resume.skills)}

        工作经历:
        {self._format_work_experience(resume.work_experience)}

        教育背景:
        {self._format_education(resume.education)}
        """

        prompt = f"""
        请仔细分析以下求职者简历和职位描述，评估匹配度。

        简历信息:
        {resume_summary}

        职位描述:
        {jd_text}

        请按照以下格式返回 JSON 结果:
        {{
            "score": 0-100的匹配分数,
            "is_match": 是否匹配（布尔值）,
            "reasons": ["匹配原因1", "匹配原因2"],
            "matched_skills": ["已匹配的技能1", "已匹配的技能2"],
            "missing_skills": ["缺少的技能1", "缺少的技能2"],
            "match_summary": "匹配总结（100字以内）"
        }}

        评估标准:
        1. 技能匹配度（40%）: 简历技能是否满足职位要求
        2. 工作经验（30%）: 相关工作经验是否充足
        3. 教育背景（20%）: 学历是否符合要求
        4. 其他因素（10%）: 公司文化契合度、地理位置等

        匹配标准:
        - 分数 >= 80: 强烈推荐
        - 分数 >= 60: 基本匹配
        - 分数 >= 40: 勉强匹配
        - 分数 < 40: 不匹配
        """

        return prompt

    async def _llm_evaluate(self, prompt: str) -> str:
        """使用 LLM 进行评估"""
        try:
            if not self.config.llm_client:
                return "{'error': '未配置 OPENAI_API_KEY，无法进行 LLM 匹配评估'}"
            response = await self.config.llm_client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000
            )
            return response.choices[0].message.content
        except Exception as e:
            self.logger.error(f"LLM 调用失败: {e}")
            return f"{{'error': '{str(e)}'}}"

    def _parse_evaluation_result(self, llm_result: str, resume: ResumeSchema) -> MatchResultSchema:
        """解析 LLM 评估结果"""
        try:
            import json

            # 提取 JSON 部分
            json_start = llm_result.find('{')
            json_end = llm_result.rfind('}') + 1
            json_str = llm_result[json_start:json_end]

            result_data = json.loads(json_str)

            return MatchResultSchema(
                score=result_data.get('score', 0),
                is_match=result_data.get('is_match', False),
                reasons=result_data.get('reasons', []),
                matched_skills=result_data.get('matched_skills', []),
                missing_skills=result_data.get('missing_skills', []),
                match_summary=result_data.get('match_summary', '')
            )

        except Exception as e:
            # 如果 JSON 解析失败，返回默认结果
            return MatchResultSchema(
                score=0,
                is_match=False,
                reasons=["LLM 结果解析失败"],
                missing_skills=[],
                matched_skills=[],
                match_summary=f"解析错误: {str(e)}"
            )

    def _format_work_experience(self, work_experience: List) -> str:
        """格式化工作经历"""
        formatted = ""
        for exp in work_experience:
            formatted += f"- {exp.company} - {exp.position} ({exp.start_date} - {exp.end_date or '至今'})\n"
            formatted += f"  描述: {exp.description}\n"
        return formatted

    def _format_education(self, education: List) -> str:
        """格式化教育背景"""
        formatted = ""
        for edu in education:
            formatted += f"- {edu.school} - {edu.major} ({edu.degree.value}) ({edu.start_date} - {edu.end_date})\n"
        return formatted


async def test_job_matcher():
    """测试函数"""
    config = JobMatcherConfig()
    matcher = JobMatcher(config)

    # 创建测试简历
    from src.models.schemas import ResumeSchema, WorkExperience, Education, ProjectExperience

    resume = ResumeSchema(
        name="张三",
        email="zhangsan@example.com",
        phone="13800138000",
        summary="3年前端开发经验，熟练使用React和TypeScript",
        skills=["React", "TypeScript", "JavaScript", "CSS", "HTML"],
        work_experience=[
            WorkExperience(
                company="ABC科技有限公司",
                position="前端工程师",
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
                description="使用React重构公司电商平台",
                technologies=["React", "Node.js", "MongoDB"],
                role="技术负责人",
                duration="6个月"
            )
        ]
    )

    # 测试 JD 抓取
    test_url = "https://boards.greenhouse.io/autotest/jobs/123456"
    print(f"正在抓取 JD: {test_url}")
    jd_text = await matcher.fetch_jd_text(test_url)
    print(f"JD 文本长度: {len(jd_text)} 字符")

    # 测试匹配评估
    if jd_text and len(jd_text) > 100:
        print("\n开始匹配评估...")
        result = await matcher.evaluate_match(resume, jd_text)

        print(f"\n匹配结果:")
        print(f"匹配分数: {result.score}/100")
        print(f"是否匹配: {result.is_match}")
        print(f"匹配总结: {result.match_summary}")

        if result.matched_skills:
            print(f"\n已匹配的技能:")
            for skill in result.matched_skills:
                print(f"  - {skill}")

        if result.missing_skills:
            print(f"\n缺少的技能:")
            for skill in result.missing_skills:
                print(f"  - {skill}")


if __name__ == "__main__":
    asyncio.run(test_job_matcher())