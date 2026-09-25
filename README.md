# AI 情报站（AI Daily Brief）

让关注 AI 的人，在几分钟内了解近期值得关注的动态。
聚合多个独立信息源的 AI 资讯，**每日自动更新**，支持关键词搜索、来源筛选、时间范围切换，以及 Obsidian 风格的**关系图谱**浏览。

```
   4 个公开信息源
        │  ① 采集 + 去重 + 遗忘策略              ┌─────────── GitHub Actions（每 3 小时，免费额度）───────────┐
        ▼                                        │ fetch.py → analyze.py（LLM 分类/摘要）→ 评测门禁 → 部署  │
   data/news.db（SQLite，随仓库提交）            └───────────────────────────┬──────────────────────────────┘
        │  ② 导出静态 JSON                                              │
        ▼                                                              ▼
   web/data.json ──► GitHub Pages（纯静态：资讯流 + 关系图谱，访客零等待）
   web/stats.json ─► 页脚「成本透明」区块

   可选：本机/容器 API（线上不部署）──► AI 问答 /ask（检索 + LLM + 引用校验）· 人工审核 /reviews · 成本看板 /api/stats
                                        同一套 LLM 客户端与 trace 表，供 Agent（LangGraph）与 MCP Server 复用
```

**文档导航**：本文件（概览 / 部署 / 案例复盘）· [ARCHITECTURE.md](ARCHITECTURE.md)（数据流 / 模块 / 数据模型 / 取舍）· [EVALS.md](EVALS.md)（指标口径 / 门禁规则 / 已知差距）

## 功能一览

| 模块 | 说明 |
|---|---|
| 资讯流 | 标题 / 摘要 / 来源 / 发布时间 / 原文链接；长标题截断、无摘要兜底 |
| 查找筛选 | 关键词搜索（防抖）、按来源筛选、今天 / 近 7 天 / 全部切换、一键清除条件、空结果提示 |
| 关系图谱（亮点） | 新闻 + 关键词节点力导向图；拖拽 / 缩放 / 悬停高亮关联 / 点击节点查看详情；资讯卡片上的关键词可一键跳转图谱定位 |
| 每日更新 | 外部定时器（cron-job.org）每 3 小时触发 GitHub Actions `workflow_dispatch`，工作流负责采集与部署（北京 02:20 / 05:20 / 08:20 / 11:20 / 14:20 / 17:20 / 20:20 / 23:20）；也保留 `workflow_dispatch` 手动触发入口 |
| 容错 | 单源失败不影响其他源与已有数据；区分「无新增」与「抓取失败」；失败状态在页脚展示 |

## 数据来源

| 来源 | 获取方式 |
|---|---|
| Hacker News | Algolia 官方 API（`hn.algolia.com/api/v1/search_by_date?query=AI&tags=story`，按时间倒序取 40 条） |
| TechCrunch AI | 公开 RSS |
| The Verge AI | 公开 RSS |
| arXiv cs.AI | 公开 RSS |

均为公开、信息源允许的获取方式，不绕登录 / 付费墙 / 反爬。

## 本地运行

**Windows 一键启动**（推荐，双击即可）：

```
启动全栈.bat      # 同时起 API(8000) + 静态站(8765)，并自动打开浏览器
```

它做三件事：① 探活 8000 —— 已有健康 API 就复用，没有才 `uvicorn` 起一个（避免端口冲突）；② 等 API 就绪（冷启动约 10 秒，失败只提示不阻塞）；③ 起静态站并打开 `http://127.0.0.1:8765/`。两个服务分别占用一个命令行窗口，**关掉窗口即停止对应服务**。只想要静态预览（不需要 AI 问答）的话，用原来的 `启动预览.bat` 即可。

> 注意：**本地不会自动启动 API**，这是设计使然 —— 线上站点是纯静态部署（GitHub Pages），只有「AI 问答」「人工审核」「成本看板」需要后端。本地点问答若报「连不上 API 服务」，就是这个原因；线上演示站要具备问答能力，见下面的「部署到 Fly.io」。

手动命令（macOS / Linux / 想自己控端口）：

```bash
pip install -r requirements.txt
python fetch.py                                        # 采集 + 去重 + 导出 web/data.json
python -m uvicorn api.main:app --port 8000             # 可选：AI 问答 / 人工审核（需先激活 venv）
cd web && python -m http.server 8080                   # 静态预览
# 浏览器打开 http://localhost:8080
```

> Windows 下若已按上面的方式建好 `.venv`，把 `python` 换成 `.venv\Scripts\python.exe` 即可（`启动全栈.bat` 已自动处理）。

## Docker 三步启动（API）

静态站不需要容器（Pages 即可），容器化的是 **API 服务**（共 10 个端点：`/health`、`/news`、`/news/{id}`、`/analyze/trigger`、`/ask`、`/api/stats`、`/insight`、`/reviews`、`/reviews/submit`、`/review/{id}`）：

```bash
git clone <仓库地址> && cd ai-daily-brief   # 1. 拿到代码与 data/news.db
cp .env.example .env                        # 2. 可选：填 DEEPSEEK_API_KEY（不填仅 /ask 不可用）
docker compose up --build                   # 3. 起服务
# → 接口文档 http://localhost:8000/docs   → 健康检查 http://localhost:8000/health
```

验证要点：

- `/health` 返回 `{"status":"ok","news_count":1384}`，说明容器读到了挂载进来的真实库；
- 嵌入模型（`BAAI/bge-small-zh-v1.5`）已在**构建期**写入镜像，首次检索不需要联网；
- `data/` 以卷挂载，Actions/本地 `fetch.py` 更新数据后**不用重建镜像**即可生效；
- 镜像以非 root 用户 `app` 运行，`.env` 被 `.dockerignore` 排除，密钥不进镜像层。

**取舍说明（与原计划的偏离）**：原计划是 `app + postgres(pgvector) + 一次性 migrate` 三件套。
实际落地只有一个 `api` 服务，理由：本项目的向量检索是「本地小模型嵌入 + SQLite BLOB」
（`retrieval.py`），单写者、当前 1.9MB 数据量，pgvector 没有收益却要多维护连接池与迁移脚本；
`db.py` 的 PostgreSQL 分支（`DATABASE_URL`）保留但**未启用**，如实标注而非假装支持。
schema 初始化改为 API 启动时执行 `init_sqlite`（幂等：`CREATE TABLE IF NOT EXISTS` + 按缺失列 `ALTER`），
因此也不需要单独的 migrate 容器。

## 部署

静态站点，站点根目录为 `web/`。本仓库使用 **GitHub Actions 部署到 GitHub Pages**：

