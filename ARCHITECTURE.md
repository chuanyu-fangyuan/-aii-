# 架构说明（ARCHITECTURE）

> 面向「想快速读懂这个项目怎么跑起来」的读者。每个结论都对得上代码，文末列出关键取舍与扩展方式。
> 最后核对时间：2026-09-23（与代码同步）。

## 1. 设计目标与约束

| 目标 | 约束推导出的做法 |
|---|---|
| **零运行成本** | 采集/分析全部跑在 GitHub Actions 的免费额度里；站点是纯静态，托管在 GitHub Pages；不租服务器、不养数据库 |
| **免运维、不依赖本机开机** | 调度交给外部定时器 cron-job.org，它按 cron 调用 Actions 的 `workflow_dispatch` REST 接口（不用 GitHub 原生 `schedule`，原因见 README 案例四） |
| **可复现** | 数据以 SQLite 单文件入库并提交进仓库，`data.json` 由代码从库里导出；任何一台装好 Python 的机器都能从库重放出站点 |
| **成本可审计** | 每次 LLM 调用都写 `llm_traces`（含失败），提供 `/api/stats` 与静态 `web/stats.json`，并有对账命令 |
| **不编造** | RAG 答案强制引用编号；引用校验只认落在检索结果范围内的 `[n]` |

## 2. 系统拓扑

```
                         ┌──────────────── 外部定时器 cron-job.org ────────────────┐
                         │  cron: 20 */3 * * *  →  调 workflow_dispatch REST API  │
                         └───────────────────────────┬─────────────────────────────┘
                                                     ▼
   ┌─────────────────────────── GitHub Actions（免费额度，无常驻服务器）───────────────────────────┐
   │                                                                                            │
   │  job: update ──► fetch.py  ──► data/news.db（SQLite，提交进仓库）──► web/data.json           │
   │        (含并发重试：reset→重跑→push，最多 3 次)                                             │
   │  job: analyze ─► analyze.py（调 DeepSeek 分类/摘要/验证）──► 回写 news.db ──► 重导出         │
   │  job: evals ───► run_all.py 评测回归门禁（覆盖率/lint/指标，见 EVALS.md）                    │
   │  job: deploy ──► 把 web/ 发布到 GitHub Pages（needs: evals）                                 │
   └──────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                              │ 静态文件（data.json / stats.json / 前端资源）
                                              ▼
                              访客浏览器（资讯流 + 关系图谱，纯前端，无后端）

   本机 / 容器 / Fly.io（可选后端：AI 问答与人工审核；线上不部署到 Pages）
   ┌───────────────────────────────────────────────────────────────────┐
   │  FastAPI(api/main.py) ──► retrieval.py（BM25 + 向量 + RRF）        │
   │        │                        │                                 │
   │        │                        └──► sentence-transformers 本地嵌入│
   │        └──► llm.py（统一 LLM 入口 + 埋点）──► DeepSeek API         │
   │  同时提供：/reviews 人工审核（HITL）、/api/stats 成本看板           │
   │  公开配额：api/ratelimit.py（单 IP 5 次/天 + 全局 100 次/天）        │
   └───────────────────────────────────────────────────────────────────┘
   Agent（LangGraph，CLI 调用）与 MCP Server（5 个工具）共享 agent/tools.py 的检索与 LLM 能力
```

**前端怎么找到后端**：`web/config.js`（`fetch.py` 构建期从环境变量 `AI_API_BASE` 生成）→ 线上指向 Fly.io 地址，本地留空则回落 `http://localhost:8000`。

**一句话**：**线上只有静态文件 + 定时任务**；需要 LLM 的三个入口（分析、问答、Agent）都从同一份 SQLite 取数、走同一个 LLM 客户端、记同一张 trace 表。

## 3. 数据流（一次定时更新）

