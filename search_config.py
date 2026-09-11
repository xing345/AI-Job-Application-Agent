"""
搜索管道配置文件
"""

# Tavily API 配置
TAVILY_API_KEY = "your_tavily_api_key_here"

# OpenAI API 配置
OPENAI_API_KEY = "your_openai_api_key_here"

# 搜索配置
MIN_SCORE_THRESHOLD = 60  # 最低匹配分数
MAX_SEARCH_RESULTS = 10   # 最大搜索结果数

# 招聘渠道：国内平台优先（海外 ATS 渠道已下线）
# 注意：这里只是声明渠道偏好，实际检索由 SearchPipeline 的三个通道执行
SEARCH_SOURCES = [
    "bosszhipin",   # BOSS直聘
    "lagou",        # 拉勾
    "liepin",       # 猎聘
    "zhaopin",      # 智联招聘
    "51job",        # 前程无忧
    "company_site", # 公司自有招聘官网
]

# 优先级权重配置
PRIORITY_WEIGHTS = {
    "score": 0.5,      # 匹配分数权重
    "matched_skills": 0.3,  # 已匹配技能权重
    "missing_skills": 0.2   # 缺少技能权重（负值）
}