1. 仓库 Settings → Pages → Source 选择 **GitHub Actions**
2. push 到 `main` 或在 Actions 页手动运行「每日数据更新与部署」工作流
3. 工作流先运行 `fetch.py` 更新数据、提交 `data.json`，再把 `web/` 发布到 Pages

演示地址：`https://<用户名>.github.io/<仓库名>/`（首次部署完成后可访问）。
定时触发由外部服务 **cron-job.org**（免费）调用 GitHub 官方 `workflow_dispatch` REST API 完成，cron `20 */3 * * *`（北京时间 02:20 / 05:20 / 08:20 / 11:20 / 14:20 / 17:20 / 20:20 / 23:20，全部避开整点高负载时段）。仓库内的 `workflow_dispatch` 入口直接复用，无需部署任何 webhook 服务。GitHub Actions 工作流定义见 `.github/workflows/update.yml`。触发时机以 **cron-job.org 触发记录 + Actions 页面的运行记录**（事件列显示 `workflow_dispatch`）共同验证为准，详见「案例四」「案例六」。

## 技术选型理由

- **Python + feedparser 采集，SQLite 存储**：URL 规范化哈希 + 标题哈希双去重，`INSERT OR IGNORE` 天然幂等——重复导入同一输入不产生重复记录。单文件库随仓库提交，schema 用幂等 `ALTER` 原地升级，不需要独立迁移脚本/容器。
- **导出静态 `data.json` + 原生前端**：零后端运行时成本，任何静态托管可复现；前端无框架，评审在干净环境只需 Python 即可跑通全链路。
- **D3.js 本地打包**（`web/vendor/d3.v7.min.js`）：图谱不依赖 CDN，离线可运行。
- **统一 LLM 入口 `llm.py`**：请求、超时、错误分类、计量、埋点收敛到一处。收口前 5 处各写一份 `requests.post`，只有分类链路会记账 —— 成本看板只能看到 13% 的调用（对账实测）；收口后分析/问答/洞察/Agent/评测全部入账。
- **本地嵌入模型 + BM25 + RRF 融合**：嵌入在本地推理（Docker 构建期落盘，运行时离线可用），零边际成本；代价是轻量模型召回有限（Recall@5=0.26，见 `EVALS.md`）。
- **外部定时器（cron-job.org）+ GitHub Actions**：不依赖个人电脑开机；GitHub Actions 处理采集/部署（免运维、artifact 上发），cron-job.org 处理调度（不依赖 GitHub 自身 `schedule` 事件，规避新仓库偶发不派发的问题）；详细原因与验证见「案例四」「案例六」。

> 完整的数据流、模块依赖、数据模型与设计取舍见 **[ARCHITECTURE.md](ARCHITECTURE.md)**；评测口径、指标定义与门禁规则见 **[EVALS.md](EVALS.md)**。

## 部署 API（让线上演示站也能 AI 问答）

**为什么需要这一步**：站点是纯静态的（GitHub Pages），问答必须有个后端。推荐使用 **Railway.app**（支持 Docker，GitHub 登录，有免费额度）。

**Railway.app 部署步骤**（约 5 分钟）：

