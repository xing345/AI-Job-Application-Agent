# 职位搜索问题诊断与修复报告

> 范围：`src/search/*`（找岗 → 抓 JD → LLM 匹配 → 排序）与 `hitl.py`。
> 结论全部基于代码 + `search_pipeline.log` 里的真实运行记录，不是现象复述。
> 修改后 `pytest tests` 全绿：**131 passed**（原基线 104 passed / 1 failed）。

---

## 一、诊断：5 个现象的真实根因

### 现象1「Boss直聘、猎聘上找不到我需要的岗位」

**根因 A（主因）：聚合门户从来没有执行过「站内关键词搜索」。**

- 找岗链路对**所有**站点一视同仁地走「打开列表页 → 按类别导航 → 翻页遍历」。
  这条路线对公司官网是对的（官网的类别导航就是它的职位索引），
  但对聚合门户是错的：Boss 的 `web/geek/job`、猎聘的 `zhaopin/` 打开后是
  **全网默认 feed**，与用户方向无关。
- 代码里其实已经写好了站内搜索框函数，但**从未被调用**（死代码）：
  - `browser_job_finder.py` 的 `_try_role_search()`（改动前 2030 行）
  - `_fallback_role_terms()`（改动前 2164 行）
  全局 grep 只有定义、没有调用点。
- 后果在日志里非常明确（`search_pipeline.log` 2026-09-20 那次运行）：
  - L3692 `用户选择跳过：出现验证码/人机验证 https://www.zhipin.com/web/geek/job`
  - L3697 `猎聘 本站 0 个职位：列表页 about:blank`（页面被反爬置空，接口 22 条职位全被判为方向无关）
  - L3700 `标题方向筛选：344 个职位锚点 -> 2 个相关` → L3701 `前程无忧 最终抽取 0 个职位`
  - 更早一轮（L829）Boss 抽到的 10 个「职位链接」全是站点导航：
    `https://www.zhipin.com/`、`/chongqing/`、`/web/geek/jobs`、`/gongsi/`、`/school/`、
    `/returnee_jobs/`、`app.zhipin.com/`、`youle.zhipin.com/recommend/selected/` …
    这些后来被当成 JD 去抓（L866-874 全部抓取失败）。

**根因 B：门户入口被「类别导航」带走（见现象5）。**

**根因 C：「方向相关 N 个 → 最终 0 个」两套判据口径不一致。**
`_prune_by_title_relevance()` 只按标题关键词判「方向相关」，而真正入库还要再过
`_looks_like_job_detail()`（URL 必须像详情页 + 文本必须像职位名）。
先筛方向、后筛详情，于是页脚/筛选标签被算成「相关」，日志却显示 0 个入库，
把排查方向引向「筛得太狠」，实际是顺序问题。

### 现象2「遇到登录墙/验证码会报错/失败」

**根因 A：跨阶段浏览器不共享会话，用户登录白做。**
- `BrowserJobFinder._start_browser()`（改动前 828 行）用 `chromium.launch()` + `new_context()`，
  每次 `discover_fixed_sites` / `discover_company_careers` 结束都 `_stop_browser()`；
  抓 JD 的 `JobMatcher.fetch_jd_texts()`（改动前 260-265 行）又**另起一个全新浏览器**。
- 于是：用户在发现阶段的窗口里登录了 Boss → 窗口关闭 → 抓 JD 阶段新浏览器没有
  任何 cookie → 又弹登录墙。用户被迫反复登录。

**根因 B：`BlockHandler` 的「同域只打断一次」在浏览器重建后仍按「已通行」放行。**
- `hitl.py::handle()`（改动前 97-100 行）遇到 `_seen_domains` 命中就直接
  `return True`；而 `_start_browser()` 重建浏览器时并不会清空这个集合。
- 结果：新浏览器其实没登录，代码却认为「用户已处理过」，静默继续 →
  JD 抓空（正是 AGENTS.md 明令禁止的「静默跳过」）。

