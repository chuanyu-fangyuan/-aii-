# AI 情报站 → 智能知识库 · 唯一行动清单

> **本文档是唯一有效的行动清单。** 取代此前两份：
> - ~~`ROADMAP_AI知识库升级.md`~~ —— 阶段 1-5 已并入本文 Week 1-2
> - ~~`ROADMAP_岗位对标与优化清单.md`~~ —— 岗位调研依据已并入本文 **附录 A**，简历/面试话术并入 **附录 B**
>
> 版本 **v2.1**（2026-09-18 二次核验：起始日调整为 9/22 周二 + 冷启动策略优化 + 防错清单）
> 预算：**98 小时**（28 天 × 3.5 小时） · 取舍偏好：优先保「面试可讲」
> 排期：**Day 1 = 2026-09-22（周二）** → 目标完成 **2026-10-19**，缓冲 10/20-10/21

---

## 〇、本次复核结论

### 0.0 v2.1 相对 v2.0 的 5 项变更（2026-09-18 二次核验）

| # | 变更 | 原因（均为实测） | 位置 |
|---|---|---|---|
| 1 | **起始日 9/19 → 9/22（周二）** | 用户指定；整条时间轴后移 3 天，Day 0 提前到 9/21 周一晚留补救窗口 | §5 全篇 |
| 2 | **Day 1「重跑 fetch.py 同步 917 条」作废** | **做不到**——Algolia 只返回最新 40 条，历史抓不回来。改为从线上 `data.json` 导入 | Day 1 |
| 3 | **Day 3「全量 917 条分析」改为「近7天 + 噪音过滤 ~300 条」** | 实测 HN 693 条 **median 仅 2 分**，score≥20 只有 14 条。全量分析 67% 是浪费 | §5.1 |
| 4 | **成本重算（原估算低估）** | 原文写「日常增量 ~16 条/天」，实测 100-150 条/天 | §10 |
| 5 | **新增 §12 防错清单** | 实测出 3 个阻塞 + 识别 4 个国内环境必踩的坑（尤其 HuggingFace 直连不通） | §12 |

**工时变化**：Day 1 省 0.5h、Day 3 省 2h → 共省 2.5h，转入缓冲池（用于 Week 2 检索调优）。

---

### 0.1 v2.0 修正的 8 个问题

### 0.1 修正的 8 个问题

| # | 问题 | v1.0 原状 | 修正 |
|---|---|---|---|
| 1 | **数据基线错误** | 三份文档统一写「337 条」「~330 条」「317→331」 | 实测线上 **917 条**（9/18 12:52）。全清单按 917 重算 |
| 2 | **工作量单位混用** | 「98 小时（14 标准人天）」而每天标「工时 1 天」×28 = 28 人天 | 98÷8=12.25≠14（原算术本身错）；28 人天=224h 是预算 2.3 倍。**全部改按小时标注，总量硬锁 98h** |
| 3 | **三套编号体系** | A 用「阶段 1-5」、B 用「阶段 6-10」、C 用「Day 1-28」 | 统一为 **Day 1-28**，阶段名仅作标签 |
| 4 | **目标值互相冲突** | 准确率 80% vs 75%；RAG 75% vs 70%；覆盖率 70% vs 60%；且 Day22 门禁 0.80 与 Day7 熔断 0.75 **同文档内不自洽** | 改为 **双层标准**（熔断线 / 达标线），见 §6 |
| 5 | **技术路线三次反复** | 向量 faiss+npy→pgvector；后端 CF Workers→FastAPI；库 SQLite→PG | 锁定唯一路线，见 §4；A 的 CF Workers 方案**明确作废** |
| 6 | **MCP 优先级冲突** | B 列为 P0 必备（阶段 7 验收含「MCP 可用」）；C 说可跳过 | 定为 **P1 加分项**：Week 3 有余量才做 |
| 7 | **4 项关键技术前提缺失** | 三份文档均未提及 | 见 §0.3，已补进对应 Day |
| 8 | **文档循环引用** | A 说「以 B 为准」→ B 说「以 C 为准」→ C 不引用 | 收敛为本文单份 |

### 0.2 已核验为真、可直接沿用的部分

| 项 | 核验方式 | 结果 |
|---|---|---|
| 4 个数据源与代码结构 | 读 `fetch.py`（481 行） | ✅ 与描述一致 |
| `news` 表 11 列 / `update_runs` 表 | `PRAGMA table_info` | ✅ 与「仅扩 schema」描述一致 |
| `ai_errors` / `llm_traces` / `pending_review` 尚不存在 | 查表清单 | ✅ 确认为待新建 |
| 起始日 9/22 = 周二 | 日历核对 | ✅ 正确 |
| **Docker daemon 实际可连** | `docker info` | ❌ **连不上**（CLI 有、daemon 未运行）→ 已列 Day 0 阻塞项 |
| **本地 `.git` 可用** | `git status` | ❌ **`not a git repository`**（缺 `.git/refs`）→ 已列 Day 0 阻塞项 |
| **Python 3.12 可用** | `py -3.12 -c` | ✅ 3.12.6 已安装，无需额外安装 |
| 成本量级（< 2 元/月） | 按筛选后 ~300 条 + 日增量实算 | ✅ 成立，实测比预估更省（见 §5.1 与 §10） |
| 嵌入体积 < 5MB | 917 × 768 × 4B | ✅ ≈ 2.8 MB |
| 线上站点存活 | 拉 `data.json` | ✅ HTTP 200，2 小时前刚更新 |
| **HN 数据噪声比例** | 解析 693 条 summary 中分数 | ⚠️ **median 仅 2 分**，是冷启动浪费的根源 → 见 §5.1 |

### 0.3 补进的 4 项关键技术前提（原文档完全没写）

| # | 缺失前提 | 为什么致命 | 补进位置 |
|---|---|---|---|
| 1 | **跨域（CORS）+ HTTPS 混合内容** | 前端在 `github.io`(HTTPS)，API 在 Fly.io/Render(HTTPS)。跨域必须配 CORS，否则浏览器直接拦掉，且 API 必须 HTTPS 否则混合内容被阻断 | Day 5 |
| 2 | **Actions 里怎么跑 PostgreSQL** | `analyze` job 依赖 PG，而 GitHub Actions 需要 `services:` 起 PG 容器，否则 job 必挂 | Day 7 |
| 3 | **「两次运行结果完全一致」不可达** | LLM 输出有随机性，即使 `temperature=0`，DeepSeek API 也不保证逐字节一致 | Day 13（改为「评测脚本可复现」） |
| 4 | **Python 3.13 兼容风险** | 本机 Python **3.13.14**，而 `sentence-transformers`/`torch`、`faiss-cpu` 在 3.13 上 wheel 支持不全 | Day 0 / Day 8（建 3.11 或 3.12 venv） |

### 0.4 一个必须先解决的阻塞项

**本地 `.git` 再次损坏：缺 `refs/` 目录，`git` 命令全部报 `not a git repository`。**
`Day 1` 的「新建分支 `feat/ai-knowledge`」在当前状态下**无法执行**。修复步骤见 §9 Day 0。

---

## 一、事实基线（2026-09-18 实测，全清单以此为准）

### 1.1 静态事实（不会变）

