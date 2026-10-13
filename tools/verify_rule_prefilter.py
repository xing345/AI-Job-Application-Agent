"""验证规则预过滤效果。"""
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.agent.nodes.screen_titles import rule_prefilter
from src.models.job import JobPosting

# 模拟岗位标题（混合技术类和非技术类）
test_titles = [
    # 技术类
    "XR系统应用开发工程师 - 移动OS",
    "运筹优化算法实习生-国际电商",
    "代码质量大模型算法实习生-质量技术",
    "视频编码策略算法实习生-音视频技术",
    "算法实习生 - 今日头条",
    "Agent算法工程师 - App Infra",
    "前端开发实习生-抖音直播",
    "直播后台开发实习生-音视频技术",
    "后端开发实习生-Flow",
    "芯片软件研发工程师（存算与AI） - 芯片研发",
    "豆包AI大模型产品实习生（算法平台） - 火山方舟",
    "网络安全实习生（WAAP方向）-安全与风控",
    "Java开发工程师 - 电商业务",
    "Python后端开发 - 支付系统",
    "全栈开发工程师 - 企业服务",
    "iOS客户端开发 - 抖音",
    "Android开发工程师 - 飞书",
    "测试开发工程师 - 质量保障",
    "运维工程师 - 基础架构",
    "数据开发工程师 - 数据中台",
    "机器学习算法工程师 - 推荐系统",
    "NLP算法工程师 - 大模型",
    "区块链开发工程师 - 智能合约",
    "云计算研发工程师 - 容器",
    "嵌入式软件开发 - 机器人",
    "游戏客户端开发 - 原神",
    "音视频开发工程师 - 直播",
    "数据库内核开发 - 分布式存储",
    "安全攻防工程师 - 红队",
    "DevOps工程师 - CI/CD",
    # 非技术类
    "行政专员 - 总部",
    "人力资源实习生 - 招聘",
    "财务会计 - 字节跳动",
    "销售经理 - 企业客户",
    "市场营销专员 - 品牌",
    "新媒体运营 - 抖音",
    "文案策划 - 内容中心",
    "UI设计师 - 产品设计",
    "法务专员 - 合规",
    "采购经理 - 供应链",
    "客服专员 - 用户支持",
    "质检专员 - 内容质量",
    "产品经理 - 抖音",  # 拿不准，产品经理可能技术相关也可能不
    "运营经理 - 电商",
    "管培生 - 综合管理",
    "投资分析师 - 战略投资",
    "公关专员 - 品牌传播",
    "培训专员 - 人才发展",
    "前台接待 - 行政",
    "司机 - 行政车队",
    # 拿不准的
    "产品运营 - 技术产品",  # 含"运营"但也含"技术"
    "技术支持工程师 - 客户成功",  # 含"技术"和"支持"
    "游戏运营 - 数据分析",  # 含"运营"和"数据"
    "AI产品经理 - 大模型",  # 含"AI"和"产品经理"
    "数据分析师 - 商业分析",  # 含"数据"但可能是业务分析
    "项目管理 - 研发项目",  # 含"项目管理"和"研发"
    "解决方案工程师 - 售前",  # 含"工程师"但可能是售前
    "量化研究员 - 投资",  # 含"研究员"和"量化"
]

jobs = [JobPosting(title=t, detail_url=f"https://example.com/{i}", site_name="test") for i, t in enumerate(test_titles)]

tech, non_tech, uncertain = rule_prefilter(jobs)

print(f"=== 规则预过滤结果 ===")
print(f"总数: {len(jobs)}")
print(f"技术类（直接保留）: {len(tech)}")
print(f"非技术类（直接排除）: {len(non_tech)}")
print(f"待定（进LLM）: {len(uncertain)}")

print(f"\n--- 技术类（{len(tech)}个）---")
for j in tech:
    print(f"  ✓ {j.title}")

print(f"\n--- 非技术类（{len(non_tech)}个）---")
for j in non_tech:
    print(f"  ✗ {j.title}")

print(f"\n--- 待定（{len(uncertain)}个，进LLM）---")
for j in uncertain:
    print(f"  ? {j.title}")

# 计算 LLM 调用节省
original_batches = (len(jobs) + 19) // 20
llm_batches = (len(uncertain) + 19) // 20
saved = original_batches - llm_batches
print(f"\n=== LLM 调用节省 ===")
print(f"原方案: {len(jobs)}个岗位 -> {original_batches}次LLM调用")
print(f"新方案: {len(uncertain)}个待定 -> {llm_batches}次LLM调用")
print(f"节省: {saved}次调用（{saved/original_batches*100:.0f}%）")