**根因 C：真实的报错来自「浏览器/上下文已被关闭」。**
- `search_pipeline.log` L866-874：`抓取 JD 失败: …, 错误: Page.title: Target page,
  context or browser has been closed`（一次 11 个 URL 里 9 个失败）；
  L856-858 `锚点抽取失败: … Target page, context or browser has been closed`。
- 触发条件是用户在 HITL 期间与可见浏览器交互（关标签页/关窗口），
  而并发的其它 4 个页面仍在跑 → 集体抛错。日志里 `JobMatcher` 早期版本还有
  `'JobMatcher' object has no attribute 'user_agent'`（L78、L576），已在本轮之前修掉。

**根因 D：阻断判定只看文案，会误判。**
- `_page_looks_blocked()`（改动前 2122 行）与 `JobMatcher._is_blocked_page()`
  （改动前 157 行）都只做**正文关键词匹配**。Boss 正常页面的登录弹窗里有
  「验证码登录」「扫码登录」文案 → 被判成 captcha/登录墙，
  一个本来能用的页面被整站跳过。

### 现象3「Boss 手动登录时网页不停闪烁」

**根因 A（主因）：抓 JD 阶段同时开 5 个**可见**标签页。**
- `SearchPipeline.__init__` 硬编码 `self.jd_concurrency = 5`（改动前 114 行），
  `JobMatcher.fetch_jd_texts(concurrency=5)` 用 `asyncio.Semaphore(5)` 并发开页
  （改动前 257 行），且 `browser.headless=false` → Chromium 不断新建/切换/关闭前台标签页，
  每个页面还会 `page.mouse.wheel()` 滚动（`_render_job_page`）→ 用户看到的就是「抖/闪/重载」。

**根因 B：暂停期间并发任务没有被冻结。**
- `BlockHandler.handle()` 等待用户输入时，其它 `fetch_one` 任务照样在开新页、跑 `goto`；
  没有任何「暂停闸门」能让浏览器停下来。

**根因 C：HITL 之后无条件重新渲染 = 重载风暴。**
- `fetch_jd_texts()` 在 `handle()` 返回 True 后就 `_render_job_page(page, url, …)`
  （改动前 286-290 行），也就是对用户刚登录好的页面再 `page.goto()` 一次；
  同域的第二、三个页面走 `_seen_domains` 快速通道，同样再重载一遍 → 页面反复刷新。

**根因 D：浏览器反复启停。** 发现阶段每个通道结束都 `_stop_browser()`，公司通道又
`_start_browser()`；抓 JD 再起一次。用户视角就是窗口反复开关。

### 现象4「字节校招列表页 1225 个岗位，Agent 只找到几个」

日志给出的答案是 **6 个**（`search_pipeline.log` L3708）：
`字节跳动校招 最终抽取 6 个职位（锚点 0 个/方向相关 0 个，JSON 响应 46 个，接口认出职位 27 个）`。
四个叠加的硬编码上限：

| # | 位置（改动前） | 行为 | 后果 |
|---|---|---|---|
| 1 | `BrowserJobFinder.__init__` 319 行 `max_jobs_per_site=10` | 每站最多 10 个 | 上限即结果数 |
| 2 | 同处 323 行 `max_list_pages=3` | 每类最多翻 3 页 | 1225 个岗位只看到前 3 页 |
| 3 | `_walk_jobs_json` 1538 行 `len(found) >= 40`、1588 行 `node[:80]` | 接口职位总量 40 条、单列表 80 条 | 翻页拿到的职位被砍掉 |
| 4 | `SearchPipeline.__init__` 119-128 行构造 `BrowserJobFinder` 时**没传**这些参数 | 即便 config 改了也无效 | 结构上不可配置 |

而且字节校招列表页是 SPA：`列表第 1 页收集 0 个职位锚点`（L3706），
锚点通道完全失效，唯一入口就是接口通道——恰好被第 3 条上限卡死。

### 现象5「硬编码导航规则，LLM 不参与『下一步点哪里』」

**根因 A：只在 URL 形状上判「是不是列表页」。**
- `_find_category_link()`（改动前 1286 行）只调用 `_looks_like_listing_url(page.url)`
  （改动前 2009-2028 行），其 `list_hints` 只覆盖 `/positions /jobs /campus /recruit …`。
