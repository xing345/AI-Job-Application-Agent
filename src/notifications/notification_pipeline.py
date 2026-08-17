"""
通知管道主测试脚本
从"模拟收到面试邮件 ➔ 识别面试时间 ➔ 输出 Google Calendar 事件数据/推送提醒"的全流程
"""

import asyncio
from datetime import datetime, timedelta
from loguru import logger
from typing import List

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# 导入相关模块
from src.notifications.email_listener import EmailListener, EmailListenerConfig, MockEmailData
from src.notifications.calendar_sync import CalendarSync, CalendarConfig, WebhookService
from src.models.interview_schemas import InterviewDetailSchema, InterviewType, InterviewStatus


class NotificationPipeline:
    """通知管道"""

    def __init__(self):
        # 初始化各组件
        self.email_listener_config = EmailListenerConfig()
        self.calendar_config = CalendarConfig(
            api_key="test_api_key",
            calendar_id="primary"
        )

        self.email_listener = EmailListener(self.email_listener_config)
        self.calendar_sync = CalendarSync(self.calendar_config)
        self.webhook_service = WebhookService()

        # 配置日志
        logger.add("notification_pipeline.log", rotation="10 MB")

    async def run_pipeline(self):
        """运行完整的通知管道"""
        logger.info("开始运行通知管道...")

        # 第一步：模拟接收邮件
        await self._step_1_mock_email_reception()

        # 第二步：邮件分类和解析
        await self._step_2_email_classification_and_parsing()

        # 第三步：创建面试事件
        await self._step_3_create_calendar_event()

        # 第四步：发送提醒通知
        await self._step_4_send_notifications()

        logger.info("通知管道运行完成")

    async def _step_1_mock_email_reception(self):
        """第一步：模拟接收邮件"""
        logger.info("步骤1: 模拟接收面试邮件")

        # 获取模拟邮件
        mock_emails = MockEmailData.get_mock_emails()

        # 过滤面试相关的邮件
        interview_emails = [email for email in mock_emails
                          if "面试" in email.subject or "Interview" in email.subject]

        print(f"\n=== 步骤1: 模拟接收邮件 ===")
        print(f"共收到 {len(mock_emails)} 封邮件")
        print(f"其中面试相关邮件 {len(interview_emails)} 封")

        for i, email in enumerate(interview_emails, 1):
            print(f"\n邮件 {i}:")
            print(f"  主题: {email.subject}")
            print(f"  发件人: {email.from_name} <{email.from_email}>")
            print(f"  时间: {email.date}")

        return interview_emails

    async def _step_2_email_classification_and_parsing(self):
        """第二步：邮件分类和解析"""
        logger.info("步骤2: 邮件分类和解析")

        # 获取模拟邮件
        mock_emails = MockEmailData.get_mock_emails()
        interview_emails = [email for email in mock_emails
                          if "面试" in email.subject or "Interview" in email.subject]

        print(f"\n=== 步骤2: 邮件分类和解析 ===")

        # 解析每封邮件
        parsed_emails = []
        for email in interview_emails:
            print(f"\n解析邮件: {email.subject}")

            # 使用邮件监听器解析
            category_schema = await self.email_listener.parse_email_content(email.body)

            print(f"分类结果:")
            print(f"  类型: {category_schema.category}")
            print(f"  公司: {category_schema.company_name}")
            print(f"  摘要: {category_schema.summary}")
            print(f"  置信度: {category_schema.confidence_score:.2f}")

            if category_schema.extracted_interview_details:
                details = category_schema.extracted_interview_details
                print(f"\n面试详情:")
                print(f"  职位: {details.job_title}")
                print(f"  面试时间: {details.interview_datetime}")
                print(f"  面试类型: {details.interview_type}")
                print(f"  地点类型: {details.location_type}")
                if details.meeting_link:
                    print(f"  会议链接: {details.meeting_link}")

                parsed_emails.append({
                    "email": email,
                    "category": category_schema,
                    "details": details
                })

        return parsed_emails

    async def _step_3_create_calendar_event(self, parsed_emails=None):
        """第三步：创建面试事件"""
        logger.info("步骤3: 创建面试事件")

        if not parsed_emails:
            parsed_emails = await self._step_2_email_classification_and_parsing()

        print(f"\n=== 步骤3: 创建面试事件 ===")

        # 初始化日历同步
        await self.calendar_sync.setup()

        for item in parsed_emails:
            details = item["details"]
            category = item["category"]

            print(f"\n为 {category.company_name} 创建面试事件:")

            # 创建面试事件
            event_id = await self.calendar_sync.create_interview_event(details)

            print(f"  事件 ID: {event_id}")
            print(f"  日历已创建!")

        return parsed_emails

    async def _step_4_send_notifications(self, parsed_emails=None):
        """第四步：发送提醒通知"""
        logger.info("步骤4: 发送提醒通知")

        if not parsed_emails:
            parsed_emails = await self._step_2_email_classification_and_parsing()

        print(f"\n=== 步骤4: 发送提醒通知 ===")

        for item in parsed_emails:
            details = item["details"]
            category = item["category"]

            # 准备通知消息
            message = self._prepare_notification_message(category, details)

            print(f"\n发送面试提醒:")
            print(f"  公司: {category.company_name}")
            print(f"  职位: {details.job_title}")
            print(f"  时间: {details.interview_datetime}")
            print(f"  消息: {message}")

            # 发送通知（使用模拟）
            await self.webhook_service.send_notification(
                message=message,
                channels=["feishu", "wechat"]
            )

    def _prepare_notification_message(self, category, details) -> str:
        """准备通知消息"""
        message = f"""
🎉 新的面试邀请！

📋 公司: {category.company_name}
💼 职位: {details.job_title}
🗓️ 时间: {details.interview_datetime}
📱 联系人: {details.contact_name or '未提供'}
🔗 链接: {details.meeting_link or '无'}
📍 类型: {details.interview_type.value}

⏰ 已创建日历事件，提前30分钟提醒
📧 请查收邮件获取详细准备要求

祝您面试顺利！
"""

        # 移除多余的空格和换行
        return message.strip().replace('\n\n', '\n')


