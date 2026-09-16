# AI 情报站（AI Daily Brief）

让关注 AI 的人，在几分钟内了解近期值得关注的动态。
聚合多个独立信息源的 AI 资讯，**每日自动更新**，支持关键词搜索、来源筛选、时间范围切换，以及 Obsidian 风格的**关系图谱**浏览。

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
| Hacker News | Algolia 官方 API（`hn.algolia.com`，AI/LLM 关键词） |
| TechCrunch AI | 公开 RSS |
| The Verge AI | 公开 RSS |
| arXiv cs.AI | 公开 RSS |

均为公开、信息源允许的获取方式，不绕登录 / 付费墙 / 反爬。

## 本地运行

```bash
pip install -r requirements.txt
python fetch.py          # 采集 + 去重 + 导出 web/data.json
cd web && python -m http.server 8080
# 打开 http://localhost:8080
```

## 部署

静态站点，站点根目录为 `web/`。本仓库使用 **GitHub Actions 部署到 GitHub Pages**：

1. 仓库 Settings → Pages → Source 选择 **GitHub Actions**
2. push 到 `main` 或在 Actions 页手动运行「每日数据更新与部署」工作流
3. 工作流先运行 `fetch.py` 更新数据、提交 `data.json`，再把 `web/` 发布到 Pages

演示地址：`https://<用户名>.github.io/<仓库名>/`（首次部署完成后可访问）。
定时触发由外部服务 **cron-job.org**（免费）调用 GitHub 官方 `workflow_dispatch` REST API 完成，cron `20 */3 * * *`（北京时间 02:20 / 05:20 / 08:20 / 11:20 / 14:20 / 17:20 / 20:20 / 23:20，全部避开整点高负载时段）。仓库内的 `workflow_dispatch` 入口直接复用，无需部署任何 webhook 服务。GitHub Actions 工作流定义见 `.github/workflows/update.yml`。触发时机以 **cron-job.org 触发记录 + Actions 页面的运行记录**（事件列显示 `workflow_dispatch`）共同验证为准，详见「案例四」「案例六」。

## 技术选型理由

- **Python + feedparser 采集，SQLite 存储**：URL 规范化哈希 + 标题哈希双去重，`INSERT OR IGNORE` 天然幂等——重复导入同一输入不产生重复记录。
- **导出静态 `data.json` + 原生前端**：零后端运行时成本，任何静态托管可复现；前端无框架，评审在干净环境只需 Python 即可跑通全链路。
- **D3.js 本地打包**（`web/vendor/d3.v7.min.js`）：图谱不依赖 CDN，离线可运行。
- **外部定时器（cron-job.org）+ GitHub Actions**：不依赖个人电脑开机；GitHub Actions 处理采集/部署（免运维、artifact 上发），cron-job.org 处理调度（不依赖 GitHub 自身 `schedule` 事件，规避新仓库偶发不派发的问题）；详细原因与验证见「案例四」「案例六」。

## 时间口径

- 存储：UTC ISO8601；展示：Asia/Shanghai。
- 「今天」= 北京时间当日 00:00 起；「近 7 天」= 当前时刻向前 7×24h。
- 发布时间缺失时标注「发布时间未知」并展示采集时间，**不以采集时间冒充发布时间**。

## 安全

- 无密钥、无第三方账号，前端无敏感信息。
- 外部内容（标题/摘要）一律以 `textContent` 渲染，不使用 `innerHTML`，防 XSS。
- 外链均带 `rel="noopener noreferrer"`。

## 验证记录

| 场景 | 方法 | 结果 |
|---|---|---|
| 真实数据获取 | `python fetch.py` | ✅ 4 源成功；修复 HN 查询后重采，入库 99 条且当日数据新鲜 |
| 重复导入幂等 | 连续运行两次 | ✅ 第二次全部 `inserted=0` |
| 单源失败容错 | `python fetch.py --fail-source techcrunch` | ✅ 该源标记 `failed`，其他源正常，旧数据保留 |
| 定时自动更新 | 外部定时器 → `workflow_dispatch` | ✅ **已通过**（详见「案例六」）：cron-job.org 每 3 小时调用 GitHub API 派发 `workflow_dispatch`，北京 12:20 真实触发 run #14 success，线上 `data.json` 的 `generated_at` 即时刷新到 12:20:36；新闻总数 317 → 331，`hackernews` 抓取 40 条新增 2 条（其余来源 `no_new`，与「抓取失败」正确区分）。同时 GitHub 原生 `schedule` 事件在 14 次运行中**始终为 0**——配置无错，问题在调度层，详「案例四」。 |
| 并发 push 竞态 | 查看失败运行 34927770343 的步骤日志 | ✅ 已定位并修复：采集成功但「提交更新结果」被拒（non-fast-forward），导致整次运行失败。已改为「每次尝试先回到远端最新 → 重新采集 → 推送」，最多重试 3 次，见「案例五」 |

（缺失日期、长标题、搜索无结果等界面状态已在前端实现并人工检查。）

## 已知限制

- 关键词提取为规则 + 实体词典（未调 LLM，零成本），偶有噪声词；词典在 `fetch.py` 的 `ENTITY_LEXICON` 可扩充。
- 图谱按「新闻-关键词」建边，不做跨媒体同一事件的语义聚合（题目注明非必做）。
- 导出窗口为最近 30 天（数据库保留全部历史）。

## 成本

开发与运行均未使用付费服务：信息源为公开 RSS/API，托管用 GitHub Pages 免额度，调度用 cron-job.org 免费版（自定义 header、POST + body 全部支持），未调用付费大模型。

## 开发说明

- 实际投入时间：约 3.45 小时（提交时如实填写）
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

### 验证记录补充（界面层）

- 搜索无结果 → 空态提示 + 一键清除条件（截图留存）
- 「今天 + 某来源」为空 → 明确提示时区差异、不代表抓取失败，并提供「查看该来源近 7 天」
- 缺发布时间 → 注入明确标注 `[测试]` 的记录验证「发布时间未知 · 采集于…」警示样式，验证后删除，未混入真实数据
- 长标题（122 字符）→ 两行截断正常
- 移动端 390px 视口 → 资讯流 / 图谱 / 抽屉均可用（截图留存）

