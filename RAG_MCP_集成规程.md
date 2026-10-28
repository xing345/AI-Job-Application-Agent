# RAG 与 MCP 集成规程（自动求职 Agent）

> 目标：在现有 `D:\x\ai agent` 上，分两步加入 **RAG（检索增强生成）** 和 **MCP（Model Context Protocol）**。
> 本文是"怎么做、怎么用"的规程，不是最终代码；按阶段落地即可。
> 技术约束沿用项目：Python 3.11+、async/await、OpenAI 兼容接口、Pydantic v2、SQLite(aiosqlite)、`.env` 管理密钥、绝不自动提交。

---

## 0. 为什么要加这两个（解决什么真问题）

| 现状痛点 | 加 RAG 后 | 加 MCP 后 |
|---|---|---|
| 填表/开放问题时，把整份简历 + 全部 4 个项目 + 39 个技能一次性塞给 LLM，长、噪声大、抓不住岗位重点 | 按"当前 JD + 字段标签"语义召回最相关的项目/简历片段，只喂 top-k，更准更省 token | — |
| `known_fields` 记忆库现在靠字符串"互相包含"匹配，同义词/换说法就 miss | 用 embedding 语义相似度匹配，"身份证号"/"证件号码"也能对上 | — |
| Agent 能力只能在本命令行里跑，外部 LLM（Claude/Cursor）调不动 | 把"查记忆库/检索项目/发起一次投递"暴露成 MCP tools，任意 MCP 客户端可调用 | — |

面试一句话讲清：**RAG 解决"LLM 知道得太多但用不准"，MCP 解决"LLM 调不动外部工具/我的系统"。**

---

## 1. 总体架构（落地后长这样）

```
                         ┌─────────────────────────────┐
   填表/开放问题字段  ───▶ │  RAG Retriever              │
   (字段label + JD)        │  query embedding            │
                         │  ─▶ knowledge_chunks 余弦top-k │
                         │  ─▶ 召回片段喂给 LLM prompt    │
                         └─────────────────────────────┘

   Claude Desktop / Cursor (MCP 客户端)
        │  stdio
        ▼
   src/mcp/server.py  (FastMCP)
        ├─ tool: list_known_fields()      → 读 state_db.known_fields
        ├─ tool: search_personal_kb(q)    → 走 RAG retriever
        └─ tool: start_apply(apply_url)   → 触发 --apply-url 直达填表
```

---

## 2. 第一部分：RAG

### 2.1 关键判断：你的数据量很小，不必上重型向量库

个人知识库 = 简历全文 + 4 个项目 + ~39 技能 + known_fields 记忆条目 ≈ **50~150 个 chunk**。
这个规模**不需要 Chroma/Milvus**：直接把 embedding 存 SQLite，查询时全量算余弦相似度即可。
面试时这本身就是加分点（知道"小数据量别堆技术栈"）。

### 2.2 新增依赖

```txt
# requirements.txt 追加
numpy>=1.26.0          # 余弦相似度
# embedding 走 OpenAI 兼容 /v1/embeddings，不额外装 SDK（沿用 openai 包）
```

### 2.3 `.env` 新增配置

```bash
# DeepSeek 没有 embedding 接口，单独配一个 embedding provider（OpenAI 兼容）
EMBEDDING_BASE_URL=https://open.bigmodel.cn/api/paas/v4   # 例：智谱 embedding-3
EMBEDDING_API_KEY=你的智谱key
EMBEDDING_MODEL=embedding-3
EMBEDDING_DIMENSION=1024
```

> 备选：若想离线零成本，可换本地 `sentence-transformers`（装依赖较重，规程默认走云端 OpenAI 兼容接口）。

### 2.4 新增目录与文件

```
src/rag/
├── __init__.py
├── embedder.py     # embedding 调用（OpenAI 兼容 /v1/embeddings，带缓存）
├── store.py        # knowledge_chunks 表 + 写入 + 余弦 top-k 检索
├── indexer.py      # 把 简历/项目/技能/known_fields 切片入库
└── retriever.py    # 对外：retrieve(query, top_k=3) -> List[str]
```