- 因此 `zhipin.com/web/geek/job`、`liepin.com/zhaopin/`、`we.51job.com/pc/search`
  这些**明明是列表页**的 URL 判不出来 → 继续走类别导航。
- 日志实证：L3704 `按方向选中官网类别: https://jobs.bytedance.com/campus/page-AgCQiO`
  ——导航栏里含「技术」二字的**宣传页**把 Agent 从列表页带走了（用户描述的正是这个）；
  更早的版本还会选中 `jobs.51job.com/yingjian/`（硬件类）、`baike.51job.com/zhiwei/01241/`（百科页）、
  `app.mokahr.com/...#/job/<guid>`（职位详情页）、`#/jobs?page=2`（分页链接）。

**根因 B：没有任何"我已经在列表页了"的 DOM 证据判据。**
已有岗位渲染出来的页面上，规则仍然愿意为 3 分权重的导航文字跳走。

**根因 C：`_try_role_search()` / `_fallback_role_terms()` 是死代码**（见现象1根因 A）。

---

## 二、方案与优先级

| 优先级 | 事项 | 理由 |
|---|---|---|
| **P0（止血，已完成）** | 列表页 DOM 证据判据 + 门户站内搜索 + 上限全部配置化 + 阻断判定加 DOM 证据 + HITL 暂停闸门 + 登录态复用 + 判据口径统一 | 都是"改一行就见效、不改架构"的确定性修复，直接对应现象1/2/3/4/5 |
| **P1（已完成，可关）** | 受约束的 LLM 导航裁决器 `NavAdvisor` | 只在规则判不准时做**选择题**，给现象5 一个可解释的架构答案 |
| **P2（未做，建议后续）** | ① 把 SPA 列表的翻页改成"按接口分页参数驱动"（现在靠点『下一页』按钮，SPA 常失效）；② `use_tavily_search` 开关接线或删除；③ `browser_agent` / `smart_form_filler` 也复用同一登录态目录 | 收益存在但要动更多调用方，本轮不碰以免破坏现有功能 |

### 关于现象5的取舍（为什么不让 LLM 全权导航）

**建议：LLM 只参与「模糊的路口选择」，不参与「执行」。**

交给确定性代码（继续用规则）：
- 翻页、点卡片、判"这个 URL 像不像职位详情"——这些有**客观证据可校验**
  （接口 JSON、DOM 锚点、URL 正则），0 成本、100% 可复现、出错能精确到行；
- 已经渲染出岗位列表时的任何跳转决策——**有岗位就是最好的证据**，不需要模型判断。

交给 LLM（新增 `NavAdvisor`）：
- 候选类别链接**同分或多个**、或页面处于"可能有列表也可能没有"的中间态时；
- 且 LLM 的能力被严格限制为：**在规则已经算好的候选里选下标，或回答 stay**。

护栏（都实现了）：
1. 候选集由确定性代码生成：同站、短文本、非详情页、非提交/登录类
   （`DANGEROUS_NAV_TEXT`），LLM 拿到的东西本身就不可能造成误点；
2. LLM 只能返回 `{"action","index","reason"}`，下标越界/非 JSON/超时/异常
   **一律回退规则结果**（`NavAdvisor.choose()` → `None`）；
3. 硬预算：`max_calls_per_search`（每轮搜索上限，默认 4）+ `timeout_s`（默认 25s），
   且只在"模糊"时触发（规则分数不接近、或页面已有零星职位链接）；
4. 一键关闭：`search.nav_advisor.enabled=false` 回到纯规则；
5. 每一次裁决都写日志（`导航裁决(LLM): …`），可事后审计。

这样"稳定路径"（90%）依旧是 0 成本、可复现的规则；只有真正判不准的 10% 才付
token 钱，且最坏情况退化为原来的行为。

---

## 三、实施清单（本轮改动）

### `src/search/hitl.py`
- 新增暂停闸门：`is_paused` / `async wait_until_resumed()`；`handle()` 询问用户期间
  清空内部 `asyncio.Event`，恢复时置位 → 并发浏览器操作在用户操作期间全部冻结。