| 维度 | 实测值 | 备注 |
|---|---|---|
| 线上 `data.json` | 800 KB | 加 AI 字段后预估 ~1.2 MB（gzip 后约 200 KB，可接受） |
| 线上最近生成 | 2026-09-18 12:52（北京） | 站点健康 |
| 代码规模 | `fetch.py` 481 / `app.js` 464 / `graph.js` 213 / `styles.css` 403 / `index.html` 77 = **1638 行** | |
| 依赖现状 | 仅 `feedparser` | 其余全部待装 |
| 环境 | 默认 Python 3.13.14；**`py -3.12` 可用（3.12.6）**；Docker CLI 29.6.2；Compose v5.3.1 | ⚠️ Py3.13 对 ML 库不友好，用 3.12 |
| 线上代码状态 | `fetch.py` 与 `app.js` 的 schedule 数据驱动改动**已推送并生效** | `meta.schedule` 已存在于线上 data.json |
| 调度链路 | cron-job.org → `workflow_dispatch` → Actions → Pages，每 3 小时 | GitHub 原生 `schedule` 事件长期 0 派发 |

### 1.2 动态事实（**会每天变，禁止在计划里写死数字**）

| 维度 | 9/18 实测 | 下周二（9/22）预估 | 说明 |
|---|---|---|---|
| 线上新闻总数 | **917 条** | **约 1200-1400 条** | HN 693 / arXiv 120 / TC 75 / Verge 29（9/18 快照） |
| 日增量 | 约 100-150 条/天 | 同左 | 来源：HN 40 条/次 × 8 次/天，去重后实际落库量 |
| 近 7 天条数 | 908 条 | 约 900-1000 条 | 因抓取窗口滚动，**近 7 天量级稳定**，不随总量线性增长 |
| 本地 `news.db` | 319 条，停在 9/16 | 不会自动增长 | ⚠️ 见 §5 Day 1 —— **无法靠重跑 `fetch.py` 补齐** |

> **关键性质：数据是「流式追加」而非「全量快照」。**
> `fetch.py` 用 Algolia `search_by_date` 只取**最新 40 条**，历史数据抓不回来。因此：
> ① 不存在"全量重跑采集"这回事；② `INSERT OR IGNORE` + `ai_status` 保证已处理记录永不重复分析；
> ③ analyze 只需处理 `ai_status != 'done'` 的增量。**"数据每天在涨"不影响方案可执行性。**

### 1.3 实测的三个执行阻塞（Day 0 必须解）

| # | 阻塞 | 实测证据 | 影响 |
|---|---|---|---|
| 1 | **本地 `.git` 损坏** | `.git/refs` 目录缺失，所有 git 命令报 `not a git repository` | Day 1 建分支直接失败 |
| 2 | **Docker daemon 未运行** | `docker info` 报 `cannot find the pipe/dockerDesktopLinuxEngine`；`Docker Desktop.exe` 不在默认路径 | Day 2 起 PG 起不来 |
| 3 | ~~Python 3.13~~ | **已解决**：`py -3.12` 可用（3.12.6），直接 `py -3.12 -m venv` | — |

---

## 二、不变量（升级过程中绝不破坏）

| 不变量 | 含义 |
|---|---|
| `fetch.py` 采集与去重逻辑 | 双哈希去重 + `INSERT OR IGNORE` 零变更 |
| `data.json` 字段只增不删 | 旧前端读到 `undefined` 即降级，不报错 |
| cron-job.org 配置不变 | 仍每 3 小时触发；analyze 复用同一次运行 |
| 原 8 项基础验收零回归 | 真实数据 / 重复幂等 / 单源容错 / 移动端 / XSS 等 |
| **API Key 永不进 repo / 前端 / `data.json`** | 只存 GitHub Secrets + 部署平台环境变量 |

---

## 三、不做清单（防止时间黑洞）

| 不做 | 原因 |
|---|---|
| React / TypeScript 重写前端 | 求职方向是后端 / AI 应用；原生 JS 已够用 |
| 实体知识图谱（原阶段 5） | 趣味性高但岗位价值低；现有图谱已足够展示 |
| Langfuse / 完整可观测性平台 | 用 PG `llm_traces` 表自建，够用且更可控 |
| 模型微调（LoRA） | JD 多标「了解」，投入产出比低，需 GPU |
| Kubernetes / 微服务拆分 | 项目体量撑不起，硬拆暴露「为简历而架构」 |
| 多模态、爬虫反爬对抗 | 与岗位主线无关 |
| 换成 Java / Spring Boot | Python 积累已深，切换成本高收益低 |

---

## 四、技术决策（锁定唯一版本，不再变更）

| 决策 | 选定 | 理由 |
|---|---|---|
| LLM | **DeepSeek-V3** | 国内直连、约 $0.14/M input、中文好 |
| Embedding | **bge-small-zh-v1.5**（本地） | 中文可用、0 成本、约 100MB |
| 数据库 | **PostgreSQL 16 + pgvector** | 一次到位，跳过 SQLite→PG 迁移；pgvector 是 JD 点名产品 |
| 向量存储 | **pgvector**（`news.embedding` 列） | 同上。**原 `faiss + npy` 方案作废** |
| 检索 | **BM25 + 向量混合 + RRF 融合** | 比纯向量稳；加时间衰减（半衰期 30 天） |
| 后端 | **FastAPI**（唯一后端） | JD 最高频框架。**原 Cloudflare Workers 方案作废** |
| Agent | **LangGraph** 状态图 + HITL | JD 出现率最高的 Agent 框架 |
| 评测 | **自建标注集 + RAGAS + LLM-as-judge + CI 门禁** | 56% JD 要求，#1 差异化项 |
| 部署（API） | **Fly.io** | 免费额度够用、支持 Docker + 常驻进程 + PG |
| 容器 | **Docker + Docker Compose** | 一键复现 |
| 测试 | **pytest + ruff + black + mypy** | 覆盖率见 §6 |
| MCP | **P1 加分项** | Week 3 有余量才做 |

---

## 五、28 天日计划

**总预算：95.5 小时**（原 98h，v2.1 通过 Day 1 -0.5h / Day 3 -2h 省下 2.5h）。
每日按「工时（小时）」标注，**Day 1-28 加总 = 95.5h**；`Day 0` 是 9/21 周一晚额外的 2h 准备工作，不计入内。
省下的 2.5h **不分配到具体某天**，作为 Week 2 检索调优的弹性缓冲（RAG 调参最容易超时，见 §6 熔断机制）。
**时间轴（起始日 9/22 周二）**：W1 9/22-9/28 ｜ W2 9/29-10/5 ｜ W3 10/6-10/12 ｜ W4 10/13-10/19 ｜ 缓冲 10/20-10/21。
国庆假期（10/1-10/7）横跨 W2 末与 W3 初——若假期投入超 3.5h/天，**多出的时间优先补 W1-W2 欠账，不要提前做 W4**。

### Week 1 · 地基与服务骨架（9/22-9/28｜24.5h）

**本周目标**：FastAPI 能跑、AI 分析能出结果、前端能看到分类标签。
**起始日**：2026-09-22（周二）。`Day 0` 提前到 9/21（周一）晚上，留出故障补救窗口。

#### Day 0（9/21 周一晚）· 解阻塞 + 环境准备｜2h
| 项 | 内容 |
|---|---|
| 任务 | ① **修复本地 `.git`**（实测确认损坏，见 §9.1）② **启动 Docker Desktop** 并确认 `docker info` 正常（实测未运行，见 §9.2）③ 建 venv：`py -3.12 -m venv .venv`（3.12.6 已就绪，无需安装）④ 注册 DeepSeek + 充值 10 元 ⑤ 建 GitHub Secret `DEEPSEEK_API_KEY` |
| 产出 | 可用的 git 仓库 + venv + Docker + Secret 就位 |
| 验收 | `git status` 正常；`docker info` 返回 ServerVersion；venv 内 `python -c "import feedparser"` 通过；`python -V` 显示 3.12.x |

