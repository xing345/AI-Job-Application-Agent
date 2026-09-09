"""
简历解析模块
使用 OCR 和 LLM 解析 PDF 简历文件
"""

import asyncio
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from loguru import logger
import re
import json

# Pydantic for data validation
from src.models.schemas import (
    ResumeSchema, WorkExperience, Education, ProjectExperience, EducationLevel,
)


# ---------------------------------------------------------------------------
# 真实文本提取辅助函数（同步阻塞实现，通过 asyncio.to_thread 放到线程池执行）
# ---------------------------------------------------------------------------
def _extract_text_from_pdf_file(file_path: str) -> str:
    """从 PDF 文件提取真实文本：优先 pdfplumber，无结果/失败时回退 PyPDF2。

    Raises:
        ValueError: 文本库缺失、文件无法读取、或 PDF 无文本层（扫描件/图片型 PDF）时抛出中文错误。
    """
    text = ""

    # 第一优先：pdfplumber（对中文简历版面还原较好）
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
        text = "\n".join(pages).strip()
    except ImportError:
        logger.warning("未安装 pdfplumber，将直接使用 PyPDF2 提取 PDF 文本")
    except Exception as e:
        logger.warning(f"pdfplumber 提取 PDF 文本失败，尝试回退 PyPDF2: {e}")

    # 回退：PyPDF2
    if not text:
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(file_path)
            pages = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
            text = "\n".join(pages).strip()
        except ImportError:
            raise ValueError(
                "无法提取 PDF 文本：未安装 pdfplumber 或 PyPDF2，请先执行 pip install -r requirements.txt"
            ) from None
        except Exception as e:
            raise ValueError(f"无法读取 PDF 文件（可能已损坏或加密）: {e}") from e

    if not text:
        raise ValueError(
            "无法从 PDF 中提取到任何文本内容：文件可能为扫描件或图片型 PDF，"
            "请提供包含文本层的 PDF 简历"
        )

    return text


