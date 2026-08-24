# 🤖 AI Job Agent v2.0 - 智能求职助手

> **版本**: 2.0 | **状态**: ✅ 生产就绪 | **类型**: 自主求职Agent

## 📋 项目概述

AI Job Agent v2.0 是一个具备自主决策、智能学习和自适应能力的求职助手。它能够自动搜索、分析、申请职位，并在收到拒信时进行深度反思，不断优化求职策略。

### 🚀 核心特性

1. **自主求职流程** - 从搜索到申请的全自动化
2. **智能匹配算法** - 多维度职位匹配评分系统
3. **未知网站导航** - 自适应官网结构解析
4. **智能表单填充** - AI驱动的表单识别与填写
5. **自反思学习系统** - 从拒信中学习和进化
6. **实时监控Dashboard** - 可视化Agent行为监控
7. **邮箱监听** - 自动检测并处理拒信
8. **动态策略优化** - 基于经验的规则引擎

### 🎯 系统架构

```
┌─────────────────────────────────────────────────────┐
│                 Agent Orchestrator                 │
│                 (中央控制器)                       │
├─────────────────────────────────────────────────────┤
│  🔍 JobSearcher   🧠 MatchingEngine  🌐 BrowserAgent │
│  📧 EmailListener 🧠 ReflectionSystem 📝 FormFiller   │
└─────────────────────────────────────────────────────┘
```

## 🛠️ 安装指南

### 1. 环境要求

- Python 3.11+
- Node.js (可选，用于Playwright浏览器驱动)
- 稳定的网络连接

### 2. 安装依赖

```bash
# 克隆项目
git clone <repository-url>
cd ai-agent

# 安装Python依赖
pip install -r requirements.txt

# 安装Playwright浏览器驱动
playwright install
```

### 3. 配置设置

1. **创建配置文件**

```bash
# 复制默认配置
cp config.json.example config.json
```

2. **编辑配置**

```json
{
  "email": {
    "enabled": true,
    "server": "imap.gmail.com",
    "username": "your_email@gmail.com",
    "password": "your_app_password"  # 使用应用专用密码
  },
  "llm": {
    "provider": "openai",
    "api_key": "your_openai_api_key"
  },
  "paths": {
    "resume": "data/resume.pdf"
  }
}
```

### 4. 准备简历

将您的简历文件放在 `data/` 目录下，支持以下格式：
- PDF (.pdf)
- Word (.docx)
- Text (.txt)

## 🚀 快速开始

### 方式一：使用交互式控制台

```bash
# 启动控制台
python run_agent.py

# 控制台命令示例
agent> help                    # 查看帮助
agent> persona                 # 创建用户画像
agent> search                  # 开始职位搜索
agent> apply url1 url2         # 申请指定职位
agent> dashboard               # 启动监控面板
agent> learn                   # 查看学习洞察
agent> start                   # 启动持续监控
agent> exit                     # 退出程序
```

### 方式二：直接命令执行

```bash
# 直接执行特定命令
python run_agent.py --command search --args

# 申请多个职位
python run_agent.py --command apply --args https://job1.com/apply https://job2.com/apply

# 启动Dashboard
python run_agent.py --command dashboard
```

## 📊 监控面板

访问 http://localhost:8501 查看实时监控面板：

- **核心指标** - 申请数量、成功率、匹配分数
- **数据可视化** - 漏斗图、分布图、时间线
- **反思日志** - Agent的学习过程和策略优化
- **策略规则** - 生成的动态策略规则

## 🧠 自反思系统详解

### 反思流程

1. **拒信检测** - 自动识别HR拒信
2. **深度分析** - LLM分析失败原因
3. **策略生成** - 生成改进策略
4. **规则存储** - 保存到策略规则库
5. **画像更新** - 根据需要优化用户画像

### 学习维度

| 维度 | 描述 | 示例 |
|------|------|------|
| **经验年限** | JD要求与实际经验匹配 | 过滤5+年经验要求 |
| **技术栈** | 技术能力与JD匹配度 | 优先React生态公司 |
| **学历/身份** | 学历、工作地点等硬性约束 | 跳过硕士以上要求 |
| **职位层级** | Senior/Junior级别错位 | 避免投递管理岗 |
| **文化匹配** | 公司文化与个人特质 | 寻找技术导向公司 |

### 策略规则类型