- `reset()` 语义明确化：**浏览器重建时必须调用**，否则"已通行"是假的。

### `src/search/nav_advisor.py`（新增）
- `NavAdvisorConfig`（从 `config.json` 的 `llm` 段兜底读 key/base_url/model）
  + `NavAdvisor.choose()`：受约束的选择题裁决器，含候选白名单过滤、
  预算、超时、非法输出降级、决策日志。

### `src/search/browser_job_finder.py`
- `_find_category_link()`：先看 URL，再看 **DOM 证据**（`_job_link_count() >= nav_stay_min_job_links`
  → 直接留在列表页）；候选加 `DANGEROUS_NAV_TEXT` 过滤；模糊时问 `NavAdvisor`。
- `_looks_like_listing_url()`：补 `/geek/job`、`/zhaopin` 等门户列表/搜索路径。
- **新增 `_portal_search_url()`**：聚合门户入口改写为站内搜索 URL
  （`PORTAL_SEARCH_URLS`：Boss/猎聘/前程无忧/智联/拉勾）；只对 `kind=portal` 生效，
  **公司官网行为不变**（这是对 AGENTS.md「不要依赖关键词搜索」的一处刻意例外，
  理由见上：门户整站产品就是搜索框，官网的索引才是类别导航）。
- `_discover_jobs_on_site()`：新增 `portal_search` 参数；新增 3.05「门户站内搜索兜底」；
  用新方法 `_filter_detail_like()` 把"先判像不像详情页、再判方向"固定下来，
  并输出每个丢弃原因的计数（修掉「相关 2 个 → 最终 0 个」的假象）。
- 所有上限走构造参数：`max_jobs_per_site / max_list_pages / max_card_clicks / max_api_objects`。
- `_walk_jobs_json()`：`40`、`node[:80]` 两个硬编码改为 `max_api_objects`。
- `_page_looks_blocked()`：改为"强特征（`STRONG_CAPTCHA_HINTS`）直接判 + 弱特征必须有
  DOM 证据（`_block_probe()` 数密码框/验证控件）"，不再仅凭文案。
- `_start_browser()`：默认使用**持久化用户目录**（`launch_persistent_context`，
  失败自动回退匿名上下文），并在每次启动时 `block_handler.reset()`；
  新增 `_context_alive()` 兼容持久化上下文（`context.browser` 可能为 None）。
- `build_nav_advisor()` 静态工厂供管道使用。

### `src/search/job_matcher.py`
- `JobMatcherConfig` 新增 `user_data_dir` / `persist_login` / `visible_concurrency`，
  并从 `config.json` 的 `browser` 段兜底。
- 新增 `_launch_browser()`：**与找岗阶段共用同一个登录态目录**（登录一次，跨阶段跨轮复用）。
- `fetch_jd_texts()`：可见浏览器下并发收敛到 `visible_concurrency`；
  每个任务开工前 `wait_until_resumed()`；HITL 之后**优先就地复用页面**
  （`_reuse_page_text()`），只有确实还是拦截页才重新渲染。
- `_is_blocked_page()`：强/弱特征分离，弱特征需 DOM 证据；`_has_block_control()` 只数不点。

### `src/search/search_pipeline.py` / `job_searcher.py` / `orchestrator/agent_orchestrator.py`
- 新增参数与配置贯通：`max_jobs_per_site / max_list_pages / max_card_clicks / max_api_objects /
  jd_concurrency / portal_keyword_search / nav_advisor / browser.*`；
  `JobSearcher` 启动时打印一行"找岗成本上限"，便于确认配置生效。
- `run_search_pipeline()` 每轮重置裁决器预算。

### 测试
- 新增 `tests/test_search_fix_phase1.py`（26 个离线用例）：上限可配置、
  门户 URL 改写、列表页不跳转、提交/登录类候选被剔除、裁决器否决/选择/失败降级/预算/
  危险候选过滤、阻断判定的 DOM 证据、HITL 暂停闸门与 reset、判据口径一致性、配置贯通。