| 步 | 执行者 | 动作 | 失败兜底 |
|---|---|---|---|
| 1 | cron-job.org | 调 Actions `workflow_dispatch` | 一天 8 次互为兜底 |
| 2 | `fetch.py` | 4 源采集（HN Algolia / TechCrunch / The Verge / arXiv RSS） | 单源失败标记 `failed`，不影响其他源；区分「无新增」与「抓取失败」 |
| 3 | `fetch.py` | 规范化 URL 哈希 + 标题哈希双去重，`INSERT OR IGNORE` | 幂等：重复导入不产生重复记录 |
| 4 | `fetch.py` | 四层遗忘：日配额 120 / 记忆强度半衰期 30h / 图谱 7 天窗口 / 库内保留 90 天 | 被遗忘内容仍可在资讯流阅读 |
| 5 | `fetch.py` | 导出 `web/data.json`（meta + news + graph + digest）与 `web/stats.json` | 导出条数上限 1500，防文件膨胀 |
| 6 | `analyze.py` | 取候选（含 HN 低分噪声过滤）→ `llm.py` 调用 → 校验回写 | 重试 3 次带指数退避；`json_parse` 错误 2 次即放弃（换 prompt 无用）；失败写 `ai_errors` |
| 7 | `evals/run_all.py` | 覆盖率 + lint + 指标回归门禁 | 门禁失败则 `deploy` 不执行；定时轮次跳过 LLM 评测省成本 |
| 8 | Actions | 提交 `data/news.db` / `web/*.json` → 发布 Pages | 推送冲突时 reset 后重跑，最多 3 次 |

## 4. 模块地图

| 模块 | 行数 | 职责 | 依赖方向 |
|---|---|---|---|
| `fetch.py` | 785 | 采集、去重、遗忘策略、图谱构建、导出 | → `db.py` |
| `analyze.py` | 385 | 候选筛选、Prompt 组装、LLM 分析、字段校验回写 | → `llm.py`, `db.py` |
| `llm.py` | 472 | **统一 LLM 入口**：请求/超时/JSON 模式/错误分类/计量/埋点、LangChain 回调、成本看板、对账 | → `db.py` |
| `db.py` | 237 | schema 与迁移、连接切换（SQLite / 可选 PG）、**官方价目表与成本模型** | 无 |
| `retrieval.py` | 233 | BM25 + 向量检索 + RRF 融合，`search()` 是唯一入口 | → `db.py` |
| `agent/graph.py` | 421 | LangGraph 状态图（plan/gather/verify/synthesize/review/publish）、运行记录持久化 | → `agent/tools.py`, `llm.py` |
| `agent/tools.py` | 321 | 5 个工具（检索/采集/去重/核查/写报告），可被 Agent 与 MCP 共用 | → `retrieval.py`, `llm.py` |
| `mcp_server/server.py` | 109 | FastMCP 暴露同样的 5 个工具供外部 Agent 调用 | → `agent/tools.py` |
| `api/` | 647 | FastAPI：新闻、问答、审核、统计、触发；鉴权中间件与响应模型分文件 | → `retrieval.py`, `llm.py` |
| `insight.py` | 116 | 每日洞察生成（LLM）并落 `data/insight.json` | → `llm.py` |
| `build_embeddings.py` | 131 | 批量为新闻生成向量（bge-small-zh-v1.5，本地推理） | → `db.py` |
| `web/` | 2117 | 原生 JS + D3：资讯流、筛选、图谱、问答、审核页 | 只读 `*.json` |

依赖是单向的：`web → json → db`、`分析/问答/Agent → llm → db`。`llm.py` 是**唯一**允许直接调外部模型 API 的地方。

## 5. 数据模型（SQLite，7 张表）

| 表 | 作用 | 关键字段 |
|---|---|---|
| `news` | 主表 | `url_hash` UNIQUE（去重）、`title_hash`、`published_at`/`published_unknown`、AI 字段（`ai_category`/`ai_summary_zh`/`importance`/`verification`/`entities_json`/`ai_status`）、`embedding`（BLOB） |
| `update_runs` | 采集审计 | 每源每轮 `status`（`ok`/`no_new`/`failed`）、`fetched`、`inserted`、失败原因 |
| `ai_errors` | 分析失败明细 | `news_id`、`error_type`（api_error/json_parse/timeout/unknown）、`retry_count` |
| `llm_traces` | **成本与调用审计** | `purpose`、`input_tokens`、`output_tokens`、`latency_ms`、`cost_yuan`、`status`、`news_id` |
| `pending_review` | HITL 待审队列 | `news_id`、`review_type`、`original_value`、`suggested_value`、`status` |
| `agent_runs` | Agent 运行快照 | `task`、`plan`、`gathered_data`、`verification_result`、`report`、`verify_count`、`completed_at` |