async def test_pipeline_with_error_scenarios():
    """测试包含错误场景的管道"""
    print("\n=== 错误场景测试 ===")

    pipeline = NotificationPipeline()

    # 测试1：无效的邮件内容
    print("\n测试1: 无效的邮件内容")
    invalid_email_content = "这是一封没有面试信息的普通邮件。"
    try:
        result = await pipeline.email_listener.parse_email_content(invalid_email_content)
        print(f"分类结果: {result.category}")
    except Exception as e:
        print(f"错误处理: {e}")

    # 测试2：缺少关键信息的面试邮件
    print("\n测试2: 缺少关键信息的面试邮件")
    incomplete_email = """
    面试通知

    您好，邀请您参加面试。
    请明天下午来公司面试。
    """
    try:
        result = await pipeline.email_listener.parse_email_content(incomplete_email)
        print(f"分类结果: {result.category}")
        if result.extracted_interview_details:
            print("成功解析面试详情")
        else:
            print("无法解析完整的面试详情")
    except Exception as e:
        print(f"错误处理: {e}")


async def demo_real_time_workflow():
    """演示实时工作流程"""
    print("\n=== 实时工作流程演示 ===")

    # 创建管道
    pipeline = NotificationPipeline()

    # 模拟实时邮件接收
    mock_emails = MockEmailData.get_mock_emails()

    for email in mock_emails:
        print(f"\n📧 收到新邮件: {email.subject}")

        # 立即处理
        category = await pipeline.email_listener.parse_email_content(email.body)

        if category.category == 'INTERVIEW_INVITE':
            print(f"✅ 这是面试邀请，正在处理...")

            # 创建日历事件
            if category.extracted_interview_details:
                await pipeline.calendar_sync.create_interview_event(
                    category.extracted_interview_details
                )

            # 发送通知
            await pipeline.webhook_service.send_notification(
                message=f"🎯 新面试安排：{category.company_name} - {category.extracted_interview_details.job_title}"
            )

        elif category.category == 'ONLINE_TEST':
            print(f"⚡ 这是在线测评，请留意")
            # 处理在线测评逻辑

        elif category.category == 'REJECTED':
            print(f"❔ 这是拒信，已存档")
            # 处理拒信逻辑

        else:
            print(f"ℹ️ 这是其他类型邮件")


