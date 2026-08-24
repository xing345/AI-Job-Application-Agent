"""
邮箱监听器 - 监控拒信并触发自反思
自动监控邮箱中的拒信，触发Agent的自反思系统
"""

import asyncio
import imaplib
import email
import re
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from pathlib import Path
from loguru import logger
import sqlite3

# 添加项目根目录到路径
import sys
import os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.reflection.self_reflection_system import SelfReflectionSystem, process_rejection_workflow
from src.models.schemas import ApplicationWithReflection


class EmailListener:
    """邮箱监听器"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化邮箱监听器

        Args:
            config: 邮箱配置
        """
        self.config = config
        self.imap_server = None
        self.user_persona = None
        self.current_applications = {}
        self.reflection_system = None
        self.is_running = False

    async def initialize(self, user_persona: Dict):
        """
        初始化监听器

        Args:
            user_persona: 用户画像
        """
        logger.info("初始化邮箱监听器...")

        try:
            # 初始化自反思系统
            db_path = str(Path(project_root) / "data" / "agent_state.db")
            self.reflection_system = SelfReflectionSystem(db_path)

            # 设置用户画像
            self.user_persona = user_persona

            # 连接到邮箱服务器
            self._connect_to_mail_server()

            # 创建数据库表
            self._create_database_tables()

            logger.info("邮箱监听器初始化完成")

        except Exception as e:
            logger.error(f"邮箱监听器初始化失败: {e}")
            raise

    def _connect_to_mail_server(self):
        """连接到邮箱服务器"""
        try:
            # 使用IMAP协议连接
            self.imap_server = imaplib.IMAP4_SSL(self.config['server'])

            # 登录
            self.imap_server.login(self.config['username'], self.config['password'])

            # 选择收件箱
            self.imap_server.select('inbox')

            logger.info(f"成功连接到邮箱服务器: {self.config['server']}")

        except Exception as e:
            logger.error(f"连接邮箱服务器失败: {e}")
            raise

    def _create_database_tables(self):
        """创建邮箱监听数据库表"""
        db_path = Path(project_root) / "data" / "email_listener.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # 创建邮件追踪表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_tracker (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE,
            sender TEXT,
            subject TEXT,
            date TEXT,
            body TEXT,
            is_processed BOOLEAN DEFAULT 0,
            processed_at TIMESTAMP,
            action_taken TEXT,
            application_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # 创建邮箱配置表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        ''')

        conn.commit()
        conn.close()

    def _load_applications_database(self):
        """从数据库加载当前的应用数据"""
        try:
            db_path = Path(project_root) / "data" / "agent_state.db"
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            cursor.execute('''
            SELECT job_id, company_name, job_title, url, original_jd
            FROM job_applications
            WHERE status = 'APPLIED' OR status = 'REJECTED'
            ''')

            applications = {}
            for row in cursor.fetchall():
                job_id, company_name, job_title, url, original_jd = row
                applications[job_id] = {
                    'job_id': job_id,
                    'company_name': company_name,
                    'job_title': job_title,
                    'url': url,
                    'original_jd': original_jd
                }

            conn.close()
            self.current_applications = applications
            logger.info(f"加载了 {len(applications)} 个应用程序记录")

        except Exception as e:
            logger.error(f"加载应用程序数据库失败: {e}")

    def _is_rejection_email(self, email_body: str, subject: str) -> bool:
        """
        判断是否为拒信

        Args:
            email_body: 邮件正文
            subject: 邮件主题

        Returns:
            bool: 是否为拒信
        """
        # 拒信关键词
        rejection_keywords = [
            'regret', 'sorry', 'not selected', 'unfortunately',
            'cannot move forward', 'declined', 'rejected', 'not suitable',
            '抱歉', '遗憾', '未能通过', '不符合', '不录用', '未选中',
            '感谢您的申请', '我们决定', '很遗憾', '不能录用'
        ]

        # 非拒信关键词（排除误判）
        non_rejection_keywords = [
            'interview', '邀请', 'offer', '录用', 'congratulations',
            '面试', '通过', 'offer letter', '欢迎', '接受'
        ]

        # 检查关键词
        email_lower = email_body.lower()
        subject_lower = subject.lower()

        has_rejection = any(keyword in email_lower or keyword in subject_lower
                          for keyword in rejection_keywords)
        has_non_rejection = any(keyword in email_lower or keyword in subject_lower
                               for keyword in non_rejection_keywords)

        return has_rejection and not has_non_rejection

    def _extract_company_info(self, email_body: str) -> Optional[Dict]:
        """
        从拒信中提取公司信息

        Args:
            email_body: 邮件正文

        Returns:
            Dict: 公司信息
        """
        # 查找公司名称
        companies = self.current_applications.values()
        company_names = [app['company_name'] for app in companies]

        # 查找匹配的公司
        for company_name in company_names:
            if company_name.lower() in email_body.lower():
                # 查找对应的申请
                for app in companies:
                    if app['company_name'] == company_name:
                        return app

        return None

    def _extract_application_info(self, email_body: str, company_info: Dict) -> Dict:
        """
        提取申请信息，匹配到具体的职位

        Args:
            email_body: 邮件正文
            company_info: 公司信息

        Returns:
            Dict: 申请信息
        """
        application_data = {
            'job_id': company_info['job_id'],
            'company_name': company_info['company_name'],
            'job_title': company_info['job_title'],
            'url': company_info.get('url', ''),
            'original_jd': company_info.get('original_jd', ''),
            'match_score': 0,
            'match_reasons': []
        }

        return application_data

    def _generate_unique_message_id(self, email_data: email.message.Message) -> str:
        """
        生成唯一的邮件消息ID

        Args:
            email_data: 邮件对象

        Returns:
            str: 消息ID
        """
        message_id = email_data.get('Message-ID', '')
        if not message_id:
            # 如果没有Message-ID，使用日期和主题生成
            date = email_data.get('Date', '')
            subject = email_data.get('Subject', '')
            message_id = f"{date}_{subject}_{hash(date + subject)}"

        return str(message_id)

    async def check_new_emails(self):
        """
        检查新邮件
        """
        try:
            # 搜索未读的邮件
            self.imap_server.search(None, '(UNSEEN)')
            status, messages = self.imap_server.search(None, '(UNSEEN)')

            if status != 'OK':
                return

            message_ids = messages[0].split()

            if not message_ids:
                return

            logger.info(f"发现 {len(message_ids)} 封新邮件")

            # 处理每封邮件
            for msg_id in message_ids:
                await self._process_email(msg_id)

        except Exception as e:
            logger.error(f"检查新邮件失败: {e}")

    async def _process_email(self, msg_id: bytes):
        """
        处理单封邮件

        Args:
            msg_id: 邮件ID
        """
        try:
            # 获取邮件数据
            status, email_data = self.imap_server.fetch(msg_id, '(RFC822)')

            if status != 'OK':
                return

            # 解析邮件
            raw_email = email_data[0][1]
            email_message = email.message_from_bytes(raw_email)

            # 提取邮件信息
            sender = email_message.get('From', '')
            subject = email_message.get('Subject', '')
            date = email_message.get('Date', '')

            # 提取邮件正文
            email_body = self._extract_email_body(email_message)

            # 生成消息ID
            message_id = self._generate_unique_message_id(email_message)

            # 检查是否已处理
            if self._is_email_processed(message_id):
                return

            # 判断是否为拒信
            if self._is_rejection_email(email_body, subject):
                logger.info(f"发现拒信: {subject}")

                # 提取公司信息
                company_info = self._extract_company_info(email_body)

                if company_info:
                    # 提取申请信息
                    application_data = self._extract_application_info(email_body, company_info)

                    # 触发反思处理
                    reflection_result = await self._handle_rejection(
                        application_data=application_data,
                        rejection_email=email_body,
                        user_persona=self.user_persona
                    )

                    # 记录处理结果
                    self._mark_email_processed(
                        message_id=message_id,
                        sender=sender,
                        subject=subject,
                        date=date,
                        body=email_body,
                        action_taken='reflection_completed',
                        application_id=application_data['job_id']
                    )

                    logger.info(f"拒信处理完成: {company_info['company_name']} - {company_info['job_title']}")
                else:
                    # 无法匹配到具体申请
                    self._mark_email_processed(
                        message_id=message_id,
                        sender=sender,
                        subject=subject,
                        date=date,
                        body=email_body,
                        action_taken='no_matching_application'
                    )

                    logger.warning(f"拒信无法匹配到具体申请: {subject}")

            else:
                # 不是拒信，标记为已读
                self.imap_server.store(msg_id, '+FLAGS', '\\Seen')

                # 记录邮件
                self._mark_email_processed(
                    message_id=message_id,
                    sender=sender,
                    subject=subject,
                    date=date,
                    body=email_body,
                    action_taken='not_rejection'
                )

        except Exception as e:
            logger.error(f"处理邮件失败: {e}")

    def _extract_email_body(self, email_message: email.message.Message) -> str:
        """
        提取邮件正文

        Args:
            email_message: 邮件对象

        Returns:
            str: 邮件正文
        """
        body = ""

        # 检查邮件类型
        if email_message.is_multipart():
            # 多部分邮件
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # 获取文本内容
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        charset = part.get_content_charset() or 'utf-8'
                        body += part.get_payload(decode=True).decode(charset, errors='ignore')
                    except:
                        body += part.get_payload(decode=True).decode('utf-8', errors='ignore')
        else:
            # 单部分邮件
            try:
                charset = email_message.get_content_charset() or 'utf-8'
                body = email_message.get_payload(decode=True).decode(charset, errors='ignore')
            except:
                body = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')

        return body

    def _is_email_processed(self, message_id: str) -> bool:
        """
        检查邮件是否已处理

        Args:
            message_id: 消息ID

        Returns:
            bool: 是否已处理
        """
        try:
            db_path = Path(project_root) / "data" / "email_listener.db"
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            cursor.execute('''
            SELECT COUNT(*) FROM email_tracker
            WHERE message_id = ? AND is_processed = 1
            ''', (message_id,))

            count = cursor.fetchone()[0]
            conn.close()

            return count > 0

        except Exception as e:
            logger.error(f"检查邮件处理状态失败: {e}")
            return False

    def _mark_email_processed(
        self,
        message_id: str,
        sender: str,
        subject: str,
        date: str,
        body: str,
        action_taken: str,
        application_id: str = None
    ):
        """
        标记邮件为已处理

        Args:
            message_id: 消息ID
            sender: 发件人
            subject: 主题
            date: 日期
            body: 正文
            action_taken: 执行的动作
            application_id: 应用ID
        """
        try:
            db_path = Path(project_root) / "data" / "email_listener.db"
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            cursor.execute('''
            INSERT OR REPLACE INTO email_tracker (
                message_id, sender, subject, date, body,
                is_processed, processed_at, action_taken, application_id
            ) VALUES (?, ?, ?, ?, ?, 1, datetime('now'), ?, ?)
            ''', (message_id, sender, subject, date, body, action_taken, application_id))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"标记邮件处理状态失败: {e}")

    async def _handle_rejection(
        self,
        application_data: Dict,
        rejection_email: str,
        user_persona: Dict
    ) -> Dict:
        """
        处理拒信，触发自反思

        Args:
            application_data: 申请数据
            rejection_email: 拒信内容
            user_persona: 用户画像

        Returns:
            Dict: 处理结果
        """
        try:
            # 执行反思工作流
            result = await process_rejection_workflow(
                application_data=application_data,
                rejection_email=rejection_email,
                user_persona=user_persona
            )

            if result['success']:
                logger.info(f"反思完成，ID: {result['reflection_id']}")

                # 如果需要更新用户画像
                if result['updated_persona']:
                    logger.info("用户画像已更新")
                    self.user_persona = result['updated_persona']

                return result
            else:
                logger.error(f"反思处理失败: {result['error']}")
                return result

        except Exception as e:
            logger.error(f"处理拒信时出错: {e}")
            return {'success': False, 'error': str(e)}

    async def start_monitoring(self, interval: int = 300):
        """
        开始监听邮件

        Args:
            interval: 监听间隔（秒）
        """
        self.is_running = True
        logger.info(f"开始监听邮件，间隔: {interval}秒")

        while self.is_running:
            try:
                # 检查新邮件
                await self.check_new_emails()

                # 等待下一次检查
                await asyncio.sleep(interval)

            except Exception as e:
                logger.error(f"邮件监听出错: {e}")
                await asyncio.sleep(interval)

    async def stop_monitoring(self):
        """停止监听邮件"""
        self.is_running = False
        logger.info("停止监听邮件")

        if self.imap_server:
            self.imap_server.close()
            self.imap_server.logout()

    def get_monitoring_status(self) -> Dict:
        """
        获取监听状态

        Returns:
            Dict: 监听状态
        """
        try:
            db_path = Path(project_root) / "data" / "email_listener.db"
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # 统计处理的邮件数量
            cursor.execute('''
            SELECT
                COUNT(*) as total_emails,
                SUM(CASE WHEN is_processed = 1 THEN 1 ELSE 0 END) as processed_emails,
                SUM(CASE WHEN action_taken = 'reflection_completed' THEN 1 ELSE 0 END) as rejections_processed
            FROM email_tracker
            ''')

            stats = cursor.fetchone()
            conn.close()

            return {
                'total_emails': stats[0],
                'processed_emails': stats[1],
                'rejections_processed': stats[2],
                'is_running': self.is_running,
                'server': self.config.get('server', 'N/A'),
                'username': self.config.get('username', 'N/A')
            }

        except Exception as e:
            logger.error(f"获取监听状态失败: {e}")
            return {'error': str(e)}


