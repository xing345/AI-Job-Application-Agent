# 项目需求文档：全自动求职投递与面试日程管理 Agent (Auto Job Agent)

## 1. 项目愿景 (Project Vision)
打造一个端到端的“全自动化求职数字替身”。
用户仅需提供：
1. **个人简历 (PDF)**
2. **求职目标指令**（目标岗位、指定公司或行业领域、地点/经验限制）

Agent 将自主完成全流程：**自动寻找目标公司招聘官网 ➔ 抓取并筛选匹配岗位 ➔ 自动填写表单与投递简历 ➔ 监听 HR 回复邮件 ➔ 自动规划面试日程到 Google Calendar**。

---

## 2. 系统核心架构与模块 (Core Architecture & Modules)

[用户输入: 简历 PDF + 求职目标]
│
▼
┌────────────────────────────────────────────────────────┐
│ 1. 简历与指令解析器 (Resume & Target Parser)            │
│ - 提取 PDF 简历，映射为 Pydantic ResumeSchema          │
│ - 解析目标指令，提取关键词、地点、公司清单及匹配度阈值    │
└─────────────────────────┬──────────────────────────────┘
│
▼
┌────────────────────────────────────────────────────────┐
│ 2. 招聘官网寻址引擎 (Career Portal Finder)             │
│ - 调用 Tavily API 定向搜索目标公司官方 Career 页面     │
│ - 识别并提炼 ATS 平台链接 (Greenhouse / Lever / Workday)│
└─────────────────────────┬──────────────────────────────┘
│
▼
┌────────────────────────────────────────────────────────┐
│ 3. 岗位抓取与智能匹配 (JD Matcher)                     │
│ - 抓取目标 Portal 岗位列表及详细 JD                      │
│ - LLM 针对简历与 JD 进行 0-100 打分，过滤低匹配度岗位    │
└─────────────────────────┬──────────────────────────────┘
│
▼
┌────────────────────────────────────────────────────────┐
│ 4. Web 自动化填报引擎 (Browser Automation Engine)      │
│ - 基于 browser-use + Playwright 操控真实 Chrome 浏览器   │
│ - 智能填充个人信息、回答开放题、自动上传 PDF 简历文件   │
└─────────────────────────┬──────────────────────────────┘
│
▼
┌────────────────────────────────────────────────────────┐
│ 5. 人工确认与安全网 (Human-in-the-Loop, HITL)          │
│ - 遇验证码 (CAPTCHA) 或提交前的最后一步强制挂起          │
│ - 提示用户在浏览器中人工确认后点击 Submit              │
└─────────────────────────┬──────────────────────────────┘
│
▼
┌────────────────────────────────────────────────────────┐
│ 6. 面试监听与日程规划 (Email & Calendar Hook)          │
│ - 轮询 Gmail 监听 HR 回复邮件                            │
│ - LLM 识别面试邀请，提取时间/会议链接同步至日历与通知  │
└────────────────────────────────────────────────────────┘


---

## 3. 技术栈规范 (Tech Stack)

- **语言与编程范式**：Python 3.11+, 全流程 `asyncio` 异步编程
- **数据结构与校验**：`pydantic` (v2)
- **Web 自动化**：`browser-use`, `playwright`
- **信息检索与抓取**：`tavily-python` API
- **Agent 编排框架**：`langgraph` (管理状态机与中断)
- **邮件与日程**：`google-api-python-client` (Gmail API & Google Calendar API)
- **开发与协作工具**：VS Code + Claude Code (CLI)

---

## 4. 开发实施路线图 (Development Roadmap for Claude Code)

### Phase 1: 基础设施与数据 Schema 搭建
- [ ] 创建项目目录树结构（`src/models`, `src/parsers`, `src/automation`, `src/search`, `src/notifications`）。
- [ ] 编写 Pydantic 数据模型：`ResumeSchema` (个人信息/经历/作答库) 与 `TargetInstructionSchema` (目标指令)。
- [ ] 实现 `src/parsers/resume_parser.py`：解析 PDF 简历文本并调用 LLM 结构化输出。

### Phase 2: 单页自动填报 MVP (核心攻坚)
- [ ] 配置 `browser-use` + `Playwright` 自动化环境。
- [ ] 编写 `src/automation/auto_fill.py`：给定任意 Greenhouse/Lever 岗位链接，自动识别输入框、填入信息并上传简历 PDF。
- [ ] 加入 HITL 中断逻辑：停在 Submit 提交按钮前，等待用户确认。

### Phase 3: 官网寻找与 JD 匹配引擎
- [ ] 编写 `src/search/job_finder.py`：使用 Tavily API 根据公司名/岗位搜索招聘官网入口。
- [ ] 编写 `src/search/job_matcher.py`：抓取 JD 文本，基于 LLM 进行匹配打分 (0-100)，筛选合格 URL 列表。

### Phase 4: 后链路邮件监听与日历同步
- [ ] 编写 `src/notifications/email_listener.py`：使用 Gmail API 轮询邮箱并用 LLM 分类邮件。
- [ ] 编写 `src/notifications/calendar_sync.py`：解析面试时间并在 Google Calendar 上创建日程事件。

### Phase 5: 全局 LangGraph 状态机整合
- [ ] 使用 LangGraph 串联全流程（Search ➔ Match ➔ Fill ➔ HITL Pause ➔ Log）。
- [ ] 添加日志记录与异常重试机制。