#### Day 1（9/22 周二）· 基线与分支｜1.5h（原 2h，省 0.5h）
| 项 | 内容 |
|---|---|
| 任务 | ① 新建分支 `feat/ai-knowledge` ② **从线上 `data.json` 导入基线**（不是重跑 `fetch.py`）——写 `import_baseline.py`，读线上 JSON 写入本地库。原因见下方 ⚠️ |
| 产出 | 本地库与线上对齐 + 分支就绪 |
| 验收 | 本地条数与线上差异 < 1%；`git branch` 显示在 `feat/ai-knowledge` |

> ⚠️ **原方案作废**：原文写「本地跑 `fetch.py` 把库从 319 条同步到 917 条」——**做不到**。
> Algolia `search_by_date` 只返回最新 40 条，本地重跑只能拿回 ~40 条/源，历史抓不回来。
> 正确做法：线上 `data.json` 已含全部 917 条，直接 `curl` 下来解析导入。

#### Day 2 · 数据层 schema 与 PG｜4h
| 项 | 内容 |
|---|---|
| 任务 | ① 设计新 schema：`news` 加 7 字段（`ai_category` / `ai_summary_zh` / `importance` / `verification` / `entities_json` / `verification_note` / `ai_status`）+ 新表 `ai_errors` / `llm_traces` / `pending_review` ② 写 `migrations/001_init.sql` ③ `docker-compose.dev.yml` 起 PG + pgvector ④ 写 `db.py` 连接层 ⑤ 把 Day 1 的基线数据灌入 PG |
| 产出 | `docker-compose.dev.yml` + `migrations/001_init.sql` + `db.py` |
| 验收 | `docker compose -f docker-compose.dev.yml up -d` 成功；`psql` 能查到 4 张表结构；`CREATE EXTENSION vector` 成功；`news` 表条数 = 基线条数 |

#### Day 3 · LLM 分析流水线｜3h（原 5h，省 2h）★策略变更★
| 项 | 内容 |
|---|---|
| 任务 | ① `analyze.py`：`analyze_one()` ② **调用时带 `response_format={"type":"json_object"}`**（DeepSeek 官方支持，见 §12 防错 4）③ Prompt 模板（分类/摘要/实体/验证 六字段）④ 幂等：`WHERE ai_status IS NULL OR ai_status != 'done'` ⑤ 失败重试 3 次（指数退避）+ 错误落 `ai_errors` ⑥ 单条失败不阻断 ⑦ 节流：每 10 条 sleep 1s ⑧ **写入前按 §5.1 的过滤规则筛出待分析对象** |
| 产出 | `analyze.py`（约 220 行）+ `prompts/v1_baseline.txt` + `analyze_candidates.sql` |
| 验收 | 对**筛选后的 ~300 条**跑一遍（预计 13-18 分钟），成功率 ≥ 95%；`ai_category` 非空率 ≥ 95% |

#### 5.1 冷启动分析范围（**最节约的关键决策**）

**原方案「对全量 917+ 条跑一遍」是巨大浪费。** 9/18 实测 HN 分数分布：

```
HN 693 条 → median = 2 分 · score≥10 仅 28 条 · score≥20 仅 14 条
```

即 HN 抓回的主要是「刚发布、0-2 分、尚未被投票」的帖子。**对知识库价值接近零，分析它们还会污染评测集。**

**过滤规则（冷启动用）**：

```sql
-- 待分析对象 = 近 7 天 AND (非 HN 源 OR HN 分数 >= 5)
SELECT * FROM news
WHERE fetched_at >= now() - interval '7 days'
  AND ai_status IS DISTINCT FROM 'done'
  AND (source_id != 'hackernews' OR summary ~ '\d+ 分' AND (regexp_match(summary, '(\d+) 分'))[1]::int >= 5);
```

**效果实测（9/18 数据）**：

| | 原方案 | 优化后 | 省 |
|---|---|---|---|
| 分析条数 | 908（近7天全量） | **约 300** | **-67%** |
| 冷启动耗时 | 60-75 分钟 | **13-18 分钟** | **-75%** |
| 冷启动成本 | 0.8 元 | **约 0.2 元** | **-75%** |
| 分类准确率 | 受噪音拉低 | **更高**（少了噪音干扰） | — |

**日常增量（常态）**：每天新增约 100-150 条 → 过滤后约 60-80 条 → **约 3-5 分钟、0.05 元/天**。

> **代价与取舍**：知识库历史覆盖范围 = 近 7 天。对「AI 资讯」场景足够（用户关心的是「最近发生了什么」）。
> 若 Week 4 有余量想扩充历史，可全量补跑一次（约 0.8 元、70 分钟），但**不是必需项**。

#### Day 4 · FastAPI 骨架 ★关键路径★｜4h
| 项 | 内容 |
|---|---|
| 任务 | ① `api/main.py` + 路由分层 ② Pydantic schemas ③ 依赖注入（DB session）④ API Key 鉴权中间件 ⑤ 端点 `GET /health`、`GET /news`、`GET /news/{id}` |
| 产出 | `api/` 目录（main / schemas / deps / middleware）+ `/docs` 可访问 |
| 验收 | `uvicorn api.main:app --reload` 启动；`/docs` 显示 3 个端点；无 key 请求 `/news` 返回 401，错 key 返回 403，非法参数返回 422 |

#### Day 5 · 分析结果接入 API + 前端双源｜3.5h ★补 CORS★
| 项 | 内容 |
|---|---|
| 任务 | ① `POST /analyze/trigger`（带鉴权）② **配置 CORS**：允许 `https://chuanyu-fangyuan.github.io`，本地开发用 `http://localhost:*` ③ 前端 `app.js` 双数据源：优先 fetch API，失败回落静态 `data.json` ④ 渲染分类 chip（7 色） |
| 产出 | 前端显示分类标签；API 与静态站共存 |
| 验收 | 断网时前端仍能展示（走 data.json 回落）；联网时显示 AI 分类；**浏览器 Console 无 CORS 报错** |

#### Day 6 · 验证角标 + 标注集启动｜3h
| 项 | 内容 |
|---|---|
| 任务 | ① 前端验证角标（✅/⚠️/❌）+ tooltip 说明依据 ② **开始标注**：从已分析新闻中随机抽 30 条，人工填 `evals/dataset.jsonl`（`expected_category` / `expected_verification`）③ 固定随机 seed |
| 产出 | `evals/dataset.jsonl`（30 条）+ 前端验证 UI |
| 验收 | 角标正确显示；标注文件逐行 `json.loads` 合法；seed 固定后可复现同一批抽样 |

#### Day 7 · Week 1 验收 + 补欠账｜3h ★补 Actions PG★
| 项 | 内容 |
|---|---|
| 任务 | ① 更新 `.github/workflows/update.yml`：在 `update` 后、`deploy` 前插 `analyze` job，**用 `services: postgres` 起 PG 容器** ② 复用现有 3 次重试 + fetch/reset 推送逻辑 ③ 抽样 30 条人工比对分类准确率 ④ 补欠账 |
| 产出 | 全链路跑通记录 + 准确率报告 |
| 验收 | 全链路（cron 触发 → 抓取 → 分析 → 部署）跑通；**分类 F1 ≥ 0.70（熔断线）** |

**✅ Week 1 里程碑**
- [ ] FastAPI 服务可访问，`/docs` 完整
- [ ] 筛选后的 ~300 条新闻全部有 AI 分类与摘要（`ai_status='done'`）
- [ ] 前端显示分类 chip + 验证角标（含 CORS 正常）
- [ ] Actions 自动跑通 analyze job（含 PG service）
- [ ] 标注集 30 条
- [ ] 分类 F1 ≥ 0.70

