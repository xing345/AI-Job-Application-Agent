# Auto Job Agent · LLM 驱动的自动求职 Agent

基于 **LangGraph + Playwright + 大模型** 的本地求职自动化 Agent：自动遍历招聘官网分类导航、用语义判断筛选岗位、抓取 JD 与简历做深度匹配、智能填写投递表单，并在**登录验证**与**最终提交**两个关键节点强制暂停、交还人工。

- 代码规模：约 1.2 万行 Python，8 个流程节点，内置 33 个招聘站点适配器
- 大模型场景：标题初筛、JD 深度匹配、表单字段理解、投递配额排序——全部真实调用 LLM，不用规则冒充
- 运行形态：本地 CLI，Playwright 持久化浏览器登录态，全量状态落 SQLite，可断点续跑

---

## 一、它解决什么问题

求职季的三个重复劳动：

1. 招聘网站分散，每个站点都要重复浏览、筛选、翻页；
2. 岗位标题五花八门，"算法 / 研发 / 工程 / 平台"等叫法与自身方向是否匹配，人工逐一判断耗时；
3. 投递表单字段大量重复（个人信息、教育、项目、开放问答），手填易错。

本项目把 **「逛招聘官网 → 判断岗位是否匹配 → 填写投递表单」** 这条链路交给 Agent 自动完成，同时守住两条安全底线：

- **Agent 绝不自动点击最终的"提交申请"按钮**，填完必停，由人工检查后手动提交；
- **遇到登录墙 / 验证码 / 人机验证必须暂停**，浏览器保持打开，等用户手动解决后输入 `continue` 恢复，不猜、不跳、不静默跳过。

---

## 二、工作流程

```
                ┌──────────────────────────────────────────────┐
                │           LangGraph 状态机编排层              │
                └──────────────────────────────────────────────┘

   ┌────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐
   │ load_profile│──▶│discover_jobs │──▶│ screen_titles │──▶│  fetch_jd    │
   │ 加载画像/   │   │ 分类导航+分页 │   │ 规则+LLM 精筛 │   │ 元素级抓 JD  │
   │ 解析简历 PDF│   │ /滚动/虚拟列表│   │ 按相关度排序  │   │  结构化提取  │
   └────────────┘   └──────────────┘   └───────────────┘   └──────┬───────┘
        ▲                                                          │
        │                       ┌──────────────────┐               ▼
        │                       │ --discover-url 任意招聘列表页     ┌──────────────┐
        │                       │ --job-url  直达岗位详情页       │  match_jobs  │
        │                       │ --apply-url 直达投递表单页       │ JD × 简历    │
        │                       └──────────────────┘               │ 0–100 打分   │
        │                                                          └──────┬───────┘
        │                                                                 ▼
        │                                                          ┌──────────────┐
        │                                                          │ confirm_list │
        │                                                          │ 匹配报告+选岗 │
        │                                                          │ 超配额 LLM 排序│
        │                                                          └──────┬───────┘
        │                                                                 ▼
        │                                                          ┌──────────────┐
        │                                              ┌──────────▶│fill_application│
        │                                              │           │ 字段映射+填写  │
        │                                              │           │ HITL 暂停提交  │
        │                                              │           └──────┬───────┘
        │                                              │                  ▼
        │                                              │           ┌──────────────┐
        └──────────────── 还有待投递岗位 ───────────────┘           │ record_result│
                                                                    │ 结果落库/循环 │
                                                                    └──────────────┘

   横向依赖：browser/（Playwright 持久化上下文）  llm/（统一异步客户端）
             models/（Pydantic v2）              storage/（SQLite 缓存+断点续跑）
             search/（站点注册表 + 适配器）
```

### 节点职责

| # | 节点 | 职责 | 调用 LLM |
|---|---|---|---|
| 1 | `load_profile` | 加载用户画像 JSON；pdfplumber 解析简历 PDF（只解析，不修改、不生成） | 否 |
| 2 | `discover_jobs` | 分类导航 + 分页 / 滚动加载 / API 拦截，自动收集岗位卡片 | 否 |
| 3 | `screen_titles` | 规则预过滤 + LLM 批量精筛，按目标方向相关度排序并限量 | 是 |
| 4 | `fetch_jd` | 元素级抓取 JD 全文、岗位职责 / 任职要求分段、岗位元信息 | 否 |
| 5 | `match_jobs` | JD 全文 × 简历深度匹配，输出 0–100 分、匹配点 / 缺失点与理由 | 是 |
| 6 | `confirm_list` | 终端输出匹配报告，用户选岗；候选超过站点配额时 LLM 排序推荐 | 是 |
| 7 | `fill_application` | 表单字段发现 → LLM 语义映射 → 自动填写 → HITL 暂停等人工提交 | 是 |
| 8 | `record_result` | 投递结果落库、移动索引，驱动岗位循环 | 否 |