# 配置示例
DEFAULT_EMAIL_CONFIG = {
    'server': 'imap.gmail.com',
    'username': 'your_email@gmail.com',
    'password': 'your_app_password',  # 使用应用专用密码
    'interval': 300  # 5分钟检查一次
}


async def create_email_listener(user_persona: Dict, config: Dict = None) -> EmailListener:
    """
    创建邮箱监听器

    Args:
        user_persona: 用户画像
        config: 邮箱配置

    Returns:
        EmailListener: 邮箱监听器实例
    """
    email_config = config or DEFAULT_EMAIL_CONFIG
    listener = EmailListener(email_config)
    await listener.initialize(user_persona)
    return listener


# 测试函数
async def test_email_listener():
    """测试邮箱监听器"""
    print("=== 测试邮箱监听器 ===")

    # 模拟用户画像
    user_persona = {
        'name': '测试用户',
        'technical_skills': ['Python', 'JavaScript'],
        'experience_years': 3
    }

    # 注意：这里使用测试配置，实际使用时需要配置真实的邮箱信息
    test_config = {
        'server': 'imap.gmail.com',
        'username': 'test@example.com',
        'password': 'test_password',
        'interval': 60  # 测试时使用较短的间隔
    }

    try:
        # 创建监听器
        listener = await create_email_listener(user_persona, test_config)

        # 加载应用程序数据
        listener._load_applications_database()

        # 获取状态
        status = listener.get_monitoring_status()
        print(f"监听器状态: {status}")

        # 模拟处理一封邮件（实际使用时不需要）
        # await listener._process_email(b'test_message_id')

        print("✅ 测试完成！")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

    return True


if __name__ == "__main__":
    # 运行测试
    asyncio.run(test_email_listener())