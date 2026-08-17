"""
邮件监听模块
使用 Gmail API 监听邮件并进行分类和信息提取
"""

import asyncio
import base64
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from email.message import EmailMessage
from dataclasses import dataclass
from loguru import logger
import re

# Gmail API
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# OpenAI for LLM
from openai import OpenAI

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from src.models.interview_schemas import EmailCategorySchema, InterviewDetailSchema


@dataclass
class EmailMessageData:
    """邮件数据类"""
    id: str
    thread_id: str
    subject: str
    from_name: str
    from_email: str
    date: datetime
    body: str
    labels: List[str]
    read: bool = False


class EmailListenerConfig:
    """邮件监听器配置"""
    def __init__(self):
        self.gmail_api_key = "your_gmail_api_key_here"
        self.openai_api_key = "your_openai_api_key_here"
        self.llm_client = OpenAI(api_key=self.openai_api_key)
        self.poll_interval = 300  # 轮询间隔（秒）
        self.max_emails_per_poll = 50
        self.search_query = "from:careers@ from:careers- from:recruiting@ from:noreply@ after:{after_date}"


class MockEmailData:
    """模拟邮件数据（用于测试）"""

    @staticmethod
    def get_mock_emails() -> List[EmailMessageData]:
        """获取模拟邮件数据"""
        now = datetime.now()

        mock_emails = [
            EmailMessageData(
                id="mock_1",
                thread_id="thread_1",
                subject="面试邀请 - 字节跳动 - 前端工程师",
                from_name="字节跳动招聘",
                from_email="careers@bytedance.com",
                date=now - timedelta(hours=2),
                body="""
                <h2>面试邀请</h2>
                <p>您好，</p>
                <p>感谢您申请字节跳动的前端工程师职位。我们很高兴地通知您，您的简历通过了初筛，邀请您参加技术面试。</p>
                <h3>面试详情</h3>
                <ul>
                    <li><strong>面试时间：</strong>2024年1月15日 14:00 - 15:00</li>
                    <li><strong>面试类型：</strong>技术面试</li>
                    <li><strong>面试方式：</strong>线上面试（腾讯会议）</li>
                    <li><strong>会议链接：</strong>https://meeting.tencent.com/dm/ABCDEFG</li>
                    <li><strong>面试官：</strong>技术主管李明</li>
                </ul>
                <p>请提前 10 分钟进入会议，并准备好电脑环境。</p>
                """,
                labels=["IMPORTANT", "CATEGORY_SOCIAL"],
                read=False
            ),
            EmailMessageData(
                id="mock_2",
                thread_id="thread_2",
                subject="在线测评 - 腾讯 - Web 开发工程师",
                from_name="腾讯招聘系统",
                from_email="noreply@tencent.com",
                date=now - timedelta(hours=5),
                body="""
                <h2>在线测评通知</h2>
                <p>您好，</p>
                <p>您已成功申请腾讯的 Web 开发工程师职位，需要进行在线编程测试。</p>
                <h3>测试详情</h3>
                <ul>
                    <li><strong>测试时间：</strong>2024年1月14日 10:00 - 12:00</li>
                    <li><strong>测试时长：</strong>120分钟</li>
                    <li><strong>测试平台：</strong>在线编程平台</li>
                    <li><strong>测试链接：</strong>https://exam.tencent.com/portal/test/123456</li>
                </ul>
                <p>请在测试开始前 15 分钟登录系统。</p>
                """,
                labels=["IMPORTANT"],
                read=False
            ),
            EmailMessageData(
                id="mock_3",
                thread_id="thread_3",
                subject="感谢您的申请 - 阿里巴巴",
                from_name="阿里巴巴招聘团队",
                from_email="recruiting@alibaba.com",
                date=now - timedelta(days=1),
                body="""
                <h2>感谢您的申请</h2>
                <p>您好，</p>
                <p>感谢您申请阿里巴巴的前端开发工程师职位。我们收到您的申请后已经仔细审核了您的简历。</p>
                <p>很遗憾，您的背景与当前职位的要求不够匹配，我们将您的申请存档。未来有合适的职位会再次考虑。</p>
                <p>祝您求职顺利！</p>
                """,
                labels=["CATEGORY_PROMOTIONS"],
                read=True
            )
        ]

        return mock_emails