---

## 三、技术栈

| 层次 | 选型 |
|---|---|
| Agent 编排 | LangGraph（StateGraph、条件路由、节点循环、中断恢复） |
| 浏览器自动化 | Playwright 异步 API，持久化登录上下文（`user_data_dir`） |
| 大模型 | OpenAI 兼容接口（DeepSeek / 智谱 / GPT 等可切换），Structured Output |
| 数据模型 | Pydantic v2，统一 `extra="forbid"` |
| 持久化 | SQLite + aiosqlite，带 schema 版本与迁移 |
| 简历解析 | pdfplumber（只解析） |
| 配置与日志 | python-dotenv、loguru |
| 测试 | pytest + pytest-asyncio（核心解析用本地 fixtures，离线可跑） |

---

## 四、快速开始

### 环境要求

- Python 3.11+
- 首次运行需联网安装 Playwright Chromium 驱动

### 安装

```bash
pip install -r requirements.txt
playwright install chromium
```

### 配置

复制 `.env.example` 为 `.env`，填入 LLM 凭证（所有密钥只放 `.env`，不硬编码）：

```bash
# 以 DeepSeek 为例
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-chat

# 智谱示例：
# OPENAI_MODEL=glm-4
# OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4

# 可选，也可通过命令行 --resume / --profile 指定
RESUME_PATH=data/resume.pdf
USER_PROFILE_PATH=data/user_profile.json
```

把简历 PDF 放进 `data/`，用户画像参照 `data/user_profile.json` 配置目标方向、目标城市等。

> 注：仓库根目录的 `config.json` / `config.example.json` 是早期版本遗留文件（含已删除的 Tavily 搜索、邮件监听等模块），**当前版本不再读取**，请以 `.env` 为准。

### 运行

```bash
# 查看内置支持的站点
python -m src.main --list-sites

# 指定站点：自动发现 → 初筛 → 匹配 → 确认 → 填表
python -m src.main --site bytedance --resume data/resume.pdf

# 直达某个岗位详情页，跳过发现与初筛（--job-url 可重复传多个）
python -m src.main --job-url https://jobs.bytedance.com/xxx --resume data/resume.pdf

# 直达某个投递/表单链接，打开后直接填表（跳过前面所有节点）
python -m src.main --apply-url https://jobs.bytedance.com/xxx/apply --resume data/resume.pdf

# 接入任意未内置的招聘列表页，无需改代码
python -m src.main --discover-url https://example.com/campus/jobs --resume data/resume.pdf

# 断点续跑：Ctrl+C 或异常退出后，凭会话 ID 恢复
python -m src.main --resume-run <session_id>
```

### CLI 参数一览

| 参数 | 说明 | 默认 |
|---|---|---|
| `--site NAME` | 内置站点名（见 `--list-sites`） | 空 |
| `--job-url URL` | 直达岗位详情页，可重复传多个 | `[]` |
| `--apply-url URL` | 直达投递表单页，直接进入填表流程 | 空 |
| `--discover-url URL` | 任意招聘列表页，动态注册为新站点 | 空 |
| `--resume PATH` | 简历文件路径（PDF / JSON / TXT） | 读 `.env` |
| `--profile PATH` | 用户画像 JSON 路径 | 读 `.env` |
| `--resume-run SID` | 凭 session_id 断点续跑 | 空 |
| `--max-deep N` | 每站点深度抓取 JD + 匹配的岗位上限，`0` 为不限 | `80` |
| `--refresh` | 忽略本地缓存，强制重新发现 / 抓取 | 关 |
| `-v` / `--verbose` | 输出详细日志 | 关 |
| `--list-sites` | 打印全部内置站点并退出 | — |

---

## 五、内置站点（33 个）

按招聘门户平台分组，未列出的网站可通过 `--discover-url` 通用接入：

| 平台族 | 站点 |
|---|---|
| 官方自有门户 | bytedance、tencent、alibaba、baidu、bilibili、meituan、jd、kuaishou、xiaohongshu、mihoyo、netease、sensetime、ctrip、baichuan |
| 飞书招聘（feishu.cn / mioffice.cn） | xiaomi、zhipu（智谱）、modelbest（面壁）、minimax、qianxun（千寻智能） |
| Moka（mokahr.com） | zte、shopee、stepfun（阶跃星辰）、moonshot（月之暗面）、shanshu（杉数）、jingwei（经纬恒润）、kuaicang（快仓） |
| 智联 zhiye（zhiye.com） | iflytek（科大讯飞）、aispeech（云知声）、healthai |
| 其他 | richinfo（彩讯）、indeed（实在智能）、ztccloud（中兴新云）、kunlun（昆仑万维，经牛客跳转） |

---

## 六、工程设计要点