### 2.5 数据表（state_db.py 升 v6）

```sql
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,          -- resume / project:<name> / skill / known_field:<key>
    text TEXT NOT NULL,            -- 切片原文
    embedding TEXT NOT NULL,       -- JSON list[float]
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kb_source ON knowledge_chunks(source);
```

### 2.6 实施步骤（RAG）

1. **embedder.py**：用现有 `AsyncOpenAI` 客户端调 `client.embeddings.create(model, input=[...])`，
   返回 `List[List[float]]`；同一文本做 md5 缓存避免重复调。
2. **indexer.py**：
   - 输入：`Resume`、`UserProfile.projects`、`UserProfile.skills`、`known_fields`。
   - 切片规则：一段经历/一个项目/一条技能 各成一个 chunk；简历全文按段落切。
   - 每 chunk 生成 embedding，upsert 进 `knowledge_chunks`。
   - 提供 `rebuild_index()`：清空重建（画像更新后调用一次）。
3. **store.py**：
   - `upsert_chunk(source, text, embedding)`
   - `search(query_emb, top_k)`：读出全部 chunk，numpy 算余弦，返回 top-k 的 text+source。
4. **retriever.py**：`async def retrieve(query: str, top_k=3) -> list[str]`
   —— embedder.embed(query) → store.search → 返回片段文本。
5. **接入填表**（`fill_application.py` 的 `llm_generate_values` 之前）：
   - 构造 `query = f"{字段label} {岗位title} {JD摘要}"`，
   - 调 `retriever.retrieve(query, top_k=3)`，
   - 把召回片段拼进 prompt 的"相关经历参考"区，替代现在把整份 profile 全量塞入。
6. **升级记忆库匹配**：`state_db.find_known_field` 增加一路——对 label 做 embedding，
   和 known_fields 的 text 算余弦，分数 >0.86 即命中（比字符串包含更稳）。

### 2.7 如何使用（RAG）

```bash
# 1. 首次/画像更新后，重建个人知识库索引
.venv\Scripts\python.exe -m src.rag.indexer --rebuild --profile data/user_profile.json --resume data/resume.pdf

# 2. 平时正常跑，填表时自动 RAG 召回（无需额外参数）
.venv\Scripts\python.exe -m src.main --apply-url "<链接>" --resume data/resume.pdf --profile data/user_profile.json
```

### 2.8 RAG 验收标准

- `--rebuild` 后 `knowledge_chunks` 有 N 条，无重复 source。
- 对 query `"做过的大模型 Agent 项目"` 能召回 RepoOps Agent / 求职 Agent 两条。
- 填表日志里能看到"召回片段"而非全量 profile。

---

## 3. 第二部分：MCP

### 3.1 定位

把本 Agent 的**只读能力 + 触发能力**暴露成 MCP tools，
让 Claude Desktop / Cursor 等 MCP 客户端直接调用。这是面试演示亮点。

### 3.2 新增依赖

```txt
# requirements.txt 追加
mcp>=1.2.0            # 官方 Python SDK（含 FastMCP）
```

### 3.3 新增目录与文件

```
src/mcp/
├── __init__.py
├── tools.py      # 纯函数：查记忆库 / 检索个人库 / 触发投递（调用现有 state_db、rag）
└── server.py     # FastMCP 实例，注册 tools，stdio 启动
```

### 3.4 暴露的 Tools（第一版）

| Tool 名 | 入参 | 作用 | 来源函数 |
|---|---|---|---|
| `list_known_fields` | 无 | 列出记忆库里所有用户补过的字段 | `state_db.list_known_fields()` |
| `search_personal_kb` | query, top_k=3 | 语义检索简历/项目/技能片段 | `rag.retriever.retrieve()` |
| `get_resume_summary` | 无 | 返回简历要点摘要 | `Resume.full_text()` 前若干字 |
| `start_apply` | apply_url, resume_path?, profile_path? | 触发一次 `--apply-url` 直达填表（异步任务） | 调 `main` 的直达分支 |