class EmailListener:
    """邮件监听器"""

    def __init__(self, config: EmailListenerConfig):
        self.config = config
        self.last_checked = datetime.now() - timedelta(days=1)
        self.logger = logger.bind(module="email_listener")

    async def start_listening(self):
        """开始监听邮件"""
        self.logger.info("开始监听邮件...")

        while True:
            try:
                # 检查新邮件
                new_emails = await self.check_new_emails()

                # 处理新邮件
                for email in new_emails:
                    await self.process_email(email)

                # 等待下一次检查
                await asyncio.sleep(self.config.poll_interval)

            except Exception as e:
                self.logger.error(f"邮件监听发生错误: {e}")
                await asyncio.sleep(60)  # 错误等待 60 秒

    async def check_new_emails(self) -> List[EmailMessageData]:
        """检查新邮件"""
        try:
            # 如果使用模拟数据
            if self.config.gmail_api_key == "your_gmail_api_key_here":
                return self._get_mock_new_emails()

            # 实际使用 Gmail API
            service = build('gmail', 'v1', credentials=None)
            query = self.config.search_query.format(
                after_date=self.last_checked.strftime('%Y/%m/%d')
            )

            # 搜索邮件
            result = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=self.config.max_emails_per_poll
            ).execute()

            messages = result.get('messages', [])

            new_emails = []
            for msg in messages:
                email_data = await self._get_email_content(msg['id'])
                new_emails.append(email_data)

            self.logger.info(f"找到 {len(new_emails)} 封新邮件")
            return new_emails

        except Exception as e:
            self.logger.error(f"检查新邮件失败: {e}")
            return []

    def _get_mock_new_emails(self) -> List[EmailMessageData]:
        """获取模拟新邮件"""
        mock_emails = MockEmailData.get_mock_emails()

        # 返回比上次检查时间更新的邮件
        return [email for email in mock_emails
                if email.date > self.last_checked and not email.read]

    async def _get_email_content(self, message_id: str) -> EmailMessageData:
        """获取邮件内容"""
        # 这里应该是实际的 Gmail API 调用
        # 为了演示，返回模拟数据
        mock_emails = MockEmailData.get_mock_emails()
        for email in mock_emails:
            if email.id == message_id:
                return email
        return None

    async def process_email(self, email: EmailMessageData):
        """处理单封邮件"""
        try:
            self.logger.info(f"处理邮件: {email.subject}")

            # 解析邮件内容
            category_schema = await self.parse_email_content(email.body)

            # 更新邮件状态
            email.read = True

            # 处理不同类型的邮件
            if category_schema.category == 'INTERVIEW_INVITE':
                self.logger.info(f"发现面试邀请: {category_schema.company_name}")
                # 这里可以触发日历同步
                await self._handle_interview_invite(category_schema)
            elif category_schema.category == 'ONLINE_TEST':
                self.logger.info(f"发现在线测评: {category_schema.company_name}")
                await self._handle_online_test(category_schema)
            elif category_schema.category == 'REJECTED':
                self.logger.info(f"收到拒信: {category_schema.company_name}")
                await self._handle_rejection(category_schema)
            else:
                self.logger.info(f"其他类型邮件: {category_schema.category}")

        except Exception as e:
            self.logger.error(f"处理邮件失败: {email.subject}, 错误: {e}")

    async def parse_email_content(self, email_body: str) -> EmailCategorySchema:
        """解析邮件内容并分类"""
        try:
            # 清理邮件内容
            clean_body = self._clean_email_body(email_body)

            # 构建分析提示
            analysis_prompt = self._build_analysis_prompt(clean_body)

            # 使用 LLM 分析
            result = await self._llm_analyze(analysis_prompt)

            # 解析结果
            return self._parse_analysis_result(result)

        except Exception as e:
            self.logger.error(f"邮件解析失败: {e}")
            return EmailCategorySchema(
                category='OTHER',
                company_name='未知',
                summary='解析失败',
                confidence_score=0.0
            )

    def _clean_email_body(self, body: str) -> str:
        """清理邮件内容"""
        # 移除 HTML 标签
        import re
        body = re.sub(r'<[^>]+>', '', body)

        # 移除多余的空白
        body = re.sub(r'\s+', ' ', body).strip()

        # 移除签名
        if '---' in body:
            body = body.split('---')[0].strip()

        return body

    def _build_analysis_prompt(self, body: str) -> str:
        """构建分析提示"""
        prompt = f"""
        请分析以下邮件内容，判断其类型并提取相关信息。请返回 JSON 格式的结果。

        邮件内容:
        {body}

        返回格式:
        {{
            "category": "INTERVIEW_INVITE | ONLINE_TEST | REJECTED | OTHER",
            "company_name": "公司名称",
            "summary": "邮件内容摘要（50字以内）",
            "confidence_score": 0.0-1.0之间的置信度,
            "interview_details": {{
                "job_title": "职位名称",
                "company_name": "公司名称",
                "interview_type": "技术面试 | 电话初筛 | 现场面试 | 视频面试 | HR面试 | 终面 | 编程测试 | 测评 | 其他",
                "interview_datetime": "ISO 格式的日期时间",
                "duration_minutes": 面试时长（分钟）,
                "location_type": "ONLINE | ONSITE | PHONE",
                "meeting_link": "会议链接（如果有）",
                "contact_name": "联系人姓名",
                "contact_email": "联系人邮箱",
                "contact_phone": "联系人电话",
                "notes": "备注信息"
            }}
        }}

        分类标准:
        - INTERVIEW_INVITE: 明确包含面试邀请、面试时间、面试官等信息
        - ONLINE_TEST: 包含在线测试、编程考试、测评等要求
        - REJECTED: 明确表示申请被拒绝、不合适等信息
        - OTHER: 其他类型邮件
        """

        return prompt

    async def _llm_analyze(self, prompt: str) -> str:
        """使用 LLM 分析邮件"""
        try:
            response = await self.config.llm_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000
            )
            return response.choices[0].message.content
        except Exception as e:
            self.logger.error(f"LLM 分析失败: {e}")
            return '{"error": "LLM 调用失败"}'

    def _parse_analysis_result(self, llm_result: str) -> EmailCategorySchema:
        """解析 LLM 分析结果"""
        try:
            import json

            # 提取 JSON 部分
            json_start = llm_result.find('{')
            json_end = llm_result.rfind('}') + 1
            json_str = llm_result[json_start:json_end]

            result_data = json.loads(json_str)

            # 构建面试详情（如果有）
            interview_details = None
            if 'interview_details' in result_data and result_data['interview_details']:
                from src.models.interview_schemas import InterviewDetailSchema, InterviewType, InterviewStatus
                interview_details = InterviewDetailSchema(
                    job_title=result_data['interview_details'].get('job_title', ''),
                    company_name=result_data['interview_details'].get('company_name', result_data['company_name']),
                    interview_type=InterviewType(result_data['interview_details'].get('interview_type', '其他')),
                    interview_datetime=datetime.fromisoformat(result_data['interview_details'].get('interview_datetime', datetime.now().isoformat())),
                    duration_minutes=result_data['interview_details'].get('duration_minutes'),
                    location_type=result_data['interview_details'].get('location_type', 'ONLINE'),
                    meeting_link=result_data['interview_details'].get('meeting_link'),
                    contact_name=result_data['interview_details'].get('contact_name'),
                    contact_email=result_data['interview_details'].get('contact_email'),
                    contact_phone=result_data['interview_details'].get('contact_phone'),
                    notes=result_data['interview_details'].get('notes')
                )

            return EmailCategorySchema(
                category=result_data.get('category', 'OTHER'),
                company_name=result_data.get('company_name', '未知'),
                summary=result_data.get('summary', ''),
                extracted_interview_details=interview_details,
                confidence_score=result_data.get('confidence_score', 0.0)
            )

        except Exception as e:
            self.logger.error(f"解析结果失败: {e}")
            return EmailCategorySchema(
                category='OTHER',
                company_name='未知',
                summary='解析失败',
                confidence_score=0.0
            )

    async def _handle_interview_invite(self, category: EmailCategorySchema):
        """处理面试邀请"""
        self.logger.info(f"处理面试邀请: {category.company_name}")

        if category.extracted_interview_details:
            details = category.extracted_interview_details
            self.logger.info(f"面试详情: {details.job_title} - {details.interview_datetime}")
            # 这里可以调用 calendar_sync 的 create_interview_event 方法

    async def _handle_online_test(self, category: EmailCategorySchema):
        """处理在线测评"""
        self.logger.info(f"处理在线测评: {category.company_name}")

    async def _handle_rejection(self, category: EmailCategorySchema):
        """处理拒信"""
        self.logger.info(f"处理拒信: {category.company_name}")