1. 访问 [railway.app](https://railway.app)，用 GitHub 账号登录
2. 点击 "New Project" → "Deploy from GitHub repo" → 选择本仓库
3. 在 Settings → Variables 中添加：
   - `DEEPSEEK_API_KEY` = 你的 DeepSeek API Key
4. 在 Settings → Generate Domain 中生成公开域名
5. 等待自动部署完成（首次约 3-5 分钟）

**把 API 地址交给 Pages**：

```bash
# GitHub 仓库 → Settings → Secrets and variables → Actions → Variables → New variable
# 名称 AI_API_BASE，值 https://your-app.up.railway.app（Railway 分配的域名）
```

**为什么不用改代码**：定时工作流会读 `AI_API_BASE`，`fetch.py` 导出时把它写进 `web/config.js`；前端从该文件取地址（本地未配置则自动回落 `http://localhost:8000`）。

**部署后自检**：

```bash
curl https://your-app.up.railway.app/health                     # 期望 {"status":"ok", ...}
curl -s https://your-app.up.railway.app/api/stats | head -c 200 # 能看到 ask_quota 配额视图
# 打开 Pages 站点 → 「AI 问答」标签 → 提问，回答下方显示「今日还可提问 N 次」
```

### 公开演示的配额（保护你的 API 额度）

演示地址公开后，`/ask` 就是「任何人点一下都花你钱」的入口，所以默认带双闸门（`api/ratelimit.py`）：

| 闸门 | 默认值 | 环境变量 | 作用 |
|---|---|---|---|
| 单 IP 每日 | **5 次** | `ASK_DAILY_PER_IP` | 防个人刷；超限返回 429 + 友好说明 |
| 全局每日 | 100 次 | `ASK_DAILY_GLOBAL` | 防换 IP 刷；封顶约 ¥1/天 |

- 配额在**检索之前**判定 —— 拒绝时不加载嵌入模型、不调 LLM，一分钱不花（有测试锁定这一点）。
- 前端显示剩余次数（「公开演示：今日还可提问 N 次」），避免用户被突然拒绝。
- **已知边界**：计数在内存中，服务重启即清零（跨实例/持久化需引入 Redis，对本场景不值得）；按北京日期切分，与站点展示时区一致。

> 不想公开问答的话：不配置 `AI_API_BASE` 即可 —— 演示站保持纯静态，问答模块提示「连不上 API 服务」，其余功能完全正常。这正是计划书风险表第 12 条的降级方案。

## 时间口径

- 存储：UTC ISO8601；展示：Asia/Shanghai。
- 「今天」= 北京时间当日 00:00 起；「近 7 天」= 当前时刻向前 7×24h。
- 发布时间缺失时标注「发布时间未知」并展示采集时间，**不以采集时间冒充发布时间**。

## 安全

- 无密钥、无第三方账号，前端无敏感信息（`.env` 被 `.dockerignore` 排除，不进镜像层）。
- 外部内容（标题/摘要/来源）一律以 `textContent` 渲染，**全站不出现 `innerHTML` / `outerHTML` / `insertAdjacentHTML` / `document.write`**，防 XSS。
- 外链均带 `rel="noopener noreferrer"`。
- 前端**不引用任何外部 CDN**（D3 本地打包），离线/内网环境可用。

> 以上四条不是口号，而是 `tests/test_frontend_safety.py` 里逐条断言的不变量 —— 文档里的承诺没有测试兜着，过两周就会变成假话。

## 验证记录

| 场景 | 方法 | 结果 |
|---|---|---|
| 真实数据获取 | `python fetch.py` | ✅ 4 源成功；修复 HN 查询后重采，入库 99 条且当日数据新鲜 |
| 重复导入幂等 | 连续运行两次 | ✅ 第二次全部 `inserted=0` |
| 单源失败容错 | `python fetch.py --fail-source techcrunch` | ✅ 该源标记 `failed`，其他源正常，旧数据保留 |
| 定时自动更新 | 外部定时器 → `workflow_dispatch` | ✅ **已通过**（详见「案例六」）：cron-job.org 每 3 小时调用 GitHub API 派发 `workflow_dispatch`，北京 12:20 真实触发 run #14 success，线上 `data.json` 的 `generated_at` 即时刷新到 12:20:36；新闻总数 317 → 331，`hackernews` 抓取 40 条新增 2 条（其余来源 `no_new`，与「抓取失败」正确区分）。同时 GitHub 原生 `schedule` 事件在 14 次运行中**始终为 0**——配置无错，问题在调度层，详「案例四」。 |
| 并发 push 竞态 | 查看失败运行 34927770343 的步骤日志 | ✅ 已定位并修复：采集成功但「提交更新结果」被拒（non-fast-forward），导致整次运行失败。已改为「每次尝试先回到远端最新 → 重新采集 → 推送」，最多重试 3 次，见「案例五」 |
| 遗忘机制与图谱性能 | 对照基准（旧版 vs 新版，agent-browser 实测，927 条真实数据） | ✅ 图谱 SVG 元素 12534 → 1562，「近 7 天」重绘阻塞 25.7ms → 10.9ms，资讯流↔图谱连续切换 121.8ms → 24.8ms，FPS 51 → 62，data.json 801KB → 472KB；遗忘提示、关键词聚焦、悬停详情人工验证通过。复测中发现并修复本地库与云端库分叉问题（详「案例七」） |
| Docker 一键启动 | `docker compose up --build` 后实测 | ✅ 构建成功（torch 2.14.0+cpu，嵌入模型构建期落盘）；`/health` 返回 `news_count=1384`、`/docs` HTTP 200、`/news` 正常返回；`--network none` 下容器内检索仍可用（3 条），证明模型不依赖运行时联网；挂载空目录启动时自动建表（`news_count=0` 仍健康）。镜像 2.36GB（torch 769MB + scipy 109MB + 模型 93MB），非 root 运行 |
| 单测与覆盖率 | `pytest tests/ --cov=. --cov-fail-under=50` | ✅ **146 passed / 2 skipped，覆盖率 58.11%**（含 db、llm、middleware、insight、analyze、agent 图结构、MCP 工具清单）。测试全部离线可跑：LLM 与网络用假对象替代，API 用例跑在临时库 |
| Lint | `ruff check .` | ✅ All checks passed（`ruff.toml` 逐条写明忽略理由） |
| 评测回归门禁 | `python evals/run_all.py --gate-config evals/baseline.json` | ✅ 门禁通过；合成回归场景实测可拦截（跌破下限 / 较基线下滑超容差 / 评测脚本跑不通三类均拦住） |
| 成本可观测性 | 容器内实测 `/api/stats` + 真实 `/ask` 调用 | ✅ 367→368 次调用、¥0.7396→¥0.7410 实时累加；按用途拆分（analyze 365 / ask 3）、`?days=1` 时间窗生效；页脚静态看板实测渲染；真实调用 11 in / 28 out tokens → ¥0.000131（非峰值半价，与手算一致） |
| 前端安全不变量 | `pytest tests/test_frontend_safety.py` | ✅ 7 条断言：全站零 `innerHTML`/`outerHTML`/`insertAdjacentHTML`/`document.write`、零外部 CDN 引用、D3 本地打包完整、外链 `_blank` 必带 `noopener noreferrer`（修正了 ask.js 缺 `noreferrer` 的真实缺陷） |
| 文档与代码一致性 | 三份文档（README / ARCHITECTURE / EVALS）逐条交叉核对 | ✅ 核对并修正 6 处不符：HN 查询串描述、测试数与覆盖率（106→146、53.6%→58.11%）、Docker 端点清单、手动命令的跨平台写法、「不使用 innerHTML」与「外链均带 noreferrer」两条不成立的安全声明（已改代码并加测试）；另修正 `/ask` 提示词版本与成本量纲（详见 Week 4 章节） |

（缺失日期、长标题、搜索无结果等界面状态已在前端实现并人工检查。）

## 数据治理（遗忘机制）

资讯是流式数据，只增不减会让列表和关系图谱逐渐不可用。本站用四层不同粒度的遗忘控制数据规模（参数集中在 `fetch.py` 顶部，随 `meta.window` 导出，页面页脚据此展示）：

| 层 | 参数 | 作用 |
|---|---|---|
| 采集配额 | `DAILY_INGEST_LIMIT = 120` | 每天最多入库 120 条（跨源合计，按北京时间自然日），从源头控制增速 |
| 记忆强度 | `GRAPH_WINDOW_DAYS = 7` + 半衰期 30 小时 | 图谱只画近 7 天内「记忆强度」最高的 240 条新闻 + 100 个关键词；强度 = 时间衰减 × 关联度，旧资讯逐渐淡出图谱 |
| 列表窗口 | `EXPORT_WINDOW_DAYS = 30` | 资讯流保留最近 30 天（被图谱遗忘的内容仍可阅读） |
| 库内归档 | `DB_RETENTION_DAYS = 90` | 数据库超过 90 天的记录删除回收空间 |

被遗忘的条目数随每次导出写入 `meta.window`，图谱视图顶部会如实提示「本轮按记忆强度遗忘了 N 条」，前端筛选命中超预算节点时同样按强度截断并提示。

## 已知限制

- 关键词提取为规则 + 实体词典（未调 LLM，零成本），偶有噪声词；词典在 `fetch.py` 的 `ENTITY_LEXICON` 可扩充。
- 图谱按「新闻-关键词」建边，不做跨媒体同一事件的语义聚合（题目注明非必做）。
- 资讯流展示最近 30 天 / 1500 条（数据库保留 90 天历史，图谱另有 7 天记忆窗口）。
- **检索 Recall@5 ≈ 0.26，低于自定熔断线 0.65**（原因与调优方向见 `evals/report_week2.md`）。该指标当前只做回归拦截、不做绝对值拦截，且每次跑门禁都会打印公示，避免被遗忘。
- **分类评测尚无人工标注集**（`evals/dataset.jsonl` 的 `expected_category` 全为空），对应门禁项缺失，门禁会明确报 WARN 而不是静默通过。
- **未纳入 black 强制检查**：既有代码是手写风格（刻意对齐的行尾注释），black 全量重排会产生 900+ 行纯格式 diff，把真实改动淹没。CI 只跑 ruff（规则见 `ruff.toml`，逐条写明了忽略理由）；本地想统一风格可自行 `black .`。

## 成本

开发与运行均未使用付费服务：信息源为公开 RSS/API，托管用 GitHub Pages 免额度，调度用 cron-job.org 免费版（自定义 header、POST + body 全部支持），未调用付费大模型。

## 开发说明

- 实际投入时间：约 5.75 小时（提交时如实填写）
- 主要工具：AI 编程助手（CodeBuddy）协作开发；D3.js（图谱可视化）；feedparser（RSS 解析）
- 关键决策：① 静态 `data.json` + 原生前端而非全栈服务——可复现性与零运行成本优先；② 关键词图谱选「规则提取」而非 LLM 摘要——符合成本约束且结果可解释。

### 问题定位与返工记录

**案例一：Hacker News 数据陈旧（数据新鲜度未校验）**

- 现象：筛选「Hacker News + 今天」无结果；抽查数据库发现 HN 最新条目停在 3 个月前。
- 定位：直接请求 HN Algolia API 对比，发现采集 URL 中的查询串 `query=AI OR "artificial intelligence" OR LLM` 被 API 错误解析（带引号短语破坏了 OR 语义），仅匹配 24 条历史帖子；`search_by_date` 看似成功返回，脚本未校验内容新鲜度。
- 修复：简化为 `query=AI&tags=story`（HN 标题自带 AI 语境），清除陈旧数据重采；同时保留教训——**采集成功 ≠ 数据正确，日期新鲜度应纳入验证**。
- 验证：重采后 HN 40 条均为当日新帖；页面「今天」视图恢复多来源内容。

**案例二：关系图谱关键词噪声**

- 现象：图谱中出现 `Abstract`、`across`、`Type` 等无意义节点。
- 定位：高频词统计把 arXiv 摘要的模板文本和正文常用词算了进来。
- 修复：高频词只从标题统计 + 扩充停用词表 + 实体词典复数归一；导出时再次清洗 arXiv 模板前缀（正则需 `re.S` 跨行匹配）。

**案例三：页脚与卡片重叠（布局）**

- 现象：页面底部状态栏与新闻卡片渲染重叠。
- 定位：`html, body { height: 100% }` 把 body 锁死在视口高，flex 布局下 main 被压缩、内容溢出但仍可见，页脚却停在视口内。
- 修复：改为 `min-height: 100vh`；同时补 `[hidden] { display: none !important }` 修复 flex 容器覆盖 hidden 属性的问题。

**案例四：定时任务配置正确却从未被执行（清理「配置 ≠ 运行」）**

- 现象：Actions 页面 7 条运行记录全部由 `push` 或手动触发，**没有一条是 Schedule 事件**；线上数据长时间停留在最近一次手动运行的结果。
- 定位（逐项排除，而非猜测）：
  1. 查 GitHub API `GET /repos/.../actions/runs?event=schedule` → `total_count = 0`，确认定时事件确实一次都没触发；
  2. 用 YAML 解析器解析**线上实际文件**，`on.schedule` 解析结果为 `[{"cron": "17 0 * * *"}]`，语法合法 → 排除 YAML 错误；
  3. 查 `GET /repos/.../actions/workflows` → `state: "active"`，未被停用 → 排除「60 天无活动自动禁用」；
  4. 仓库每日均有提交，排除活跃度问题；cron 五字段表达式合法。
- 根因判断：配置本身无误，问题出在**调度层**。两轮修复均未奏效：第一版 cron 设在 UTC 00:17（紧邻整点），第二版改到 UTC 02:20 / 14:20（避峰 + 双时段），**北京时间 2026-09-16 10:20 的触发点仍未出现**（API 复核 `event=schedule` 依旧为 0，运行总数停留在 9）。GitHub 官方文档说明「每小时开始前后为高负载时段，定时任务可能被延迟，极端情况下被跳过」，且 schedule 变更后存在生效延迟——但连续多个触发点全部落空，已不能仅用「高负载延迟」解释。
- 修复：① 规范化 `on` 块缩进（原文件由网页编辑器产生，`- cron` 与父键缩进不一致，虽可解析但不利于人工维护）；② cron 改为 `20 */3 * * *`——每 3 小时一次、每天 8 次，把触发机会从 2 次提到 8 次，同时保留「避开整点」的原则；③ 保留 `workflow_dispatch` 手动入口作为随时可用的人工触发通道。
- 决策：连续 4 个触发点（UTC 09-15 00:17 / 09-16 00:17 / 02:20 / 03:20）落空后，**改用外部定时器方案**——cron-job.org 调用 GitHub 官方 `workflow_dispatch` REST API 触发工作流（GitHub 自身的 `schedule` 事件保留作为白送的兜底，重复执行由工作流的 `concurrency` 配置消解）。这避免了「配置正确但调度器不派发」时只能等待的问题，也满足题目「不依赖个人电脑、可自行定时运行」的验收要求。
- 教训：**「配置已提交」不等于「任务已运行」**。定时任务的验收标准是**运行记录中确实存在由定时源触发的事件**，而不是配置文件里是否存在 `cron` 字段——这正是题目「配置与运行分开」原则在调度器层的延伸。平台侧的不确定性（调度器偶发不派发）应在设计时就用「外部触发 + 失败告警」兜底，而不是赌平台一定正常。
- 落地与端到端验证见「案例六」。

**案例五：并发 push 竞态导致整次运行失败**

- 现象：运行 `34927770343`（2026-09-15 04:10 UTC）结论为 failure，页面部署被跳过。
- 定位（查 API 到步骤级）：第 5 步「采集并导出数据」成功 → 第 6 步「提交更新结果」**失败** → 第 7 步「上传静态站点」skipped → `deploy` job skipped。失败原因是 `git-auto-commit-action` 推送被拒：`! [rejected] main -> main (non-fast-forward)`。
- 根因：工作流 checkout 之后、push 之前，远端 `main` 被别的提交更新（当时正在通过网页修改 cron），工作流本地分支落后于远端，普通 `push` 被拒，导致**采集到的数据没写进仓库、站点也没重新部署**。`concurrency` 只能取消同组内正在跑的运行，挡不住来自网页编辑、手动 push 等其它来源的并发提交。
- 修复：把「采集 / 提交 / 推送」合并为一步并加并发重试——每次尝试都先 `git fetch` + `git reset --hard origin/main` 回到远端最新，再重新执行 `fetch.py`（采集本身幂等，重跑无副作用），然后提交推送；最多重试 3 次，仍失败则显式报错退出，**不静默丢弃数据**。
- 教训：无人值守的定时任务里，「先落盘再推送」的写法必须考虑远端已变化的可能；与其在冲突后用 `--force` 覆盖（可能冲掉别人的提交），不如基于最新远端状态**重新生成**结果再提交。

**案例六：外部定时器接管调度（方案 A 落地与端到端验证）**

承接案例四的结论——GitHub 原生 `schedule` 事件对该仓库长期不派发，单纯调 cron 表达式不能解决问题。改为「外部定时器调用 GitHub 官方 `workflow_dispatch` REST API」方案。

**选型：cron-job.org**
- 免费、可设自定义 header、POST + body、零成本即可托管任意 HTTP 触发
- 时区可设、cron `*/3` 类表达式直接写
- 唯一隐患：连续失败 25 次会自动停用该 job → 失败邮件通知必须开

**配置核心（4 项即可）**
1. URL：`https://api.github.com/repos/chuanyu-fangyuan/-aii-/actions/workflows/<workflow_id>/dispatches`
2. Request method：POST
3. Request body：`{"ref":"main"}`
4. Headers：
   - `Authorization: Bearer <细粒度PAT>` —— PAT 范围限定为仅本仓库、仅 `Actions: Read and write`
   - `Accept: application/vnd.github+json`
   - `X-GitHub-Api-Version: 2022-11-28`
   - `Content-Type: application/json`

Crontab：`20 */3 * * *`，时区 `Asia/Shanghai` → 北京 02:20 / 05:20 / 08:20 / 11:20 / 14:20 / 17:20 / 20:20 / 23:20。仓库代码**无须改动**，`workflow_dispatch` 入口早就存在。

**端到端验证（2026-09-16 北京 12:20，三段独立取证，非单一截图）**

| 环节 | 实测证据 | 结果 |
|---|---|---|
| cron-job.org 派发 | HISTORY：12:20:20 执行，耗时 26 ms，网络 2.96 s | ✅ HTTP 204 |
| GitHub Actions 执行 | run #14，`created_at=04:20:22Z`，事件 `workflow_dispatch`，`conclusion=success` | ✅ |
| 线上站点刷新 | Pages `data.json` 的 `generated_at = 2026-09-16T04:20:36Z`（=北京 12:20:36） | ✅ |

**额外佐证——这次不是空跑：** 新闻总数 317 → 331（+14）；来源明细中 `hackernews` 状态 `ok`、抓取 40 条 / 新增 2 条；其余来源 `no_new`，与「抓取失败」正确区分；图谱 598 节点 / 1071 边重建。

GitHub UI 把 `workflow_dispatch` 显示成「手动运行」是它的分类方式，实际由 cron-job.org 自动调用——**满足「每天自动更新、不依赖个人电脑」的验收要求**。

**剩余风险与对策**
- **PAT 到期静默断更**（cron-job.org 连续失败 25 次自动停 job，且不会主动提醒你 PAT 过期）→ 必开 cron-job.org 失败邮件通知；建议每年手动 rotate 一次（GitHub 细粒度 PAT 最长 1 年）。
- **cron-job.org 自身故障** → 工作流保留 GitHub 原生 `schedule` 作白送的兜底（即使从不派发也不影响主路径，触发重复时由 `concurrency: pages / cancel-in-progress` 消解）。
- **单点调度服务** → 把同一 URL 也配到第二个外部服务（UptimeRobot HTTP 监控 POST、EasyCron 等）即作备援，无须改代码。

**教训：** 触发器应与应用逻辑解耦——「谁在何时来敲门」是平台侧的事，「门被敲开之后做什么」才是自己的事。后者稳定运行后，前者可以无痛替换（GitHub schedule → cron-job.org → 任何外部调度服务）。这种解耦是「配置与运行分开」原则在调度器层的延伸：触发源可换，但工作流定义、数据契约、产物结构都不必跟着改。

**案例七：关系图谱卡顿（数据规模只增不减）+ 复盘中发现数据库分叉**

- 现象：资讯库涨到 927 条后，图谱在「近 7 天 / 全部」视图下 SVG 元素超过 12500 个，「近 7 天」重绘阻塞 26ms、连续资讯流↔图谱切换累计阻塞 122ms，帧率跌破 51fps，低端设备明显卡顿。
- 定位（先量化，再动手）：
  - **规模**：旧图谱按纯时间窗口从库内取数，节点数随库容量线性增长——917 条数据时图谱已到 1676 节点 / 4277 边，data.json 801KB；数据库只增不减，卡顿只会越来越重。
  - **前端**：`app.js` 启动时用嵌套 `nodes.find` 构建 news→keyword 映射（O(n×m)）；`graph.js` 每次重绘全量重建 SVG、实例泄漏（切视图未 `simulation.stop()`）、无坐标复用。
- 决策（三层遗忘 + 前端重构）：
  - **采集配额**：每日入库上限 120 条（按北京时间自然日），控制增速源头。
  - **记忆强度**：图谱不再按纯时间取数，改为 `强度 = 时间衰减（半衰期 30h）× 关联度` 排序，7 天窗口内只保留最强的 240 条新闻 + 100 个关键词，与库容量彻底解耦；被遗忘条目数写入 `meta.window`，页脚与图谱提示如实展示「本轮按记忆强度遗忘了 N 条」。
  - **列表/归档分层**：资讯流保留 30 天（被图谱遗忘的仍可读），库内 90 天归档 + VACUUM 回收空间。
  - 前端同步重构：Map 替代嵌套 find、坐标缓存跨重绘复用、网格初始化 + 收敛后自适应取景、悬停节流、筛选命中超预算节点时按强度截断并提示。
- 实测（agent-browser 对照基准，927 条真实数据）：

| 指标 | 旧版 | 新版 |
|---|---|---|
| 图谱 SVG 元素（近 7 天） | 12534 | **1562** |
| 「近 7 天」重绘阻塞 | 25.7ms | **10.9ms** |
| 资讯流↔图谱连续切换 ×3 | 121.8ms | **24.8ms** |
| FPS | 50.8–59.2 | **60.8–62.5** |
| data.json 体积 | 801KB | **472KB** |

- **复盘时又揪出一个更隐蔽的问题——本地库与云端库分叉**：复测时发现导出后站点资讯从 927 条「变」成 334 条。追查发现本地 `news.db` 是 09-16 之后的旧分叉（最大 id 1529、停更两天），而仓库里那份是云端 Actions 持续累积的（最大 id 4949）；本地误用旧库导出，把云端两天的新增悄悄丢掉。**数据变少不报任何错**，是靠新旧对照的数字对不上才发现的。修复：从仓库恢复云端库重新导出；并在 `fetch.py` 增加 `warn_if_stale` 新鲜度防线——导出前检查 `update_runs` 最后运行时间，落后超 24 小时即显式警告「本库可能落后于云端流水线」（已模拟事故现场验证：旧库触发警告、新库静默）。
- 教训：① 性能问题先测基线再改，修复效果用同一把尺子量（对照基准贯穿始终）；② 「数据规模失控」要在**源头**（配额）和**展示层**（记忆强度）同时设防，只优化前端渲染只是推迟爆炸；③ 数据管线最大的风险不是报错，而是**静默退化**——「条数变少」「日期变旧」这类不抛异常的回归，必须靠显式校验（新鲜度检查、数量对照）兜住，这与案例一的教训一脉相承。

### 验证记录补充（界面层）

- 搜索无结果 → 空态提示 + 一键清除条件（截图留存）
- 「今天 + 某来源」为空 → 明确提示时区差异、不代表抓取失败，并提供「查看该来源近 7 天」
- 缺发布时间 → 注入明确标注 `[测试]` 的记录验证「发布时间未知 · 采集于…」警示样式，验证后删除，未混入真实数据
- 长标题（122 字符）→ 两行截断正常
- 移动端 390px 视口 → 资讯流 / 图谱 / 抽屉均可用（截图留存）


---

## Week 3：Agent 与评测（2026-09-22）

本周把「流水线」升级为「能自主决策的 Agent」，并完成 RAG 评测 v2。

### 新增能力

| 模块 | 说明 |
|---|---|
| `agent/tools.py` | 5 个 LangChain 工具：search_news / fetch_source / dedup_check / verify_claim / write_report，全部复用已有模块，不重写 |
| `agent/graph.py` | LangGraph 状态图：plan → gather → verify → synthesize → review → publish；条件边 verify 可疑→回 gather 补证（最多 2 轮防死循环）；状态持久化到 `agent_runs` 表 |
| HITL 审核流 | 重要结论进 `pending_review` 表，`POST /review/{id}`（approve/reject + 理由），未审核内容不进线上，前端 `web/review.html` 审核页 |
| MCP Server | `mcp_server/server.py` 用 FastMCP 4 暴露 5 个工具，可被 Claude Desktop / Cursor 调用 |
| 评测 v2 | `evals/eval_rag.py`：RAGAS 口径三指标 + LLM-as-judge + 20 组问答对（含 2 道「资料不足」陷阱题）+ Prompt v1/v2 对比，报告见 `evals/report_week3.md` |

### Week 3 验收记录（2026-09-22，三链路一次跑通）

`tests/verify_week3.py` 单次运行依次执行三条链路（结果存 `data/week3_acceptance.json`）：

| 链路 | 内容 | 结果 | 耗时 |
|---|---|---|---|
| A 分类/分析 | `analyze.py --limit 3` 真实分类 + 摘要 | ✅ | 4.7s |
| B RAG 问答 | `/ask` 端点（TestClient 直调）带引用回答 | ✅ 引用 1 条 | 23.6s |
| C Agent | `run_agent` 完整情报任务，产出 1389 字报告 | ✅ | 18.0s |

其余验证：`pytest tests/test_tools.py` 8 passed；`tests/verify_mcp.py` 5 个工具全部列出并可调用（含 LLM 类工具）；RAGAS 三指标 v1/v2 对比有明确结论（差异在噪声内，v2 忠实度 1.00 略优，详见 report_week3.md）。

### 失败模式与复盘（本周新增三条，均为真实事故）

**案例八：ragas 与 Agent 生态依赖冲突（「评测库 vs 运行时」不可兼得）**

- 现象：安装 ragas 后 `import ragas` 直接失败——0.2.15/0.4.3 均硬依赖 `langchain_community.chat_models.vertexai`，而 langchain-community 0.4.x（Agent 所需 langchain 1.x 生态）已移除该模块。
- 弯路：先尝试把整套 langchain 降级到 0.3.x 旧栈迁就 ragas，结果 ① 与 Agent 新栈代码冲突；② Windows 下 pip 的 safe-delete 机制在本机不可用（回收站不可达），任何「替换已存在文件」的安装都会 OSError 失败，留下 `~anggraph`、`~agas` 等残缺目录；③ 排查时误删了 `langgraph/cache` 目录——它不是垃圾，而是 langgraph-checkpoint 4.2.0 的正式模块，导致 Agent 状态图无法导入。
- 修复：放弃降级，从官方 wheel 直接解包恢复缺失模块（`langgraph/cache` 由 langgraph-checkpoint 提供，4 个文件即修复），Agent 完整回归通过；评测改用「按 RAGAS 论文口径自实现」方案（`evals/eval_rag.py`），方法论与局限在 report_week3.md 如实披露。
- 教训：① **评测工具不能绑架运行时**——两者共享一个 venv 时，任何一方的依赖地狱都会烧到另一方；正确做法是隔离（独立 venv）或自实现轻量口径，而不是牺牲生产环境去迁就工具；② Windows + 受限回收站环境下，pip「替换式安装」不可靠，修复破损包用「从 wheel 定向解包缺失文件」最小侵入，不搞删除重装；③ **删除任何 site-packages 里的目录前，先查它属于哪个发行版**（`grep <路径> */RECORD`），「看起来像残留」的目录可能是真实模块。

**案例九：Prompt v1/v2 对比的天花板效应（如何解读「没差别」）**

- 现象：精心设计的 v2 Prompt（强制逐句引用、结论先行、不足先声明）与 v1 相比三项指标差异全部 ≤ 0.03，几乎持平。
- 定位：语料仅 900 余条、检索 context_precision 已达 0.9+，答案本质是「抄写+归纳」，两种 Prompt 都贴着天花板；评测规模 20 题也不足以分辨 0.03 的差异。
- 决策：仍切换 v2 上线——20 题 0 编造（v1 有 1 条无支持断言），陷阱题行为更稳定，情报站「不编造 > 多说 2%」；语料扩大后复测。
- 教训：对比实验出现「没差别」时，先判断是**真的没差别**还是**天花板/样本量**问题，结论要写成可复检的形式（差异、题数、哪个场景下会变）。

**案例十：评测裁判与生成模型同源的自我偏好风险**

- 现象：用 DeepSeek 既当生成模型又当裁判，faithfulness 出现 1.00 的满分——需要警惕「自己评自己偏乐观」。
- 缓解：① 三指标中 context_precision 可独立复核（检索片段的相关性人工抽查即可验证）；② 陷阱题（#19/#20）的「声明不足而非编造」行为可人工直接读答案验证，已验证通过；③ report_week3.md 中把「裁判=生成模型」列为已知局限。
- 教训：LLM-as-judge 的分数不是终点，要设计**至少一个不依赖裁判的独立检查点**（陷阱题、人工抽查、可计算指标）。

**案例十一：门禁设计反噬——「统一阈值」把部署永久卡死**

- 现象：Week 4 加了评测回归门禁（`--baseline 0.75`）并让 `deploy` 依赖它。上线前体检发现，只要推送就会永久阻断部署。
- 定位：把真实评测输出喂给门禁函数复现，`[FAIL] eval_retrieval.py: recall@k=0.2600 < baseline=0.75`。检索长期在 0.26（Week 2 报告已记录其低于 0.65 熔断线）、RAG faithfulness 是 1.00，把两者塞进同一个 0.75 下限，等于要求「本来就未达标的指标立刻达标」；同时分类评测因标注集为空提前返回、不产出指标，旧实现把「没指标」当成通过——同一套门禁既会误杀又会漏放。
- 修复：改为逐指标声明（snapshot / tolerance / floor / target），未达标项只公示不拦截、回归则硬拦；「没指标」改为 WARN 而非静默通过。另外做了成本分流：push 触发跑完整评测，定时数据更新跳过 LLM 评测（否则每 3 小时烧 80 次调用）。
- 教训：**门禁的职责是防退化，不是催达标**。把「目标值」当「下限」用，会把一条本来能拦住真问题的防线变成每天都在误报的噪声源——真出现退化时反而没人看了。同时，任何「没数据就跳过」的判定都要显式报出来，静默通过的门禁等于没有门禁。

**案例十二：Agent 的「闭环」是假的——图上连了边，数据没接上（Agent 失败模式）**

- 现象：状态图里 `verify → gather` 有一条补证回边，`verify_count < 2` 时才走综合，看起来「验证不过就补数据」的闭环成立。做 lint 清理时发现 `synthesize_node` 里两个变量 `gathered` / `verification` 被读出来却从未使用。
- 定位：`synthesize_node` 的报告由 `write_report` 工具生成，而该工具**自己按主题重新检索**库内新闻再让 LLM 写 —— 于是 Agent 前面辛苦收集的数据、以及验证节点的结论，对最终报告**没有任何影响**。回边只是让流程多跑一轮、多花钱，却没有把新证据带进报告。
- 修复：先如实标注（`synthesize_node` 与 `publish_node` 的注释写清「报告不消费 gathered/verification」），并把死变量清掉；要真正闭环，应把证据显式拼进 `write_report` 的入参 —— 这属于行为变更，需配套评测确认收益，故留作已知项（`ARCHITECTURE.md` 的失败模式表里列为「报告与证据脱节」）。
- 教训：**判断一个循环是否有效，看数据流而不是看箭头**。lint 报的「变量赋值未使用」往往不是洁癖问题，而是「这条线断了」的信号 —— 死变量就是断线的显影剂。

**案例十三：Agent 运行记录永远缺「结束时间」（Agent 失败模式）**

- 现象：`agent_runs` 表有 `completed_at` 列，但查库发现所有行都是 NULL，无法统计任何一次运行的耗时。
- 定位：`save_run()` 有两条分支 —— 更新已有 run 时写了 `completed_at = CASE WHEN status='published' THEN datetime('now')`，而**新建 run 的 INSERT 分支完全没写这一列**。恰好 Agent 的正常路径（一次跑完就落库）走的是 INSERT，于是这列永远是空。
- 修复：INSERT 分支补上同样的 CASE 表达式；用单测锁住「published 状态必须写入完成时间」。
- 教训：同一个字段在两条分支上必须同时维护 —— 只在「更新」路径写、忘了「新建」路径，是典型的**分支不对称缺陷**，而且它不会报错，只会在你哪天想看统计时发现数据是空的。


### 成本核算（全项目，截至 Week 3）


| 项 | 用量 | 估算成本 |
|---|---|---|
| 分类/分析链路（365 次，`llm_traces` 实测） | 输入 178,861 tok / 输出 45,967 tok | ≈ ¥0.74 |
| RAG 问答与评测（`/ask` 实测 + 评测明细） | 约 130 次调用 | ≈ ¥0.4 |
| Agent 运行 + HITL/MCP 开发测试 | 约 10 余次完整运行 | ≈ ¥0.3 |
| **有 trace 可查的小计** | 约 500 次调用 | **≈ ¥1.4** |
| 收口前未埋点的评测/Agent 调用 | 控制台单日 ¥0.39 中有 87% 属于此类 | 约 ¥1–1.5 |
| **LLM 总成本（估算）** | — | **≈ ¥2.5–3** |

托管（GitHub Pages + Actions）与调度（cron-job.org）维持 0 成本。整个项目自始至终未使用付费服务（唯一付费依赖是 DeepSeek 的按量调用）。

> 说明：最初表格写「≈ ¥3」是早期按调用次数粗估；Day 25 接入逐次计量后发现计价量纲错了 1000 倍（少算），修正后有 trace 的部分为 ¥1.4。差额来自收口之前**没有埋点**的评测/Agent 调用 —— 这不是估算，而是与控制台账单对账后的结论，对账过程见「首次对账结果」。

## Week 4：质量门禁与工程化

### 评测结果摘要

| 评测 | 数据集 | 关键指标 | 当前值 | 达标线 | 状态 |
|---|---|---|---|---|---|
| 检索 | 10 条 query | Recall@5 / MRR / NDCG@5 | 0.26 / 0.39 / 0.24 | 0.65 | ❌ 未达标（已公示，调优方向见 EVALS.md） |
| 分类 | 30 条（**0 条已标注**） | macro-F1 | — | 0.70 | ⚠️ 未启用（缺人工标注） |
| RAG 问答 | 20 题 | faithfulness / answer_relevancy / context_precision / rubric | 1.00 / 0.98 / 0.96 / 4.9 | 0.75 / — / — / 3.5 | ✅ 达标 |
| Embedding 一致性 | 库内随机样本 | cos_sim | 1.000000 | > 0.99 | ✅ |

口径、局限（裁判与生成模型同源、样本量小）与门禁规则详见 **[EVALS.md](EVALS.md)**。

### 门禁组成

三部分都在 `.github/workflows/update.yml` 的 `evals` 作业里，且 `deploy` 依赖它：

| 关卡 | 命令 | 阈值 |
|---|---|---|
| 单元测试 | `pytest tests/ --cov=. --cov-fail-under=50` | 覆盖率 ≥ 50%（实测 58.11%，146 条用例） |
| Lint | `ruff check .` | 0 error（规则见 `ruff.toml`） |
| 评测回归 | `python evals/run_all.py --gate-config evals/baseline.json` | 见下 |


### 门禁为什么要从「一个数字」改成逐指标规则

最初实现是 `--baseline 0.75`：给所有评测的所有同名指标套同一个下限。实测直接判死——检索的 `recall@k` 长期在 0.26，RAG 的 `faithfulness` 是 1.00，两者量纲、口径、可达性完全不同；统一阈值的结果是**每次运行都失败、`deploy` 被 `needs: evals` 永久卡住**，门禁反而失去意义。

现在改为 `evals/baseline.json` 逐指标声明：`snapshot`（记录时水平）+ `tolerance`（允许抖动）+ `floor`（达标硬下限，仅对已确认可达标的指标启用）+ `target`（未达标目标，只公示不拦截）。实测拦截能力（合成数据验证）：

```
拦截 | faithfulness 跌破达标线 0.75      | faithfulness=0.7 < 下限 0.75
拦截 | 检索 recall 下滑到 0.10           | recall@k=0.1 较基线 0.26 下滑超过 0.06
拦截 | 评测脚本跑不通                    | eval_rag.py: 评测未跑通
放行 | 一切正常                          |
```

另一处修正是：**「没指标」不再等于「通过」**。分类评测在标注集为空时会提前返回、不产出指标，旧实现会静默放行，等于该项门禁形同虚设；现在会打印 WARN 并在报告里留痕。

### 评测成本控制

RAG 评测每轮要跑 80 次 LLM 调用（约 ¥0.5–1），而工作流每 3 小时被 cron 触发一次——若每轮都跑满，一天 ¥4–8、一个月上百元，与「低成本」目标冲突。因此按触发来源分流：**push（代码变更）跑完整评测，定时数据更新只跑零成本的检索/分类评测**，两条路径共用同一份门禁规则。

### 单测不做的事

不新增会花钱或依赖外网的用例：LLM 调用、网络请求一律用假对象顶替（`tests/test_analyze.py` 用假的 `urlopen` 覆盖成功/HTTP 错误/非 JSON/超时四条路径）。API 测试全部跑在临时库上——早期版本直接对着 `data/news.db` 跑，`test_submit_review` 真往 `pending_review` 插了一行「测试」，脏数据进了仓库还会显示在线上审核页；现在临时库 + 夹具隔离，并加断言防止回退。

## 可观测性与成本看板（Day 25）

### 一个入口管住所有 LLM 调用

收口前，仓库里有 **5 处各自 `requests.post` 到 DeepSeek 的代码**（分类、问答、洞察、Agent 的两个工具），而只有分类链路会写 `llm_traces`。结果是成本看板只能看到一条链路，问答与 Agent 的消耗全是黑洞；每处还各写一套重试/超时/错误分类，口径不一致。

现在统一到 `llm.py`：

| 关注点 | 做法 |
|---|---|
| 调用 | `llm.chat(messages, purpose=...)` —— 请求、超时、JSON 模式、错误分类一处实现 |
| 埋点 | 每次调用（**含失败**）都写 `llm_traces`：model / tokens / latency / cost / status / news_id |
| 用途维度 | `purpose ∈ {analyze, ask, insight, agent_verify, agent_report, eval, agent}`，看板据此区分钱花在哪条链路 |
| LangChain | Agent 走 langchain 自己的客户端，用 `llm.langchain_callbacks()` 回调把 token 用量落库 |
| 计量 | 按官方价目表分三档计价：输入缓存命中 / 未命中 / 输出，并自动区分**峰谷时段**（峰值是非峰值的 2 倍） |

### 成本看板

- **接口**：`GET /api/stats[?days=N]` —— 累计与按用途、按日分布、错误调用数、均次成本；`days=0` 为全量。
- **静态站**：线上是纯静态部署（Pages 上没有 API 可调），因此 `fetch.py` 在导出时同时生成 `web/stats.json`，页脚直接展示「累计 N 次调用 / X tokens / 约 ¥Y」。

```
成本透明：累计 368 次模型调用 / 224,952 tokens / 约 ¥0.7410（估算）；analyze 365 次 · ask 3 次。
按 DeepSeek 官方价目表估算（含峰谷与缓存价），实际以账户账单为准
```

### 修掉的两个真问题

1. **计价量纲错 1000 倍**：常量注释写「元/千 token」，计算却除以 1,000,000。365 次分类调用的累计费用被记成 **¥0.0003**，与账单差几个数量级。改为按官方价目表（USD/百万 token）+ 汇率折算 + 峰谷/缓存分档后，同一批数据重算为 **¥0.7394**（`python llm.py --recost` 可重算历史行）。
2. **线上跑的提示词不是评测的那份**：Week 3 的结论是「线上切 v2」，但 `/ask` 仍指向 `prompts/rag_v1.txt`，而门禁评的是 v2 —— 报告的「评测口径与生产一致」当时并不成立。现已改指 `rag_v2.txt`，并实测走通（引用 3 条，成本计入 `purpose='ask'`）。

### 对账方式（验收项）

`/api/stats` 的金额是**按官方价目表估算**，不是账单。对账用 `python llm.py --reconcile <账单金额> --days <窗口天数>`，它会打印估算值、账单值、比值与下一步排查方向（账单偏高 → 先查未埋点调用；估算偏高 → 先查峰谷与缓存价）。

项目内可校验的部分已由测试锁定：单位量纲、峰谷 2 倍关系、缓存价差 > 40 倍、百万输入 token 的成本落在 ¥1.5–3。

### 首次对账结果（2026-09-23）

控制台当日：**255 次请求 / 192,841 tokens / ¥0.39**。与本地记录比对：

| 口径 | 调用数 | tokens | 金额 | 隐含单价 |
|---|---|---|---|---|
| 控制台账单 | 255 | 192,841 | ¥0.39 | **¥2.02 / 百万 token** |
| 本地可解释部分 | 32 | 20,003 | ¥0.047 | **¥2.35 / 百万 token** |
| 覆盖率 | **13%** | **10%** | — | — |

两个结论：

1. **单价口径成立**：估算 ¥2.35/百万 vs 账单隐含 ¥2.02/百万，同一量级（差异来自峰谷权重），说明「官方价目表 + 汇率折算」的模型站得住。
2. **金额差的主因是埋点覆盖率，不是价格**：当天本地只能解释 13% 的调用 —— 用户跑的 RAG 评测（40 条结果 = 80 次调用，发生在收口之前）**一次 trace 都没留下**。这正是统一入口要补的洞；收口后评测/问答/Agent/CI 分析全部计入，下一次对账可逐笔对齐。

> 待校准项：官方文档写峰值时段为「UTC 周一至周五 01:00–04:00、06:00–10:00」，但账单隐含单价更接近非峰值。等埋点覆盖率满 100%，再用一整天数据判断；需要改的只有 `db.PEAK_HOURS_UTC` 一处。