迁移策略：`init_sqlite()` 幂等（`CREATE TABLE IF NOT EXISTS` + 按缺失列 `ALTER TABLE`），因此**不需要单独的迁移容器/脚本**，老库也能原地升级（有测试覆盖）。

## 6. 检索与问答链路

```
query ─► BM25（中文按单字切分、英文按词，未引入 jieba）─┐
      └► 向量检索（bge-small-zh-v1.5，本地推理）────────┴─► RRF 融合 ─► top-k 上下文 ─► llm.py ─► 答案
                                                                                     │
                                                               引用校验：只认落在检索结果范围内的 [n]
```

- BM25 语料由「标题 + AI 摘要 + 分类」拼成，分词规则见 `retrieval._tokenize`：中文逐字、英文整词。
  逐字切分是当前 Recall@5 偏低的原因之一（见 `EVALS.md` 的调优方向：引入 jieba 做词级切分）。
- 嵌入模型在 Docker 构建期落盘（`HF_HUB_OFFLINE=1`），运行时**不联网**也能检索。
- 提示词版本以 `prompts/rag_v2.txt` 为准（v1/v2 的对比结论见 `EVALS.md`）。

## 7. Agent 与 HITL

**状态图**（实测导出的真实结构）：

```
__start__ → plan → gather → verify ─┬─(status=needs_regather 且 verify_count<2)→ gather
                                    └─(否则)→ synthesize → review ─┬→ publish → __end__
                                                                   └→ synthesize（预留修订环）
```

**失败模式与兜底**（都是踩过或主动设的边界）：

| 失败模式 | 现象 | 兜底设计 |
|---|---|---|
| 无限补证循环 | verify 反复要求补数据，token 与费用上涨 | `verify_count < 2` 硬上限，第 3 轮强制进 synthesize |
| LLM 返回非 JSON | 解析失败 | 重试 1 次后放弃（换 prompt 不解决格式问题），记 `ai_errors` |
| 报告与证据脱节 | 图上有闭环、报告却没用到验证结果 | 已在 `synthesize_node` 注明：报告由 `write_report` 重新检索生成，**不消费 gathered/verification**（曾经的断线见 README 案例十二） |
| 运行记录不完整 | 看不出某次运行耗时 | 插入分支也写 `completed_at`（案例十三） |
| 人工改不动 AI 结果 | 分类/摘要错误无人纠正渠道 | `pending_review` + `web/review.html`：提交→审核→应用，形成闭环 |
| 状态丢失 | 进程崩溃后无法复盘 | 每步落 `agent_runs`（plan/gathered/verification/report/messages） |

## 8. MCP 工具层

`mcp_server/server.py` 用 FastMCP 暴露与 Agent 相同的 5 个工具，任何支持 MCP 的客户端都能接入：
`search_news`、`fetch_source`、`dedup_check`、`verify_claim`、`write_report`。
好处是**工具只实现一次**：Agent 内部调用与外部 MCP 调用走同一份代码，行为不会漂移。

## 9. 成本与可观测性

- **统一入口**：`llm.chat(..., purpose=...)`，所有链路（分析/问答/洞察/Agent/评测）都经此，成功与失败都写 `llm_traces`。
- **计量**：官方价目表分三档（输入缓存命中/未命中/输出）+ 峰谷时段（峰值 2 倍）+ 汇率折算，模型写在 `db.py` 一处。
- **看板**：`GET /api/stats?days=N`（接口）与 `web/stats.json`（静态站页脚），另有 `python llm.py --reconcile <账单金额>` 做账单对账。
- **实测**：单次调用 11 in / 28 out → ¥0.000131；与控制台首次对账显示单价口径一致、差额主要来自埋点覆盖率（详见 README「首次对账结果」）。