async def test_email_listener():
    """测试邮件监听器"""
    print("=== 邮件监听器测试 ===\n")

    # 创建配置
    config = EmailListenerConfig()
    listener = EmailListener(config)

    # 模拟检查新邮件
    new_emails = await listener.check_new_emails()

    print(f"找到 {len(new_emails)} 封新邮件:")

    for i, email in enumerate(new_emails, 1):
        print(f"\n=== 邮件 {i} ===")
        print(f"主题: {email.subject}")
        print(f"发件人: {email.from_name} <{email.from_email}>")
        print(f"时间: {email.date}")
        print(f"预览: {email.body[:200]}...")

        # 测试邮件解析
        print("\n开始解析邮件...")
        category = await listener.parse_email_content(email.body)

        print(f"\n分类结果:")
        print(f"类型: {category.category}")
        print(f"公司: {category.company_name}")
        print(f"摘要: {category.summary}")
        print(f"置信度: {category.confidence_score:.2f}")

        if category.extracted_interview_details:
            details = category.extracted_interview_details
            print(f"\n面试详情:")
            print(f"职位: {details.job_title}")
            print(f"面试时间: {details.interview_datetime}")
            print(f"面试类型: {details.interview_type}")
            print(f"地点类型: {details.location_type}")
            if details.meeting_link:
                print(f"会议链接: {details.meeting_link}")


if __name__ == "__main__":
    asyncio.run(test_email_listener())