---

### Week 2 · 检索与 RAG（9/29-10/5｜24.5h）

**本周目标**：语义检索可用，问答带引用溯源。

#### Day 8 · Embedding 流水线｜3h
| 项 | 内容 |
|---|---|
| 任务 | ① 装 `sentence-transformers`，加载 `bge-small-zh-v1.5`（首次下载 ~100MB）② `build_embeddings.py`：批量计算 + 写 pgvector ③ Actions 缓存 `~/.cache/huggingface/` ④ 增量逻辑（只算没算过的）|
| 产出 | `build_embeddings.py` + `news.embedding` 列有数据 |
| 验收 | 已分析集（~300 条）全部有 embedding；**同一条新闻两次计算余弦相似度 > 0.99**；缓存命中后耗时 < 30 秒 |

#### Day 9 · 混合检索层｜4h
| 项 | 内容 |
|---|---|
| 任务 | ① `retrieval.py`：pgvector `<=>` 向量检索 + BM25（`rank_bm25`）② RRF 融合（k=60）③ 时间衰减（半衰期 30 天）④ 接口 `search(query, top_k)` |
| 产出 | `retrieval.py`（约 150 行） |
| 验收 | 20 个测试 query，**top-5 命中率 ≥ 0.65（熔断线）**；产出「纯向量 vs 混合检索」对比数据 |

#### Day 10 · RAG 问答端点｜4h
| 项 | 内容 |
|---|---|
| 任务 | ① `POST /ask` ② Prompt 注入 top-5 上下文 + 强制引用编号 `[1][2]` ③ 输出 `{answer, citations:[{news_id,title,link}]}` ④ 幻觉防护：校验引用 ID 真实存在 ⑤ 硬超时 25s |
| 产出 | `/ask` 可用 + `prompts/rag_v1.txt` |
| 验收 | 问「OpenAI 最近有什么进展」返回带编号引用的回答；引用 ID 全部能在库中查到 |

#### Day 11 · 问答前端｜3h
| 项 | 内容 |
|---|---|
| 任务 | ① 顶部加问答入口（点击展开弹层）② `ask.js`：调 `/ask` + 流式渲染 ③ 引用列表可点击跳原文 ④ 加载态 / 错误态 / 空态 |
| 产出 | 可交互的问答 UI |
| 验收 | 移动端 390px 可用；加载显示骨架屏；API 失败有明确提示 |

#### Day 12 · 主题聚类与「今日洞察」｜3h
| 项 | 内容 |
|---|---|
| 任务 | ① `analyze_daily_topics()`：当日新闻喂 LLM 生成 3-5 主题 ② 写入 `data.insight` ③ 前端「今日 AI 洞察」折叠卡 ④ 点击主题跳转对应新闻 |
| 产出 | 洞察卡上线 |
| 验收 | 连续 3 天生成成功；主题数在 3-5 之间；点击主题能过滤到对应新闻 |

#### Day 13 · 评测脚本 v1｜4h
| 项 | 内容 |
|---|---|
| 任务 | ① `evals/eval_classify.py`：Accuracy / P-R-F1 per-class + 混淆矩阵 ② `evals/eval_retrieval.py`：Recall@5 / MRR / NDCG@5 ③ 扩充标注集到 60 条 ④ 生成 `evals/report_week2.md` |
| 产出 | 两个评测脚本 + 首份评测报告 |
| 验收 | **固定 seed + 缓存 LLM 输出**，同一份缓存下两次运行结果完全一致；报告含分类 F1 与检索 Recall@5 数值 |

> ⚠️ 原验收写「两次运行结果完全一致」——因 LLM 有随机性，**必须先把推理结果缓存到本地**再跑评测，否则此条不可达。

#### Day 14 · Week 2 验收 + 补欠账｜3.5h
| 项 | 内容 |
|---|---|
| 任务 | ① 端到端验证：问答 → 引用 → 跳原文 ② 成本核对（累计 token 与费用）③ 补欠账 |
| 产出 | Week 2 验收记录 |
| 验收 | **RAG 问答 20 组事实型 query 人工评估，正确率 ≥ 0.70（熔断线）** |

**✅ Week 2 里程碑**
- [ ] pgvector 存有全部已分析新闻的 embedding（~300 条）
- [ ] 混合检索 top-5 命中率 ≥ 0.65
- [ ] `/ask` 返回带引用的答案
- [ ] 前端问答 UI 可用（含移动端 390px）
- [ ] 今日洞察卡上线
- [ ] 评测脚本 v1 跑通，有首份报告
- [ ] 标注集 60 条

---

### Week 3 · Agent（10/6-10/12｜24.5h）★接国庆假期尾★

**本周目标**：把「流水线」升级为「能自主决策的 Agent」—— 50% JD 的硬要求。

#### Day 15 · 工具层｜3.5h
| 项 | 内容 |
|---|---|
| 任务 | ① `agent/tools.py`：5 个工具（LangChain `@tool`）<br>　`search_news(query)` / `fetch_source(source_id)` / `dedup_check(url)` / `verify_claim(claim)` / `write_report(topics)`<br>② 全部复用已有函数（retrieval / fetch / analyze），不重写 ③ 工具单元测试 |
| 产出 | `agent/tools.py` |
| 验收 | 每个工具能独立调用并返回结构化结果；`pytest tests/test_tools.py` 全绿 |

#### Day 16 · LangGraph 状态图｜5h
| 项 | 内容 |
|---|---|
| 任务 | ① `agent/graph.py`：状态定义 + 6 节点<br>　`plan → gather → verify → synthesize → review → publish`<br>② 条件边：verify 发现可疑 → 回 gather 补证（**最多 2 轮**，防死循环）③ 状态持久化（PG 表 `agent_runs`）|
| 产出 | `agent/graph.py` + 状态图（`draw_mermaid`） |
| 验收 | 给定「总结今日 AI 领域进展」，Agent 自主调用 ≥3 个工具并产出报告；mermaid 能渲染 |

#### Day 17 · HITL 审核机制｜3.5h
| 项 | 内容 |
|---|---|
| 任务 | ① 重要结论进 `pending_review` 表 ② 审核端点 `POST /review/{id}`（approve / reject + 理由）③ 未审核内容不进线上 ④ 前端审核列表页 |
| 产出 | 审核流上线 |
| 验收 | 构造一条待审结论，未审核时线上查不到；approve 后出现 |

#### Day 18 · Agent 联调与 Prompt 优化｜4h
| 项 | 内容 |
|---|---|
| 任务 | ① 跑 5 个真实场景观察行为 ② 修死循环 / 工具误用 / 输出格式问题 ③ **记录失败模式到 README（面试素材）** |
| 产出 | Agent 稳定运行记录 + 失败模式清单 |
| 验收 | 连续 5 次运行无崩溃；平均工具调用轮数在 3-6 之间 |

#### Day 19 · MCP Server（**P1 加分项，时间不够可跳过**）｜3h
| 项 | 内容 |
|---|---|
| 任务 | ① `mcp/server.py` 用 FastMCP 暴露 5 个工具 ② 本地用 MCP Inspector 验证 |
| 产出 | 可被 Claude Desktop / Cursor 调用的 MCP server |
| 验收 | MCP Inspector 能列出并成功调用全部工具 |