> 安全红线沿用项目规则：`start_apply` 只负责"打开并填表"，**绝不自动点提交**，最终仍 HITL 停在提交前。

### 3.5 server.py 骨架

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("auto-job-agent")

@mcp.tool()
async def list_known_fields() -> list[dict]: ...

@mcp.tool()
async def search_personal_kb(query: str, top_k: int = 3) -> list[str]: ...

@mcp.tool()
async def start_apply(apply_url: str) -> str: ...   # 不自动提交

if __name__ == "__main__":
    mcp.run()   # 默认 stdio
```

### 3.6 实施步骤（MCP）

1. `tools.py`：每个 tool 直接复用现有 `state_db` / `rag.retriever` 函数，不重写逻辑。
2. `server.py`：FastMCP 注册上述 tools；`start_apply` 用 `asyncio.create_subprocess`
   拉起 `.venv\Scripts\python.exe -m src.main --apply-url <url> ...`，返回进程提示。
3. 本地联调：`.venv\Scripts\python.exe -m src.mcp.server`，用 MCP Inspector 测每个 tool。

### 3.7 如何使用（MCP 接入 Claude Desktop / Cursor）

在 MCP 客户端配置文件里加：

```json
{
  "mcpServers": {
    "auto-job-agent": {
      "command": "D:\\x\\ai agent\\.venv\\Scripts\\python.exe",
      "args": ["-m", "src.mcp.server"],
      "cwd": "D:\\x\\ai agent"
    }
  }
}
```

然后在 Claude 里就能说：
- "列出我之前在求职表单里填过哪些字段"
- "从我的项目里找和这个岗位最相关的经历"
- "帮我打开这个投递链接开始填表"（Agent 仍停在提交前等你手动提交）

### 3.8 MCP 验收标准

- MCP Inspector 里 4 个 tools 都能调用并返回正确数据。
- Claude Desktop 连上后能问出"记忆库里有哪些字段"。
- `start_apply` 能拉起浏览器并停在提交前，不自动提交。

---

## 4. 落地顺序（建议）

| 阶段 | 内容 | 产出 |
|---|---|---|
| P1 | RAG：embedder + store + indexer + retriever | 个人知识库可重建、可检索 |
| P2 | RAG 接入填表 prompt + 记忆库语义匹配 | 填表更准、记忆命中更稳 |
| P3 | MCP server + 4 个 tools + Claude 接入 | 外部 LLM 可调用本 Agent |

先做 P1/P2（立刻提升填表质量），再做 P3（面试展示）。

---

## 5. 面试怎么讲（这个项目里的 RAG / MCP）

- **RAG**："我的个人资料 chunk 量小，所以没上 Chroma，直接 embedding 存 SQLite、查询算余弦；
  填表时按当前 JD+字段标签召回 top-k 相关项目片段，而不是把整份简历塞给 LLM，省 token 也更贴岗。"
- **MCP**："我把记忆库查询、个人库检索、发起投递封装成了 MCP tools，
  用 FastMCP 起 stdio server，Claude Desktop 能直接调用；投递动作仍然只填表不提交，保留 HITL。"

---

## 6. 注意事项

- embedding 与 chat 可以用不同 provider（DeepSeek 无 embedding），全部走 `.env`，不硬编码。
- `knowledge_chunks` 的 embedding 用 JSON 列存；若以后 chunk 过万再迁 `sqlite-vec`。
- MCP 的 `start_apply` 受现有浏览器 profile 占用约束，多开需 `BROWSER_PROFILE_SUFFIX`。
- 全程遵守：不自动提交、遇登录/验证码 HITL、密钥只放 `.env`。