- **搜索过滤** - 过滤不符合条件的职位
- **匹配调整** - 调整匹配算法权重
- **应用策略** - 优先申请的职位类型
- **画像更新** - 更新用户画像信息

## 📧 邮箱监听配置

### Gmail配置

1. **启用2FA验证**
2. **生成应用专用密码**
3. **配置邮箱信息**

```json
{
  "email": {
    "enabled": true,
    "server": "imap.gmail.com",
    "username": "your_email@gmail.com",
    "password": "xxxx xxxx xxxx xxxx"
  }
}
```

### 其他邮箱

支持支持IMAP协议的邮箱服务器：
- Outlook/Hotmail: outlook.office365.com
- QQ邮箱: imap.qq.com
- 163邮箱: imap.163.com

## 📈 使用示例

### 完整求职流程

```bash
# 1. 创建用户画像
agent> persona
# 上传简历，输入职业目标

# 2. 搜索职位
agent> search
# 自动搜索匹配的职位

# 3. 查看匹配结果
agent> status
# 查看高匹配职位列表

# 4. 申请职位
agent> apply https://example.com/job/123
# 智能填写表单并提交

# 5. 启动持续监控
agent> start
# Agent会自动监控邮箱处理拒信
```

### 高级用法

```bash
# 批量申请
python run_agent.py --command apply --args url1 url2 url3

# 查看学习洞察
python run_agent.py --command learn

# 查看实时状态
python run_agent.py --command status

# 紧急停止
python run_agent.py --command emergency
```

## 🐛 故障排除

### 常见问题

1. **无法创建用户画像**
   - 检查简历文件是否存在
   - 确认LLM API密钥正确
   - 检查文件格式支持

2. **职位搜索无结果**
   - 检查网络连接
   - 确认用户画像配置
   - 调整搜索参数

3. **邮箱监听不工作**
   - 验证邮箱配置
   - 确认邮箱支持IMAP
   - 检查网络防火墙设置

4. **Dashboard无法访问**
   - 确认端口8501未占用
   - 检查Streamlit安装
   - 查看浏览器控制台错误

### 日志查看

```bash
# 查看运行日志
tail -f logs/agent.log

# 查看浏览器操作日志
tail -f logs/browser.log

# 查看反思日志
tail -f logs/reflection.log
```

## 🔧 高级配置

### 自定义搜索源

```json
{
  "search": {
    "sources": [
      "linkedin",
      "bosszhipin",
      "indeed",
      "zhaopin"
    ]
  }
}
```

### 调整匹配算法

```json
{
  "matching": {
    "threshold_score": 75,
    "auto_apply": true,
    "dry_run": false
  }
}
```

### 配置浏览器选项

```json
{
  "browser": {
    "headless": false,    // 显示浏览器窗口
    "timeout": 60000,     // 延长超时时间
    "max_retries": 5      // 增加重试次数
  }
}
```

## 📊 性能优化

### 提升搜索效率

1. **限制搜索范围**
   ```json
   {
     "search": {
       "max_results_per_search": 30
     }
   }
   ```

2. **调整搜索间隔**
   ```json
   {
     "search": {
       "interval_hours": 12
     }
   }
   ```

### 优化内存使用

1. **启用headless模式**
   ```json
   {
     "browser": {
       "headless": true
     }
   }
   ```

2. **清理缓存**
   ```bash
   # 定期清理数据目录
   rm -rf data/cache/*
   ```

## 🛡️ 安全注意事项

1. **API密钥保护**
   - 使用环境变量存储敏感信息
   - 不要将密钥提交到版本控制

2. **数据隐私**
   - 简历和个人信息加密存储
   - 定期清理敏感数据

3. **合规使用**
   - 遵守网站robots.txt规则
   - 控制请求频率，避免被封禁

## 🤝 贡献指南

欢迎贡献代码和反馈！

### 开发环境设置

```bash
# 克隆开发版本
git clone <repository-url>
cd ai-agent

# 安装开发依赖
pip install -r requirements-dev.txt

# 运行测试
pytest tests/

# 代码格式化
black src/
isort src/
```

### 提交规范

- 使用清晰的commit消息
- 遵循PEP 8代码规范
- 添加必要的测试用例

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 🆘 技术支持

- 📧 邮箱: support@example.com
- 🐛 Issues: [GitHub Issues](https://github.com/your-repo/issues)
- 📖 文档: [Wiki](https://github.com/your-repo/wiki)

---

**开始您的智能求职之旅！🚀**