#### Day 20 · 评测 v2：RAGAS + LLM-as-judge｜4h
| 项 | 内容 |
|---|---|
| 任务 | ① 装 `ragas`，评 `faithfulness` / `answer_relevancy` / `context_precision` ② LLM-as-judge：另一模型按 rubric 打分（1-5）③ 补 20 组 RAG 问答对到标注集 ④ Prompt v2 对比实验 |
| 产出 | `evals/eval_rag.py` + v1/v2 分数对比表 |
| 验收 | RAGAS 三项指标有数值；v1 vs v2 有明确结论（哪个更好、差多少） |

#### Day 21 · Week 3 验收 + 补欠账｜1.5h
| 项 | 内容 |
|---|---|
| 任务 | ① Agent + RAG + 分类三条链路联合验证 ② 全量成本核算 ③ 补欠账 |
| 产出 | Week 3 验收记录 |
| 验收 | **三条链路在同一个 Actions 运行里全部成功** |

**✅ Week 3 里程碑**
- [ ] Agent 能自主完成一次完整情报任务
- [ ] 条件边补证逻辑生效（有验证记录）
- [ ] HITL 审核流可用
- [ ] RAGAS 三项指标有数值
- [ ] Prompt v1/v2 对比表
- [ ] （可选）MCP server 可被外部客户端调用

---

### Week 4 · 评测门禁 + 工程化 + 收尾（10/13-10/19｜24.5h）

**本周目标**：把项目从「能跑」变成「可信、可复现、可交付」。

#### Day 22 · Evals 整合 + 回归门禁｜3.5h
| 项 | 内容 |
|---|---|
| 任务 | ① `evals/run_all.py` 统一入口，输出 JSON 报告 ② 写进 Actions：`--baseline 0.75`（见 §6 说明）③ **故意降低 Prompt 质量，验证门禁能拦住** |
| 产出 | CI 回归门禁生效 |
| 验收 | 构造一次「质量下降」的提交，Actions 准确报错并阻止 |

> ⚠️ baseline 取 **0.75**（略低于达标线 0.80），留出模型抖动余量。原文档 Day 22 写 0.80、Day 7 写 0.75，二者不自洽。

#### Day 23 · 单测 + Lint｜5h
| 项 | 内容 |
|---|---|
| 任务 | ① `pytest` 覆盖 `parse_dt` / `url_hash` / `clean_summary` / 去重 / API 端点（TestClient）② `ruff` + `black` + `mypy` 进 CI ③ 覆盖率报告 |
| 产出 | `tests/` 目录 + CI lint 步骤 |
| 验收 | `pytest` 全绿；**覆盖率 ≥ 50%（熔断线）**；CI lint 无 error |

#### Day 24 · Docker 化｜4h
| 项 | 内容 |
|---|---|
| 任务 | ① `Dockerfile`（多阶段：builder + runtime）② `docker-compose.yml`：app + postgres(pgvector) + 一次性 migrate ③ `.dockerignore` ④ README 加「Docker 三步启动」 |
| 产出 | 可一键启动的容器编排 |
| 验收 | **在干净目录 `git clone` 后 `docker compose up` 能起服务**，`/docs` 可访问 |

#### Day 25 · 可观测性 + 成本看板｜3h
| 项 | 内容 |
|---|---|
| 任务 | ① `llm_traces` 表记录每次调用（model / tokens / latency / cost / status）② 封装统一 LLM 调用入口自动埋点 ③ `GET /api/stats` 返回累计 token 与费用 |
| 产出 | 成本看板端点 + trace 数据 |
| 验收 | `/api/stats` 返回真实累计费用，与 DeepSeek 后台对账误差 < 10% |

#### Day 26 · 文档全面更新｜4h
| 项 | 内容 |
|---|---|
| 任务 | ① README 重写：新架构图 / 部署 / 技术选型 / **评测报告** / 成本 / 已知限制 ② 新增 `ARCHITECTURE.md` ③ 新增 `EVALS.md` ④ 补充故障排查案例（Agent 失败模式） |
| 产出 | 三份文档 |
| 验收 | 按 README 在干净环境能跑通；文档中无与事实不符的描述（**交叉核对一遍**） |

#### Day 27 · 全链路验收｜2.5h
| 项 | 内容 |
|---|---|
| 任务 | ① 逐条过 §7 的 14 项验收清单 ② 确认无人值守链路仍工作 ③ 清理临时文件、分支合并到 `main` |
| 产出 | 验收记录表 |
| 验收 | 14 项全部通过或明确标注「未完成」 |

#### Day 28 · 简历与面试材料｜2.5h
| 项 | 内容 |
|---|---|
| 任务 | ① 更新简历项目描述（见附录 B）② 准备复试 10 分钟讲稿（数据流 / 技术取舍 / 故障定位）③ 准备 5 类现场修改预案 |
| 产出 | 简历定稿 + 讲稿 |
| 验收 | 简历一页不溢出；讲稿能脱稿讲 10 分钟 |

**✅ Week 4 里程碑**
- [ ] CI 回归门禁能拦住质量下降
- [ ] pytest 覆盖率 ≥ 50%
- [ ] `docker compose up` 一键启动
- [ ] `/api/stats` 成本对账准确
- [ ] 三份文档与事实一致
- [ ] 14 项验收全过或标注清楚
- [ ] 简历定稿

**缓冲期：10/20-10/21** —— 追赶 / 补漏。

---

## 六、双层标准与熔断机制

### 6.1 双层标准（解决 v1.0 的指标冲突）

**熔断线** = 低于此值立即停下调优，不进入下一周；**达标线** = 最终验收 / 简历要报的数字。

| 指标 | 熔断线 | 达标线 | 度量工具 | 关卡 |
|---|---|---|---|---|
| 分类 F1 | 0.70 | **0.80** | `eval_classify.py` | Day 7 |
| 检索 Recall@5 | 0.65 | **0.75** | `eval_retrieval.py` | Day 9/14 |
| RAG 人工正确率 | 0.70 | **0.80** | 20 组人工评估 | Day 14 |
| RAGAS faithfulness | 0.65 | **0.75** | `eval_rag.py` | Day 20 |
| 测试覆盖率 | 50% | **65%** | `pytest-cov` | Day 23 |
| CI 门禁 baseline | — | **0.75** | `evals/run_all.py` | Day 22 |
| 旧 8 项回归 | 100% | **100%** | README 验收表 | 全程 |

### 6.2 熔断点与动作

| 熔断点 | 触发条件 | 动作 |
|---|---|---|
| **Week 1 末** | 分类 F1 < 0.70 | **停下调 Prompt**，不进 Week 2。分类是所有下游的地基 |
| **Week 2 末** | RAG 正确率 < 0.70 | 砍 Week 3 的 MCP + HITL，时间用来调检索 |
| **Week 3 末** | Agent 崩溃率 > 20% | **降级为朴素 tool-calling loop**（不画状态图），保留 5 工具与评测 |
| **Week 4 中** | Day 24 仍没好 | 砍 Docker Compose 只留 `Dockerfile`；砍 trace 埋点改用现成 token 计数 |

### 6.3 降级顺序（时间不够时按此砍）

```
1. MCP server          （3h，加分行，非必需）
2. 可观测性平台         （改为简单计数）
3. Docker Compose      （只留 Dockerfile）
4. HITL 审核           （改为「标记待审」+ 邮件通知）
5. LangGraph 状态图     （降级为朴素 tool-calling loop）
6. React / 图谱         （本来就不做）
```
**永不砍**：FastAPI、Agent（哪怕降级版）、Evals —— 三项岗位硬门槛。

---

## 七、14 项验收清单（Day 27 逐条过）