def _read_text_file(file_path: str) -> str:
    """读取 .txt 简历文本：优先 UTF-8，失败回退 GB18030（兼容常见中文编码）"""
    with open(file_path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gb18030", errors="replace")


def _extract_text_from_docx_file(file_path: str) -> str:
    """从 .docx 简历提取文本：读取段落与表格"""
    try:
        from docx import Document
    except ImportError:
        raise ValueError(
            "解析 .docx 简历需要 python-docx，请先执行 pip install -r requirements.txt"
        ) from None

    doc = Document(file_path)
    parts = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


class MockPDFParser:
    """模拟 PDF 解析器（仅供显式调用 use_mock=True 时的测试工具，真实流程不使用）"""

    def __init__(self):
        self.logger = logger.bind(module="resume_parser")

    async def parse_text_from_pdf(self, pdf_path: str) -> str:
        """从模拟 PDF 提取文本"""
        # 返回固定的测试文本
        return """
        张三
        电话：13800138000
        邮箱：zhangsan@example.com

        求职意向：前端开发工程师，专注于 React 和 Vue 技术栈

        工作经历
        某科技有限公司 - 前端开发工程师 (2022.01 - 2024.01)
        负责公司核心产品的前端开发，使用 React 和 TypeScript 构建用户界面

        创新互联网公司 - 初级前端开发 (2020.06 - 2021.12)
        参与多个Web应用开发，学习现代前端技术栈

        教育经历
        XX大学 - 计算机科学与技术 - 本科 (2016.09 - 2020.06)

        项目经验
        企业管理系统：使用 React 和 Ant Design 开发的企业级管理平台
        技术栈：React, TypeScript, Ant Design, Redux

        电商平台：基于 Vue.js 的前后端分离电商平台
        技术栈：Vue.js, Vuex, Element UI, Node.js

        技能
        JavaScript, TypeScript, React, Vue, HTML, CSS, Webpack, Git, npm, RESTful API
        """

class ResumeParser:
    """简历解析器"""

    def __init__(self, use_mock: bool = False):
        """初始化简历解析器。

        Args:
            use_mock: 是否强制使用 MockPDFParser（仅供显式测试），
                      默认 False 表示对真实文件做文本提取。
        """
        self.logger = logger.bind(module="resume_parser")
        self.use_mock = use_mock
        self.pdf_parser = MockPDFParser() if use_mock else None

    async def parse_pdf(self, pdf_path: str) -> Optional[ResumeSchema]:
        """
        解析简历文件

        Args:
            pdf_path: 简历文件路径（支持 .pdf / .txt / .docx）

        Returns:
            ResumeSchema: 解析后的简历数据，失败返回 None
        """
        try:
            self.logger.info(f"开始解析简历: {pdf_path}")

            # 检查文件是否存在
            if not os.path.exists(pdf_path):
                self.logger.error(f"简历文件不存在: {pdf_path}")
                return None

            # 提取文本（use_mock=True 仅供显式测试；默认对真实文件做提取）
            if self.use_mock:
                text = await self.pdf_parser.parse_text_from_pdf(pdf_path)
            else:
                text = await self._extract_text_from_file(pdf_path)

            if not text:
                self.logger.error(
                    f"无法从简历文件中提取到任何文本内容: {pdf_path}（文件可能为空或格式不支持）"
                )
                return None

            # 解析简历结构
            resume_data = await self._parse_resume_structure(text)

            # 身份信息缺失时明确失败（绝不回填虚构的姓名/邮箱去投递）
            if not (resume_data.get("name") or "").strip() or not (resume_data.get("email") or "").strip():
                self.logger.error(
                    f"未能从简历中识别出姓名或邮箱: {pdf_path}。"
                    "请提供包含清晰姓名与联系邮箱的简历文件，或先用 LLM 结构化解析。"
                )
                return None

            # 创建 Pydantic 模型
            resume = self._create_resume_schema(resume_data)

            self.logger.info(f"简历解析成功: {resume.name if resume else '未知'}")
            return resume

        except Exception as e:
            self.logger.error(f"解析简历时出错: {e}")
            return None

    async def _extract_text_from_pdf(self, pdf_path: str) -> str:
        """从 PDF 文件提取真实文本（pdfplumber 优先，失败回退 PyPDF2）"""
        return await asyncio.to_thread(_extract_text_from_pdf_file, pdf_path)

    async def _extract_text_from_file(self, file_path: str) -> str:
        """按扩展名提取简历文件文本：.pdf / .txt / .docx，其余格式抛出明确错误"""
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            return await asyncio.to_thread(_extract_text_from_pdf_file, file_path)
        if ext == ".txt":
            return await asyncio.to_thread(_read_text_file, file_path)
        if ext == ".docx":
            return await asyncio.to_thread(_extract_text_from_docx_file, file_path)
        raise ValueError(
            f"暂不支持该简历文件格式: {ext or '（无扩展名）'}，目前仅支持 .pdf / .txt / .docx 简历文件"
        )

    async def _parse_resume_structure(self, text: str) -> Dict[str, Any]:
        """解析简历结构"""
        # 简化的简历解析逻辑
        # 实际应用中可以使用更复杂的 NLP 模型

        data = {
            "name": self._extract_name(text),
            "phone": self._extract_phone(text),
            "email": self._extract_email(text),
            "summary": self._extract_career_objective(text),
            "work_experience": self._extract_work_experience(text),
            "education": self._extract_education(text),
            "projects": self._extract_project_experience(text),
            "skills": self._extract_skills(text)
        }

        return data

    def _extract_name(self, text: str) -> str:
        """提取姓名"""
        # 尝试多种模式匹配姓名
        patterns = [
            r'姓名[：:]\s*([^\n]+)',
            r'名字[：:]\s*([^\n]+)',
            r'^\s*([^\n]{2,4})[ \t]*\n',  # 首行(允许缩进)可能是姓名
            r'([A-Za-z一-龥]{2,4})[，,]\s*电话',  # 姓名后跟电话
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                name = match.group(1).strip()
                if len(name) >= 2 and len(name) <= 20:
                    return name

        # 识别不到姓名时返回空串（绝不用虚构姓名冒充真实简历）
        return ""

    def _extract_phone(self, text: str) -> str:
        """提取电话号码"""
        phone_pattern = r'(1[3-9]\d{9})'  # 中国手机号
        match = re.search(phone_pattern, text)
        return match.group(1) if match else ""

    def _extract_email(self, text: str) -> str:
        """提取邮箱"""
        email_pattern = r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
        match = re.search(email_pattern, text)
        return match.group(1) if match else ""

    def _extract_career_objective(self, text: str) -> str:
        """提取求职意向"""
        # 查找求职意向相关内容
        objective_patterns = [
            r'求职意向[：:]\s*([^\n]+)',
            r'意向岗位[：:]\s*([^\n]+)',
            r'目标职位[：:]\s*([^\n]+)',
            r'期望职位[：:]\s*([^\n]+)',
        ]

        for pattern in objective_patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                return match.group(1).strip()

        # 没有明确求职意向时返回空串，不再填充虚构文案
        return ""

    def _extract_work_experience(self, text: str) -> List[Dict[str, str]]:
        """提取工作经历"""
        work_experiences = []

        # 查找工作经历部分
        work_section = self._find_section(text, "工作经历", "工作经验", "工作", "实习")
        if not work_section:
            return []

        # 使用正则表达式提取每条工作经历
        # 简化的格式：公司名称 - 职位 - 时间 - 描述
        pattern = r'([^\n]+)\s*[-–]\s*([^\n]+)\s*\(([^)]+)\)\s*\n([\s\S]*?)(?=\n\n|\n[A-Z一-龥]|$)'

        matches = re.finditer(pattern, work_section)

        for match in matches:
            company = match.group(1).strip()
            position = match.group(2).strip()
            time_period = match.group(3).strip()
            description = match.group(4).strip()

            if company and position:
                work_experiences.append({
                    "company": company,
                    "position": position,
                    "start_date": self._parse_date(time_period),
                    "end_date": self._parse_date(time_period, is_end=True),
                    "description": description[:500]  # 限制描述长度
                })

        return work_experiences

    def _extract_education(self, text: str) -> List[Dict[str, str]]:
        """提取教育经历"""
        educations = []

        # 查找教育经历部分
        education_section = self._find_section(text, "教育经历", "教育背景", "学历", "学校")
        if not education_section:
            return []

        # 提取教育信息（末尾条目可能没有换行）
        pattern = r'([^\n]+)\s*\(([^)]+)\)'

        matches = re.finditer(pattern, education_section)

        for match in matches:
            pre_paren = match.group(1).strip()
            time_period = match.group(2).strip()

            # 按 " - " 拆分：学校 - 专业 - 学位 或 学校 - 学位
            parts = [p.strip() for p in re.split(r'[-—]', pre_paren) if p.strip()]
            if not parts:
                continue
            school = parts[0]
            degree = parts[-1] if len(parts) >= 2 else "其他"
            major = parts[1] if len(parts) >= 3 else ""

            if school and degree:
                educations.append({
                    "school": school,
                    "degree": degree,
                    "major": major,
                    "start_date": self._parse_date(time_period),
                    "end_date": self._parse_date(time_period, is_end=True),
                    "description": ""
                })

        return educations

    def _extract_project_experience(self, text: str) -> List[Dict[str, Any]]:
        """提取项目经验"""
        projects = []

        # 查找项目经验部分
        project_section = self._find_section(text, "项目经验", "项目", "项目经历")
        if not project_section:
            return []

        # 提取项目信息（项目名不跨行）
        pattern = r'([^：:\n]+)[：:]\s*([^\n]+)\s*\n([\s\S]*?)(?=\n\n|\n[A-Z一-龥]|$)'

        matches = re.finditer(pattern, project_section)

        for match in matches:
            project_name = match.group(1).strip()
            tech_desc = match.group(2).strip()
            description = match.group(3).strip()

            if project_name:
                technologies = self._extract_technologies(tech_desc)
                projects.append({
                    "name": project_name,
                    "description": description[:500],
                    "technologies": technologies,
                    "role": "团队成员",  # 默认角色（schema 必填）
                    "duration": "未注明"  # 默认时长（schema 必填）
                })

        return projects

    def _extract_skills(self, text: str) -> List[str]:
        """提取技能列表"""
        skills = []

        # 查找技能部分
        skills_section = self._find_section(text, "技能", "专业技能", "技术栈", "掌握技能")
        if not skills_section:
            return []

        # 去掉开头的标题（如 "技能：" 或 "技能"）
        content = re.sub(r'^[^,，、\n：:]*[：:]?', '', skills_section)

        # 按逗号/顿号/空白分隔技能
        for skill in re.split(r'[,，、\s]+', content):
            skill = skill.strip()
            if skill and len(skill) > 1 and skill not in skills:
                skills.append(skill)

        return skills[:50]  # 限制技能数量

    def _extract_technologies(self, text: str) -> List[str]:
        """提取技术栈"""
        technologies = []

        # 常见技术关键词
        tech_keywords = [
            'JavaScript', 'TypeScript', 'React', 'Vue', 'Angular', 'HTML', 'CSS',
            'Python', 'Java', 'C++', 'C#', 'Go', 'Rust', 'PHP', 'Ruby',
            'Node.js', 'Express', 'Django', 'Flask', 'Spring', 'ASP.NET',
            'MySQL', 'PostgreSQL', 'MongoDB', 'Redis', 'Oracle',
            'Git', 'Docker', 'Kubernetes', 'AWS', 'Azure', 'Linux', 'Windows'
        ]

        found_techs = []
        for tech in tech_keywords:
            if tech.lower() in text.lower():
                found_techs.append(tech)

        return found_techs

    def _find_section(self, text: str, *section_names: str) -> Optional[str]:
        """查找简历中的特定部分"""
        for name in section_names:
            # 优先匹配 "名称：内容" 形式，其次匹配独占一行的标题（如 "工作经历" 无冒号）
            for sep in ('[：:]', ''):
                pattern = f'{name}{sep}[\\s]*([^\\n]*)'
                match = re.search(pattern, text)
                if match:
                    section_start = match.start()
                    # 查找下一个部分或文档结束
                    next_section = text.find('\n\n', section_start)
                    section_end = next_section if next_section != -1 else len(text)
                    return text[section_start:section_end]

        return None

    def _parse_date(self, date_str: str, is_end: bool = False) -> str:
        """解析日期字符串"""
        # 简化的日期解析
        if not date_str:
            return ""

        # 处理如 "2020.01 - 2024.01" 或 "2020-01 至 2024-01" 格式
        if '至' in date_str or '-' in date_str:
            parts = date_str.replace('至', '-').split('-')
            if len(parts) >= 2:
                year_month = parts[1].strip() if is_end else parts[0].strip()
                return year_month

        # 处理年份格式
        year_pattern = r'(\d{4})'
        match = re.search(year_pattern, date_str)
        if match:
            return match.group(1) + (".01" if not is_end else ".12")

        return date_str

    def _create_resume_schema(self, data: Dict[str, Any]) -> ResumeSchema:
        """创建简历 Pydantic 模型"""
        # 转换工作经历
        work_experiences = []
        for work in data.get("work_experience", []):
            work_experiences.append(WorkExperience(
                company=work.get("company", ""),
                position=work.get("position", ""),
                start_date=work.get("start_date", ""),
                end_date=work.get("end_date", ""),
                description=work.get("description", "")
            ))

        # 转换教育经历（degree 必须是 EducationLevel 枚举值，非法值兜底为"其他"）
        valid_degrees = {level.value for level in EducationLevel}
        educations = []
        for edu in data.get("education", []):
            degree = edu.get("degree", "")
            if degree not in valid_degrees:
                degree = "其他"
            educations.append(Education(
                school=edu.get("school", ""),
                degree=degree,
                major=edu.get("major", ""),
                start_date=edu.get("start_date", ""),
                end_date=edu.get("end_date", ""),
                description=edu.get("description", "")
            ))

        # 转换项目经历
        projects = []
        for proj in data.get("projects", []):
            projects.append(ProjectExperience(
                name=proj.get("name", ""),
                description=proj.get("description", ""),
                technologies=proj.get("technologies", []),
                role=proj.get("role", "团队成员"),
                duration=proj.get("duration", "未注明")
            ))

        # 创建简历对象
        return ResumeSchema(
            name=data.get("name", "未知"),
            phone=data.get("phone", ""),
            email=data.get("email", ""),
            summary=data.get("summary", ""),
            skills=data.get("skills", []),
            work_experience=work_experiences,
            education=educations,
            projects=projects
        )


# 导出函数
async def parse_pdf(pdf_path: str) -> Optional[ResumeSchema]:
    """解析简历文件的便捷函数（真实提取模式，不使用模拟数据）"""
    parser = ResumeParser(use_mock=False)
    return await parser.parse_pdf(pdf_path)


# 测试函数
async def test_resume_parser():
    """测试简历解析器"""
    print("=== 简历解析器测试 ===\n")

    # 创建解析器
    parser = ResumeParser()

    # 创建测试文本
    test_text = """
    张三
    电话：13800138000
    邮箱：zhangsan@example.com

    求职意向：前端开发工程师

    工作经历
    某科技有限公司 - 前端开发工程师 (2022.01 - 2024.01)
    负责公司核心产品的前端开发，使用 React 和 TypeScript 构建用户界面

    创新互联网公司 - 初级前端开发 (2020.06 - 2021.12)
    参与多个Web应用开发，学习现代前端技术栈

    教育经历
    XX大学 - 计算机科学与技术 - 本科 (2016.09 - 2020.06)

    项目经验
    企业管理系统：使用 React 和 Ant Design 开发的企业级管理平台
    技术栈：React, TypeScript, Ant Design, Redux

    电商平台：基于 Vue.js 的前后端分离电商平台
    技术栈：Vue.js, Vuex, Element UI, Node.js

    技能
    JavaScript, TypeScript, React, Vue, HTML, CSS, Webpack, Git
    """

    # 解析文本
    resume_data = await parser._parse_resume_structure(test_text)
    print(f"解析结果：{json.dumps(resume_data, indent=2, ensure_ascii=False)}")

    # 创建 Schema
    resume = parser._create_resume_schema(resume_data)
    print(f"\n简历对象：{resume.name}")


if __name__ == "__main__":
    asyncio.run(test_resume_parser())