async def run_comprehensive_test():
    """运行全面测试"""
    print("\n" + "="*60)
    print("🚀 通知管道全面测试")
    print("="*60)

    pipeline = NotificationPipeline()

    # 测试1：基本功能测试
    print("\n📋 测试1: 基本功能流程")
    await pipeline.run_pipeline()

    # 测试2：错误场景测试
    print("\n🚨 测试2: 错误场景处理")
    await test_pipeline_with_error_scenarios()

    # 测试3：实时流程演示
    print("\n⏱️  测试3: 实时工作流程")
    await demo_real_time_workflow()

    print("\n" + "="*60)
    print("✅ 所有测试完成!")
    print("="*60)


async def test_individual_components():
    """测试单个组件"""
    print("\n=== 单个组件测试 ===")

    # 1. 测试邮件监听器
    print("\n1. 测试邮件监听器...")
    await test_email_listener()

    # 2. 测试日历同步
    print("\n2. 测试日历同步...")
    await test_calendar_sync()

    # 3. 测试邮件解析
    print("\n3. 测试邮件解析...")


async def test_email_listener():
    """测试邮件监听器"""
    print("\n--- 邮件监听器测试 ---")
    config = EmailListenerConfig()
    listener = EmailListener(config)

    # 获取模拟邮件
    emails = MockEmailData.get_mock_emails()
    print(f"模拟邮件数量: {len(emails)}")

    # 测试解析
    for email in emails[:2]:  # 测试前2封
        print(f"\n解析邮件: {email.subject}")
        result = await listener.parse_email_content(email.body)
        print(f"结果: {result.category} - {result.summary}")


async def test_calendar_sync():
    """测试日历同步"""
    print("\n--- 日历同步测试 ---")
    config = CalendarConfig()
    calendar_sync = CalendarSync(config)
    await calendar_sync.setup()

    # 创建测试数据
    from src.models.interview_schemas import InterviewDetailSchema, InterviewType
    details = InterviewDetailSchema(
        job_title="测试职位",
        company_name="测试公司",
        interview_type=InterviewType.TECHNICAL,
        interview_datetime=datetime.now() + timedelta(days=1),
        duration_minutes=60,
        location_type="ONLINE",
        meeting_link="https://test.meeting.com"
    )

    # 创建事件
    event_id = await calendar_sync.create_interview_event(details)
    print(f"创建事件成功: {event_id}")


async def main():
    """主函数"""
    print("📧 通知管道测试")
    print("支持的功能:")
    print("  1. 邮件监听和分类")
    print("  2. 面试详情提取")
    print("  3. 日历事件创建")
    print("  4. 多渠道提醒通知")
    print("  5. 错误处理和容错")
    print("\n正在运行测试...")

    # 选择测试模式 - 默认运行基本测试
    test_mode = "1"  # 可以修改为 2 或 3 进行其他测试

    if test_mode == "1":
        pipeline = NotificationPipeline()
        await pipeline.run_pipeline()
    elif test_mode == "2":
        await run_comprehensive_test()
    elif test_mode == "3":
        await test_individual_components()
    else:
        print("默认运行基本测试...")
        pipeline = NotificationPipeline()
        await pipeline.run_pipeline()


if __name__ == "__main__":
    asyncio.run(main())