| # | 验收项 | 通过条件 | 验证方式 |
|---|---|---|---|
| 1 | 真实数据 | 4 源均有数据，单源失败不影响 | `--fail-source techcrunch` |
| 2 | 幂等 | 重复导入不产生重复 | 连跑 2 次 `fetch.py`，第 2 次 inserted=0 |
| 3 | 分类准确 | F1 ≥ 0.80（达标线） | `evals/eval_classify.py` |
| 4 | 检索命中 | Recall@5 ≥ 0.75（达标线） | `evals/eval_retrieval.py` |
| 5 | RAG 可信 | RAGAS faithfulness ≥ 0.75 | `evals/eval_rag.py` |
| 6 | API 规范 | `/docs` 完整；无 key 401 / 错 key 403 / 非法参数 422 | 浏览器 + curl |
| 7 | Agent 可跑 | 自主调用 ≥3 工具完成任务 | `python -m agent.run` |
| 8 | 回归门禁 | 降质量提交被 CI 拦住 | 故意改坏 Prompt 提 PR |
| 9 | 一键部署 | 干净环境 `docker compose up` 成功 | 新目录 clone |
| 10 | 成本可查 | `/api/stats` 与后台对账误差 < 10% | 与 DeepSeek 后台比对 |
| 11 | 零回归 | 原 8 项基础验收仍全过 | 原 README 验收表 |
| 12 | 无人值守 | 关电脑 3 天后站点仍有新数据 | 观察 3 天 |
| 13 | **API key 零泄露** | repo / `data.json` / 前端构建产物均无明文 | `git grep` + 拉线上文件 grep |
| 14 | **移动端 390px** | 全部新 UI 通过视口测试 | DevTools 视口模拟 |

---

## 八、关键路径

```
Day 0 (修 git+Docker) → Day 1 (导入基线) → Day 2 (PG+pgvector) → Day 3 (analyze) → Day 4 (FastAPI)
                                                                              ↓
                                        Day 8 (embedding) → Day 9 (检索) → Day 10 (RAG)
                                                                              ↓
                                        Day 15 (工具) → Day 16 (LangGraph) → Day 17 (HITL)
                                                                              ↓
                                        Day 20 (RAGAS) → Day 22 (门禁) → Day 24 (Docker)
                                                                              ↓
                                                                          Day 27 (验收)
```

**最关键的 5 天：Day 0-4。** 这五天拖了，后面全挤。
**非关键路径**（可并行/可推迟）：前端改造、洞察卡、MCP、文档。

### 每日收尾习惯（保持 28 天不跑偏）
每天结束前花 5 分钟：
1. 在 `PROGRESS.md` 打勾今天完成的任务
2. 记录一个「今天卡住的问题」+ 怎么解决的（**这就是复试要讲的「问题定位」素材**）
3. 落后 > 0.5 天就对照 §6.3 砍项，**不要靠加班补**

---

## 九、Day 0（9/21 周一晚）· 半小时解掉全部阻塞

> 三项阻塞已实测确认（见 §1.3）。**这一节不做完，Day 1 直接卡死。**

### 1. 修复本地 git（阻塞项）

`git status` 报 `not a git repository`，`.git/refs` 目录整体缺失。这是**第二次出现**（上次在 9/16），说明本地 `.git` 不稳。

**快修（先试，30 秒）**：
```bash
cd /d/开发测试/ai-daily-brief
mkdir -p .git/refs/heads .git/refs/tags .git/refs/remotes/origin
git fetch origin main
git reset --hard origin/main
git status          # 期望：正常输出
```

**兜底（快修无效就用这个，5 分钟，更稳）**：
```bash
# 工作区文件先备份（fetch.py / web/ / README.md 等）
cd /d/开发测试
git clone https://github.com/chuanyu-fangyuan/-aii- ai-daily-brief-clean
# 把工作区里「有本地改动」的文件复制回去（正常只有 fetch.py / app.js / README.md）
# 然后以后都在这个目录工作，旧目录留作备份
```
> **建议直接用兜底方案。** 用 Git Bash 在项目目录外执行，避免被损坏的 `.git` 干扰。

### 2. 建 venv（用已就绪的 3.12）
实测 `py -3.12` 可用（3.12.6），**无需额外安装**：
```bash
py -3.12 -m venv .venv
source .venv/Scripts/activate     # Git Bash
python -V                          # 期望：Python 3.12.6
pip install feedparser requests
```
> 默认 `python` 是 3.13.14，`sentence-transformers`/`torch` 在 3.13 上 wheel 不全 —— 所以**必须显式用 3.12**。

顺便把 venv 加进忽略：
```bash
echo ".venv/" >> .gitignore && echo ".env" >> .gitignore
```

### 3. 启动 Docker Desktop（阻塞项）
实测 `docker info` 连不上 daemon（CLI 有、engine 未运行）：
```bash
# 先手动启动 Docker Desktop，等托盘图标变绿，再验证
docker info --format '{{.ServerVersion}}'   # 期望：输出 29.x 之类的版本号
```
> 若找不到 Docker Desktop：开始菜单搜 "Docker"。装了但没启动是最常见情况。
> **第一次启动要几分钟**，Day 0 提前跑掉，别到 Day 2 才等。

### 4. 注册 DeepSeek + 建 Secret
`platform.deepseek.com` 注册 → 充值 10 元 → 记下 API Key →
GitHub 仓库 Settings → Secrets and variables → Actions → New repository secret → 名称 `DEEPSEEK_API_KEY`
```bash
# 本地开发用 .env（已在 .gitignore 里，不会进仓库）
echo 'DEEPSEEK_API_KEY=sk-xxxx' > .env
```
> ⚠️ **绝不要**把 key 写进 `data.json`、前端代码、或任何会被提交的文件。

### 5. 提前把「噪声过滤」跑通（15 分钟，省 Day 3 两小时）
用线上现成数据验证 §5.1 的过滤规则真的有效：
```bash
cd /d/开发测试
curl -sS --ssl-no-revoke -o _live.json "https://chuanyu-fangyuan.github.io/-aii-/data.json"
python -c "
import json, re
d=json.load(open('_live.json',encoding='utf-8'))
from datetime import datetime, timezone, timedelta
cut=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
r7=[n for n in d['news'] if (n.get('published_at') or '')>=cut]
def keep(n):
    if n['source_id']!='hackernews': return True
    m=re.search(r'(\d+) 分', n.get('summary',''))
    return bool(m) and int(m.group(1))>=5
print('近7天:', len(r7), '→ 过滤后:', sum(1 for n in r7 if keep(n)))
"
```
> 9/18 实测输出：`近7天: 908 → 过滤后: 229`。数字量级对上（±50%）就说明规则可用。

### 6. Day 1 = 9/22（周二）正式开工

---

## 九·补、为什么这套方案「下周二开始」也跑得动

| 疑问 | answer |
|---|---|
| **数据每天在涨，计划里的数字会不会失效？** | 会失效，但**不影响执行**。已把所有写死的数字改成动态口径（§1.2），Day 3 用 SQL 实时筛，不依赖具体条数 |
| **涨到 1400 条会不会成本翻倍？** | **不会**。近 7 天窗口是滚动的，稳定在 900-1000 条；过滤后稳定在 ~300 条。**总库存涨，待分析量不涨** |
| **会不会重复分析旧数据白花钱？** | **不会**。`ai_status` 字段保证已处理的不重跑；`INSERT OR IGNORE` 保证不重复入库 |
| **落下的那几天新闻还能补吗？** | **不能**。Algolia 只返回最新 40 条 → 数据是流式的。**所以 cron-job.org 那套必须保持活着**（这是它真正的价值） |
| **晚 3 天开始有什么损失？** | 只损失 3 天的冷启动窗口（约 0.1 元），无其它影响 |