### 1. 提取与语义严格分离
Playwright 只做元素级结构化提取（表单字段、选项、JD 段落、岗位元信息），LLM 只接收结构化文本做语义判断，**不向 LLM 喂整页 HTML**。既省 token、又减少幻觉，判断结果可复现、可缓存。

### 2. LLM 调用工程化
- **Structured Output 降级链**：`json_schema → json_object → 纯 prompt 约束`，兼容 DeepSeek、智谱等不支持 json_schema 的后端；
- **错误分类**：401 / 403 / 400 等不可重试错误立即抛出；429 限流、5xx、超时、网络错误按指数退避有限重试；
- **并发与可观测**：信号量控制全局并发，全链路记录模型、响应格式、重试次数、token 用量与耗时；
- **严格校验**：LLM 输出清洗后再由 Pydantic 校验，失败直接报错，绝不绕过模型约束。

### 3. 不确定不编造
LLM 无法确定的字段值返回 `null`，流程自动跳过而不是猜测填写；协议授权、薪资期望、背景调查承诺、真实性声明等**法律 / 隐私 / 个人意愿字段一律标记为需人工确认**，不自动代填。

### 4. 两道人工闸门（HITL）
- **登录 / 验证闸门**：自动检测密码框、验证码元素、登录拦截文案、403 页面等，命中后真正阻塞、浏览器保持打开；用户在浏览器中处理完后，终端输入 `continue` 恢复。
- **最终提交闸门**：Agent 只填表，**绝不点击"提交申请"**；人工提交后，Agent 通过 URL 变化、页面标题变化、成功关键词三重信号验证投递是否真实成功。

### 5. 多级缓存 + 断点续跑
发现结果、标题初筛、JD 全文（按内容 hash 判失效）、匹配结果分别缓存，重复运行不重复抓取、不重复调模型；全量状态落 SQLite，任意中断（含手动 Ctrl+C）后凭会话 ID 恢复，DB schema 带版本号与迁移逻辑。

### 6. 严格分层与单一事实源
`agent`（流程编排）、`llm`（大模型）、`browser`（浏览器）、`search`（岗位发现）、`models`（数据）、`storage`（存储）职责隔离；所有 Prompt 集中在 `src/llm/prompts.py`，不散落各模块。

---

## 七、项目结构

```
.
├── data/                  # 简历 PDF、用户画像 JSON、浏览器持久化登录态、SQLite 库
├── logs/                  # 运行日志
├── output/                # 初筛结果、匹配报告等产物
├── resumes/               # 备用简历目录
├── src/
│   ├── main.py            # CLI 入口（argparse）
│   ├── agent/
│   │   ├── graph.py       # LangGraph StateGraph 编排
│   │   ├── state.py       # AgentState（Pydantic）
│   │   └── nodes/         # 8 个流程节点，一节点一文件
│   ├── llm/
│   │   ├── client.py      # 统一异步 LLM 客户端（降级 / 重试 / 校验）
│   │   └── prompts.py     # 全部 Prompt 模板集中管理
│   ├── browser/
│   │   ├── manager.py     # Playwright 持久化浏览器管理
│   │   ├── navigator.py   # 导航 / 点击 / 等待封装
│   │   └── hitl.py        # HITL 暂停机制（BlockHandler）
│   ├── search/
│   │   ├── site_registry.py  # 站点配置注册表（含投递配额）
│   │   ├── discoverer.py     # 通用岗位发现（四层降级）
│   │   └── adapters/         # 站点专用适配器（含飞书/Moka/zhiye 基类）
│   ├── models/            # Pydantic v2 数据模型
│   ├── storage/
│   │   └── state_db.py    # SQLite 投递记录、缓存、断点续跑
│   └── utils/             # 日志等公共工具
├── tests/                 # 单元测试与离线集成测试
├── tools/                 # 站点排查、缓存诊断、LLM 连通性验证脚本
├── docs/                  # 问题排查报告
├── examples/              # 未知网站接入示例
└── requirements.txt
```

---

## 八、测试与验证

```bash
# 全部测试（核心页面解析用本地 fixtures，离线即可跑）
pytest tests/

# 验证 LLM 客户端连通性（会真实调用一次模型）
python -m tools.verify_llm_client
```

测试覆盖：数据模型校验、站点适配器、岗位发现与初筛、匹配与配额排序、表单填写、LLM 客户端降级与重试、SQLite 存储与状态恢复。

---

## 九、安全与合规

- 本项目仅用于**个人求职效率提升**与 Agent 技术实践；
- 使用时请遵守各招聘网站的服务条款，合理控制访问频率；
- 所有凭证只放在本地 `.env`，已通过 `.gitignore` 排除，请勿提交到公开仓库；
- Agent 不代签任何协议、不代做真实性声明、不自动提交申请——最终投递动作始终由人完成。

---

## License

MIT，详见 [LICENSE](./LICENSE)。
