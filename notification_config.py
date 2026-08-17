"""
通知系统配置文件
"""

# Gmail API 配置
GMAIL_API_KEY = "your_gmail_api_key_here"
GMAIL_CLIENT_ID = "your_gmail_client_id_here"
GMAIL_CLIENT_SECRET = "your_gmail_client_secret_here"
GMAIL_REFRESH_TOKEN = "your_gmail_refresh_token_here"

# OpenAI API 配置
OPENAI_API_KEY = "your_openai_api_key_here"

# Google Calendar API 配置
GOOGLE_CALENDAR_API_KEY = "your_google_calendar_api_key_here"

# 通知渠道配置
NOTIFICATION_WEBHOOKS = {
    "feishu": "your_feishu_webhook_url_here",
    "wechat": "your_wechat_webhook_url_here",
    "telegram": "your_telegram_bot_token_here"
}

# 监听配置
EMAIL_POLL_INTERVAL = 300  # 轮询间隔（秒）
EMAIL_MAX_RESULTS = 50     # 每次轮询最大邮件数

# 分类配置
MIN_CONFIDENCE_SCORE = 0.7  # 最低置信度
MATCH_THRESHOLD = 60       # 最低匹配分数