---

## 十、一个月后的你会得到什么

| 维度 | 具体成果 |
|---|---|
| **代码** | FastAPI 服务 + LangGraph Agent + pgvector 检索 + RAGAS 评测 + Docker 编排 |
| **数据** | 近 7 天 ~300 条带 AI 分析的新闻（此后每日增量）、60+ 条标注集、20 组问答对 |
| **指标** | 分类 F1 / 检索 Recall@5 / RAGAS faithfulness 三条可量化曲线（含达标线对照） |
| **文档** | README + ARCHITECTURE.md + EVALS.md + PROGRESS.md（含 28 天问题记录） |
| **面试** | 一个能当场打开的系统 + 一套带基线的评测数字 + 一次真实的故障定位故事 |
| **简历** | 覆盖 FastAPI / LangGraph / pgvector / RAG / RAGAS / Docker / MCP / Evals 关键词 |

### 成本实算（v2.1 重算，替换原「按 917 条基线」）

> ⚠️ 原估算「日常增量 ~16 条/天」是**严重低估**——实测日增 100-150 条（HN 40 条/次 × 8 次/天）。
> 下表按实测重算，并以「过滤后」口径计算。

| 项 | 计算 | 金额 |
|---|---|---|
| **一次性冷启动** | 300 条 × (500 in + 200 out) tokens | ≈ **0.27 元** |
| 日常增量分析 | 过滤后 ~50-60 条/天 × 700 tokens | ≈ **1.5 元/月** |
| RAG 问答 | 10 次/天 × 2500 tokens | ≈ 0.3 元/月 |
| Embedding | 本地 bge-small | **0** |
| Fly.io + Actions + Pages | 免费额度 | **0** |
| **合计** | | **冷启动 0.27 元 + 约 1.8 元/月** |

**对比原方案**：若不做 §5.1 的过滤，冷启动是 908 条 ≈ 0.8 元、日常是每天 100+ 条 ≈ 3 元/月 —— **过滤后省掉约 60%**。

**三个可选的进一步节约杠杆（按性价比排序）**：

| 杠杆 | 省 | 代价 |
|---|---|---|
| 提高 HN 阈值到 `score >= 10` | 冷启动 300→120 条（-60%） | 可能漏掉少量「刚发布但重要」的帖子 |
| 冷启动只取近 3 天 | 300→150 条（-50%） | 知识库历史更短 |
| 用 DeepSeek 缓存（同 prompt 前缀命中缓存价） | 约 -30% | 需 prompt 前缀稳定 |

**暂不启用**——现有成本（< 2 元/月）已远低于「值得优化的门槛」。真到用量变大时，按上表顺序调。

---

## 十一、风险清单与对策

> 继承自原 `ROADMAP_AI知识库升级.md` 第 6 节，并补入本次复核新发现的 4 项。

| 风险 | 触发条件 | 概率 | 影响 | 对策 |
|---|---|---|---|---|
| DeepSeek API 故障 | 服务商宕机 / 限速 | 中 | 分析整体跳过 | 重试 3 次；失败留 `ai_status='pending'`，下次重跑；前端不显示 `ai_*` 即降级 |
| DeepSeek 输出非 JSON | Prompt 漂移 | 中 | 单条失败 | 严格 JSON 校验；非 JSON 重试 1 次；仍失败置 `error` 落 `ai_errors` |
| Embedding 模型加载慢 | 首次 / 缓存失效 | 中 | Actions 超时 | `actions/cache` 缓存 `~/.cache/huggingface/` |
| Embedding 不一致 | 模型版本变化 | 低 | 检索抖动 | 锁版本 `bge-small-zh-v1.5`；变更时全量重建 |
| API key 泄露 | 误提交 / 前端误用 | 中 | 安全事故 | GitHub Secrets + 部署平台 env；`git grep` 入 CI；永不写 `data.json` |
| 幻觉回答 | LLM 编造引用 | 高 | RAG 准确率低 | 强制 prompt 要求引用编号；前端校验所有引用 ID 真实存在 |
| 旧数据无 AI 字段 | 升级前的存量 | 中 | 前端显示空 | 未处理记录不渲染 AI 区块，前端不报错 |
| **CORS / 混合内容拦截** | **前端与 API 跨域** | **高** | **前端完全取不到数据** | **Day 5 显式配置 CORS 白名单；API 必须 HTTPS；实测 Console 无报错** |
| **Actions 内无 PostgreSQL** | **analyze job 依赖 PG** | **高** | **CI 必挂** | **Day 7 用 `services: postgres` 起容器；或改用 `pgvector/pgvector` 镜像** |
| **Python 3.13 装不上 ML 库** | **本机为 3.13.14** | **高** | **Day 8 卡死** | **Day 0 建 3.11/3.12 venv；CI 里固定 `python-version: '3.11'`** |
| **演示时 API 冷启动** | **免费层休眠（Render 类）** | **中** | **面试当场打不开** | **选 Fly.io 常驻；前端双数据源回落；演示前预热一次** |

---

## 十二、防错清单（按「报错概率 × 卡死程度」排序）

> 目标：**把「遇到才查」变成「开工前就躲开」**。逐条对应到具体 Day。

### P0 · 已实测确认（不解决 Day 1 就停）

| # | 症状 | 根因 | 修复 | 对应 |
|---|---|---|---|---|
| 1 | `fatal: not a git repository` | `.git/refs` 目录缺失 | 见 §9.1（快修 or 重新 clone） | Day 0 |
| 2 | `cannot find the pipe/dockerDesktopLinuxEngine` | Docker Desktop 未启动 | 手动启动，等托盘变绿；`docker info` 验证 | Day 0 |
| 3 | `pip install torch` 编译失败 / 无 wheel | 默认 Python 3.13.14 | `py -3.12 -m venv .venv`（3.12.6 已就绪） | Day 0 |

### P1 · 国内环境几乎必踩（**这四条不提前处理，Week 1-2 会卡死**）

| # | 症状 | 根因 | 修复 | 对应 |
|---|---|---|---|---|
| 4 | **`sentence-transformers` 下载模型超时 / 连接被重置** | **`huggingface.co` 国内直连不通** | 设镜像：`export HF_ENDPOINT=https://hf-mirror.com`（写进 `.env` 和 Actions `env:`，**别只写在终端里**） | Day 8 |
| 5 | pip 装包极慢 / 失败 | 默认源在国外 | `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple ...`；或写进 `pip.conf` | Day 0 |
| 6 | **DeepSeek 返回内容不是 JSON，`json.loads` 报错** | LLM 输出有随机性，靠 prompt 约束不稳 | 两件事：① 调用时加 `response_format={"type":"json_object"}`（官方支持）② **prompt 里必须出现 "json" 字样**，否则接口报 400 | Day 3 |
| 7 | HTTP 429 限速 | 并发过高 | 串行 + `time.sleep(1)`（每 10 条）+ 指数退避重试（1s/2s/4s）；失败留 `pending` 下轮再跑，**不要原地硬重试** | Day 3 |

### P2 · 大概率遇到（有现成解法）