- 修正一个**改动前就已失败**的用例 `test_category_link_rejects_detail_pages`：
  它断言 Moka 的 `#/jobs` 页面必须返回某个类别链接，但该 URL 已被识别为职位列表页
  （`/campus-recruitment`），返回 `None` 才是正确行为。现在断言的是真正的不变量
  「绝不导航到 `#/job/` 详情页」。

---

## 四、配置（`config.json`，已写入；`config.example.json` 同步）

```json
"search": {
  "max_results_per_search": 50,   // 最终返回岗位上限
  "jd_fetch_limit": 40,           // 进入 JD 抓取/LLM 评估的候选上限（直接决定 LLM 成本）
  "max_jobs_per_site": 25,        // 【新】每站最多抽取多少岗位（原硬编码 10）
  "max_list_pages": 4,            // 【新】每类最多翻几页（原硬编码 3）
  "max_card_clicks": 16,          // 【新】单站最多点几张 SPA 卡片（原 12）
  "max_api_objects": 200,         // 【新】单站最多认多少条接口职位（原 40/80）
  "jd_concurrency": 3,            // 【新】JD 抓取并发（原硬编码 5）
  "portal_keyword_search": true,  // 【新】聚合门户改用站内搜索 URL
  "recruit_type": "campus",
  "nav_advisor": {                // 【新】受约束的 LLM 导航裁决器
    "enabled": true,
    "max_calls_per_search": 4,
    "timeout_s": 25,
    "max_candidates": 6
  }
},
"browser": {
  "headless": false,
  "persist_login": true,                       // 【新】复用登录态（用户目录）
  "user_data_dir": "data/browser_profile",     // 【新】已加入 .gitignore
  "visible_concurrency": 2                     // 【新】可见浏览器下 JD 抓取并发上限
}
```

**成本换算参考**：11 个站点 × `max_jobs_per_site` 是"发现阶段"上限；
真正花钱的是 `jd_fetch_limit` 次 LLM 评估（每条约 1k token）。
把 `max_jobs_per_site` 提到 60 只会让候选池更大、排序更准，不会直接放大 LLM 调用；
要放大评估量再调 `jd_fetch_limit`。

---

## 五、验证方法

### 1. 离线回归（先跑，确认没改坏）
```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
# 期望：131 passed
.\.venv\Scripts\python.exe -m pytest tests/test_search_fix_phase1.py -q
# 期望：26 passed
```

### 2. 问题4：字节跳动「1225 个岗位只找到几个」
```powershell
.\.venv\Scripts\python.exe run_agent.py     # 模式 1（岗位诊断）或 search 字节跳动
```
在 `search_pipeline.log` 中看这一次的日志行：
- **修复前**：`列表第 1 页收集 0 个职位锚点` → `字节跳动校招 最终抽取 6 个职位`
- **修复后**期望：
  - `字节跳动校招 聚合门户改用站内搜索入口: …`（仅门户站会出现）
  - `列表第 1 页收集 … / 第 2 页 … （累计 …, 接口职位累计 …）`——接口职位随翻页增长
  - `字节跳动校招 最终抽取 N 个职位（锚点 … → 像职位详情 … → 方向相关 …；… 接口认出职位 M 个）`
    其中 **N 应显著大于 6**（在 25/4 页的默认上限内）；
  - 想再多抓：`max_jobs_per_site` 提到 60、`max_list_pages` 提到 8，
    再按需提高 `jd_fetch_limit`。
- 判断"没停在列表页"的负向信号：日志出现
  `按方向选中官网类别: https://jobs.bytedance.com/campus/page-AgCQiO`。
  **修复后这类宣传页不该再被选中**；若出现应为
  `… 已渲染 N 个职位详情链接，判定已在职位列表页，跳过类别导航跳转`。

### 3. 问题1：Boss / 猎聘
- 日志应出现：`Boss直聘 聚合门户改用站内搜索入口: https://www.zhipin.com/web/geek/job?query=…`
  （猎聘为 `https://www.liepin.com/zhaopin/?key=…`）。