## 10. 四种运行形态

| 形态 | 启动方式 | 用到什么 | 不包含什么 |
|---|---|---|---|
| 线上（含 AI 问答） | 无（持续自动） | Pages 静态文件 + **Fly.io 上的 API** | 需要一次性部署（见 README「部署到 Fly.io」） |
| 纯静态降级 | 不配置 `AI_API_BASE` | 只有 Pages 静态文件 | 无问答（前端提示连不上 API），其余功能正常 |
| 本机全栈 | `启动全栈.bat` / README 手动命令 | API(8000) + 静态站(8765) | 需要本机 Python 环境 |
| 容器 | `docker compose up --build` | 只有 API（含嵌入模型，可离线检索） | 不含静态站（`web/` 交给 Pages 或本地 http.server） |

**前端如何找到 API**：`web/config.js` 由 `fetch.py` 在导出时从环境变量 `AI_API_BASE` 生成，`index.html` / `review.html` 都从这里读 `window.AI_API_BASE`，未配置时回落 `http://localhost:8000`。地址出口只留这一处（有测试锁住），避免又有人在 HTML 里硬编码线上地址。

**公开端点的成本闸**：`/ask` 暴露在公网，因此带「单 IP 每日 5 次 + 全局每日 100 次」双配额（`api/ratelimit.py`），且在检索之前判定 —— 拒绝时不加载模型、不调 LLM，一分钱不花。计数为进程内存态、重启清零（已知边界，README 已标注）。

## 11. 关键取舍

| 决策 | 备选 | 为什么这么选 |
|---|---|---|
| 静态 `data.json` + 原生前端 | 全栈 SSR / SPA 框架 | 零运行成本、评审可复现；前端无构建步骤，双击就能跑 |
| SQLite 单文件并提交进仓库 | Postgres + pgvector | 单写者、数据量 MB 级；省掉连接池与迁移运维。`db.py` 保留 PG 分支但**未启用**，如实标注 |
| 本地小模型嵌入（bge-small-zh） | 云端 embedding API | 零边际成本、可离线；代价是检索 Recall@5 偏低（0.26，见 EVALS.md） |
| 规则化关键词图谱（非 LLM 抽取） | LLM 抽实体 | 零成本且结果可解释；代价是词表需人工扩充 |
| RAGAS 论文口径自实现 | 直接用 ragas 库 | ragas 与 Agent 所需的 langchain 1.x 生态互斥（案例八），保运行时优先 |
| 门禁逐指标声明基线 | 单一全局 `--baseline` | 单一阈值会把「未达标项」当「退化」拦死部署（案例十一） |
| cron-job.org + `workflow_dispatch` | GitHub 原生 `schedule` | 新仓库 `schedule` 事件实测长期不派发（案例四） |
| 统一 LLM 入口 | 各链路各写 HTTP | 埋点覆盖率决定成本看板是否可信（Day 25 实测覆盖率从 13% 提升到全量） |

## 12. 扩展点

| 想做什么 | 改哪里 |
|---|---|
| 加一个信息源 | `fetch.py` 的 `SOURCES` 列表新增一项（RSS 或 API），无需改其他文件 |
| 换 LLM | `llm.DEFAULT_MODEL` + `db.DEEPSEEK_PRICING_USD`（价目表） |
| 换嵌入模型 | `retrieval.py` 的模型名 + `build_embeddings.py` 重建向量 |
| 调遗忘策略 | `fetch.py` 顶部四个常量（日配额 / 半衰期 / 图谱上限 / 保留期） |
| 加一项评测 | `evals/` 新增脚本，并在 `run_all.py` 的 `EVAL_SCRIPTS` 与 `baseline.json` 里登记 |
| 加一个 MCP 工具 | `agent/tools.py` 加 `@tool` 函数并登记进 `ALL_TOOLS`，MCP 侧自动可见 |
| 收紧/放宽门禁 | `evals/baseline.json`（逐指标 snapshot/tolerance/floor/target） |