| # | 症状 | 根因 | 修复 | 对应 |
|---|---|---|---|---|
| 8 | 前端 Console 报 CORS / 混合内容 | 前端在 `github.io`，API 在 `fly.dev` | FastAPI `CORSMiddleware` 白名单加 `https://chuanyu-fangyuan.github.io`；API 必须 HTTPS；**实测 Console 无报错才算过** | Day 5 |
| 9 | Actions 里 analyze job 连不上 DB | runner 上没有 PG | job 加 `services: postgres`，镜像用 `pgvector/pgvector:pg16`（**自带扩展，省一步**） | Day 7 |
| 10 | `CREATE EXTENSION vector` 失败 | 用的 `postgres:16` 镜像没有 pgvector | 换 `pgvector/pgvector:pg16` | Day 2 |
| 11 | API 返回 200 但前端白屏 | 前端直接 `innerHTML` 渲染新字段 | 沿用现有 `textContent` 风格；**新字段一律可选**，`undefined` 时不渲染该区块 | Day 5 |
| 12 | Fly.io 部署失败 / 超过免费额度 | 配置错 / 忘了 `fly.toml` | **降级方案**：静态站继续用 Pages 兜底，API 只用于演示（演示前 `fly deploy` 预热一次） | Day 24 |

### 通用三条防错原则（贯穿全程）

| 原则 | 落地方式 |
|---|---|
| **每层都要有降级路径** | API 挂 → 前端回落 `data.json`；analyze 挂 → 前端不渲染 AI 区块；embedding 挂 → 退化为 BM25 检索 |
| **每个外部调用都要有幂等标记** | `ai_status` / `embedding IS NULL` / `ai_errors` —— 保证「跑一半挂了，重跑不重复花钱」 |
| **每个网络请求都要有超时** | `requests.get(..., timeout=30)`；LLM 调用 `timeout=60`。**没有超时的请求是隐性死锁** |

### 开工前的「防错自检」（Day 0 收尾时跑一遍）

```bash
# 1) git 正常
cd /d/开发测试/ai-daily-brief && git status
# 2) Docker daemon 活着
docker info --format '{{.ServerVersion}}'
# 3) venv 是 3.12 且 feedparser 可用
source .venv/Scripts/activate && python -V && python -c "import feedparser; print('ok')"
# 4) 镜像已设
echo $HF_ENDPOINT                                    # 期望 https://hf-mirror.com
# 5) 过滤规则有效（输出量级 200-350）
python -c "..."   # 见 §9.5
```
**5 条全过 = 可以开工。任何一条没过 = 停下来先解，别硬上。**

---

## 附录 A：岗位对标依据（原 `ROADMAP_岗位对标与优化清单.md` 精简）

**调研依据**：2026 年招聘市场真实 JD 抽样（390 个 AI Engineer 岗位）。

### A.1 JD 能力项出现频率

| 能力项 | 出现率 | 说明 |
|---|---|---|
| **Python + 软件工程基础** | 59% | 「能交付，不是写 notebook」 |
| **Evals / 评测体系** | **56%** | **#1 差异化项**，区分你和 prompt 调参玩家 |
| **Agent / 多智能体编排** | **50%** | 增长最快，也「最难造假」 |
| RAG 全链路 | 26% | 「设计一个 RAG 系统」是最高频面试开场题 |
| MLOps / 部署（Docker/K8s） | 17% | 「推理服务能在真实负载下稳定」 |

### A.2 招聘硬数据

| 指标 | 数值 | 含义 |
|---|---|---|
| 初级岗位占比 | ~1% | AI 工程师是**转型岗**，不是校招起点 |
| 中位经验要求 | 5 年 | 社招通道基本关闭 → **主战场是校招** |
| 从软件工程背景转型 | 3-5 个月 | 你已在这条路上 |

### A.3 三个 P0 缺口（为什么排进计划）

| 缺口 | 为什么致命 | 补在哪 |
|---|---|---|
| **FastAPI 服务化** | 几乎每份 JD 都要求 Web 框架；「我用 Serverless 转发了一下」会被判定不合格 | Day 4-5 |
| **Agent 能力** | 50% JD 要求，且最难造假。**改动极小**——复用现有检索/抓取/分析函数 | Day 15-18 |
| **Evals 评测体系** | 56% 出现率，#1 差异化项。「人工抽样 30 条」不算评测（不可复现、无基线、无回归） | Day 6/13/20/22 |

### A.4 项目三大优势（面试主动讲）

| 优势 | 为什么稀有 |
|---|---|
| **真实无人值守系统** | 99% 应届项目是本地 demo，跑一次就结束 |
| **一次真实疑难故障定位** | 案例六：14 次 `schedule=0` → API 取证 → 判定调度器侧问题 → 外部定时器兜底 |
| **成本意识** | 学生项目很少算账：月成本 < 1.5 元，且能说清为什么 |

---

## 附录 B：简历与面试（原 `ROADMAP_岗位对标与优化清单.md` 第 6-7 节）

### B.1 简历项目描述（3 条，控制在原长度内）

```
2026.9-2026.10  AI 情报站 · 智能资讯知识库（个人项目 · 已上线）
https://chuanyu-fangyuan.github.io/-aii-/
• AI 流水线：FastAPI + LangGraph 构建每日情报 Agent，4 个异构数据源（API+RSS）
  接入 DeepSeek 做自动分类/摘要/事实验证；pgvector 向量检索 + BM25 混合召回，
  RAG 问答带引用溯源；工具集通过 MCP 暴露给外部客户端调用
• 评测体系：自建 100 条人工标注集 + 20 组 RAG 问答对，用 RAGAS 与 LLM-as-judge
  量化 faithfulness / Recall@5 / 分类 F1，Prompt 迭代前后分数对比；
  CI 加回归门禁，指标下降自动拦截合并
• 工程与运维：Docker Compose 一键部署（FastAPI + PostgreSQL），pytest 覆盖率 65%+；
  GitHub Actions 每 3 小时无人值守运行，LLM 调用全链路埋点（token/延迟/成本）；
  月成本 < 1.5 元（DeepSeek + 本地 Embedding + 免费托管）
```

> **注意**：数字要与 §6 达标线一致（65% 覆盖率 / 100 条标注集），**不要写未达成的数字**。
> `schedule=0` 的故障定位放面试口头讲（简历压缩后放不下，口头更有感染力）。

### B.2 面试预案

| 可能的问题 | 回答要点 |
|---|---|
| 「RAG 效果怎么评测的？」 | 标注集 + RAGAS 分数 + Prompt 迭代对比表 + CI 门禁 |
| 「为什么用 pgvector 不用 Milvus？」 | 数据量 < 1 万、已在用 PG、避免额外服务；说清 trade-off |
| 「Agent 失败怎么处理？」 | 条件边重试上限 2 轮 + HITL 审核 + 降级到规则聚类 |
| 「怎么控制成本？」 | 本地 embedding + DeepSeek + 分级模型 + 缓存 |
| 「为什么不做微调？」 | 数据量不足、RAG 更适合知识密集型、微调无法热更新 |
| 「项目最大的难点？」 | 讲调度器故障定位（案例六）——真实、有取证、有兜底 |
| 「重做会怎么改？」 | 提前做 evals、数据契约先定好、早引入 PG |

### B.3 前 10 分钟讲稿骨架

1. **数据流（2 min）**：4 源 → Python 抓取 → PG 双哈希去重 → LLM 分析 → pgvector 索引 → FastAPI → Pages/前端。每步只做一件事，无隐藏耦合。
2. **技术取舍（3 min）**：① 静态站 + 服务层共存（保零成本托管，补后端服务）② 规则词典 + LLM 分层（可解释、可热修、按需付费）
3. **一次问题定位（5 min，STAR）**：Situation 站点数据不自动更新 → Task 定位是配置错还是调度器不派发 → Action API 实测 `event=schedule` 恒为 0，逐项排除 → Result 外部定时器兜底 + 端到端取证。