- 若站点不认 URL 参数，应看到兜底：
  `… 默认列表无方向相关岗位，已改用站内搜索框` + `已在站内搜索框输入岗位: …`。
- 结果行 `各通道发现职位数: portal=…` 不再恒为 0；`Boss直聘 本站 0 个职位` 的
  三条常见原因提示里，会附带各判据的丢弃计数。
- 若某站仍为 0：日志会明确写 `锚点 A 个（判非职位详情而丢弃 B 个：导航文本 …、非职位路径 …、
  仍是列表页 …、不像详情页 …｜像详情页 C 个，其中方向相关 D 个）`，
  可以直接看出是"没抓到"还是"筛掉了"。

### 4. 问题2/3：Boss 登录时页面是否静止
手工验证步骤：
1. `config.json` 保持 `browser.headless=false`、`persist_login=true`；
2. 跑 `run_agent.py` → `search`；
3. 遇到登录/验证时会看到终端横幅：
   `⛔ Agent 在这里停住了，需要你手动处理：…`
   **此时浏览器必须完全静止**：不再新开标签页、不再滚动、不再重载
   （日志会有一行 `等待用户在浏览器里完成处理（Agent 暂停所有页面操作）...`）；
4. 在可见窗口里扫码/输验证码登录，回到终端按回车；
5. 期望：
   - 日志 `JD 抓取浏览器已启动（复用登录态目录 data/browser_profile）`，
     且**不再第二次弹登录**（同一域名只打断一次）；
   - 不再出现 `Page.title: Target page, context or browser has been closed` 批量失败；
   - 可见浏览器最多 2 个标签页（`visible_concurrency=2`），不再有 5 个标签页轮流闪。
6. 重启 Agent 再搜一次 Boss：应**免登录直接出结果**（登录态已在 `data/browser_profile`）。

### 5. 问题5：导航决策
- 观察日志中每个站点的三选一：
  - `… 已是职位列表页，跳过类别导航跳转`（URL 证据）
  - `… 已渲染 N 个职位详情链接，判定已在职位列表页，跳过类别导航跳转`（DOM 证据）
  - `按方向选中官网类别: …`（真的不在列表页时才跳）
- 若出现 `导航裁决(LLM): 留在当前页 —— …` 或 `导航裁决(LLM): 选择候选[i] …`，
  说明模糊场景已交给 LLM 裁决（每次附一句话理由，可审计）；
  纯规则场景不会有这类日志（也不产生 token 消耗）。
- 关掉它验证降级：`search.nav_advisor.enabled=false` → 行为回到纯规则，
  且不影响任何其它结果。

---

## 六、已知遗留 / 未做（明确说明，不静默）

1. `search.use_tavily_search` 仍是**未接线开关**（`SearchPipeline` 只记录不使用）。
   本轮没有实现 Tavily 关键词通道，也没有删除——删除属于接口变更，需要你确认。
2. 门户站内搜索 URL 的**查询参数名**是按各站惯例写的（Boss `query`、猎聘 `key`、
   51job `keyword`、智联 `kw`、拉勾 `kd`）。若某站改版导致参数失效，会自动走
   「站内搜索框」兜底路径，不会静默返回空；但仍建议实测一次并回来更新
   `PORTAL_SEARCH_URLS`。
3. SPA 列表分页仍依赖"点下一页/加载更多"按钮（`_goto_next_list_page`）。
   对无限滚动的站点，翻页收益有限——这是 `max_list_pages` 的天然上限。
   下一步可改为解析接口的分页参数直接请求。
4. `BrowserJobFinder` 与 `JobMatcher` 已共用登录态目录；
   `browser_agent` / `smart_form_filler`（投递阶段）仍是各自独立的浏览器，
   若在投递阶段也遇到登录墙，需要同样处理（本轮未动，避免影响投递链路）。
5. 持久化用户目录在多实例并发运行时会被 Chromium 独占。若你同时跑两个
   Agent 实例，请给其中一个改 `browser.user_data_dir`；启动失败会打印
   `持久化浏览器目录不可用（…），回退匿名上下文` 并继续工作，不会崩。
