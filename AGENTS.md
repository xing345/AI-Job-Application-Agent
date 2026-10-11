# Auto Job Agent 项目指南（重写版）

## 项目概述
LLM-driven 自动求职 Agent：岗位发现 → 标题语义初筛 → JD 深度匹配 → 用户确认 → 自动填表 → HITL 提交。
技术栈：Python 3.11+、Playwright、LangGraph、OpenAI 兼容 LLM API、Pydantic v2、python-dotenv。

## 终端命令
- 启动 Agent：`python -m src.main --site bytedance --resume data/resume.pdf`
- 直接指定岗位 URL：`python -m src.main --job-url https://jobs.xxx/xxx --resume data/resume.pdf`
- 列出支持站点：`python -m src.main --list-sites`
- 断点续跑：`python -m src.main --resume-run <session_id>`
- LLM 客户端验证：`python -m tools.verify_llm_client`
- 安装依赖：`pip install -r requirements.txt`

## 代码结构
```
src/
├── main.py              # 入口，命令行参数
├── agent/
│   ├── graph.py         # LangGraph StateGraph 编排
│   ├── state.py         # AgentState (Pydantic)
│   └── nodes/           # 每个节点一个文件
│       ├── load_profile.py
│       ├── discover_jobs.py
│       ├── screen_titles.py     # 标题语义初筛（LLM）
│       ├── fetch_jd.py
│       ├── match_jobs.py        # JD 深度匹配（LLM）
│       ├── confirm_list.py      # 含配额排序（LLM）
│       ├── fill_application.py  # 自动填表（LLM 字段映射）
│       └── hitl_submit.py
├── llm/
│   ├── client.py        # 统一异步 LLM 调用（重试+超时+structured output）
│   └── prompts.py       # 所有 prompt 模板集中管理
├── browser/
│   ├── manager.py       # Playwright 持久化 profile
│   ├── navigator.py     # 页面导航封装
│   └── hitl.py          # HITL 暂停机制（BlockHandler）
├── models/              # Pydantic 数据模型
├── search/
│   ├── site_registry.py # 招聘站点配置（含投递配额）
│   └── discoverer.py    # 分类导航遍历+分页
└── storage/
    └── state_db.py      # SQLite 投递记录、断点续跑
```

## 代码规范
- 所有 IO 和浏览器操作用 `async/await`。
- 所有数据模型用 Pydantic v2。
- 环境变量放 `.env`，通过 `python-dotenv` 加载，禁止硬编码密钥。
- 模块严格分离：`agent`（流程）、`llm`（大模型）、`browser`（浏览器）、`models`（数据）、`search`（岗位发现）、`storage`（存储）。
- 所有 LLM prompt 集中在 `src/llm/prompts.py`，不散落各模块。

## 已删除功能（不要重新添加）
- 简历修改/生成（`career/resume_builder.py` 等）
- 邮件监听、日历同步、仪表盘、通知推送
- Tavily 关键词搜索（岗位发现只走官方招聘网站分类导航+分页）

## 安全与操作规则
- **绝不自动点击最终「提交申请」按钮**：表单填完后必须 HITL 暂停，等用户手动点提交。
- **遇到登录墙/验证码/人机验证必须停**：用 `src/browser/hitl.py` 的 `BlockHandler` 检测并暂停，终端打印原因和 URL，等用户在浏览器中手动解决后输入 `continue` 恢复。不猜不跳不静默跳过。
- **岗位发现走分类导航+分页**：不依赖关键词搜索。先标题语义初筛，再打开详情页匹配完整 JD。
- **提取与语义分离**：Playwright 做元素级结构化提取，LLM 只做语义判断。禁止给 LLM 喂整页 HTML。
- **LLM 四个核心场景必须真实调用大模型**：标题初筛、JD匹配、字段理解、配额排序，不能用规则代替。
