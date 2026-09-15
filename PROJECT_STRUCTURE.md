# 项目结构说明 — AI 情报站（AI Daily Brief）

聚合多个公开信息源的 AI 资讯站：Python 脚本每日采集、去重后存入 SQLite 并导出静态 `data.json`，原生前端渲染资讯流与 D3 关系图谱，GitHub Actions 定时更新并部署到 GitHub Pages。**无后端运行时，静态站点零成本托管。**

## 目录结构

```
-aii--main/
├── .github/
│   └── workflows/
│       └── update.yml          # GitHub Actions：每日采集 → 提交数据 → 部署 Pages
├── data/
│   └── news.db                 # SQLite 数据库（news、update_runs 两张表，保留全部历史）
├── web/                        # 静态站点根目录（部署时整个目录发布）
│   ├── vendor/
│   │   └── d3.v7.min.js        # D3.js v7 本地打包，图谱不依赖 CDN，可离线运行
│   ├── index.html              # 页面骨架：顶栏 / 工具栏 / 资讯流 / 图谱 / 抽屉 / 页脚
│   ├── styles.css              # 全站样式（响应式，含 390px 移动端适配）
│   ├── app.js                  # 前端主逻辑：状态管理、筛选、资讯流渲染、详情抽屉
│   ├── graph.js                # D3 力导向关系图谱：拖拽 / 缩放 / 高亮 / 点击定位
│   └── data.json               # fetch.py 导出的前端数据（meta / news / graph / digest）
├── fetch.py                    # 采集主脚本：抓取 → 清洗去重 → 入库 → 导出 JSON
├── requirements.txt            # Python 依赖：feedparser>=6.0
├── 启动预览.bat                 # Windows 一键本地预览（python http.server，端口 8765）
├── .gitignore                  # 忽略 __pycache__、*.pyc、截图、.DS_Store
└── README.md                   # 项目说明、运行部署、验证记录与已知限制
```

## 整体架构与数据流

```
Hacker News API ─┐
TechCrunch RSS  ─┤                              ┌──────────────┐
The Verge RSS   ─┼─► fetch.py（抓取/清洗/去重）─►│ data/news.db  │
arXiv cs.AI RSS ─┘        │                     └──────┬───────┘
                          │                            │ 最近 30 天
                          │                            ▼
                          │                     web/data.json
                          │                     ┌──────┴───────┐
                          └────────────────────►│  app.js      │ 资讯流 / 搜索筛选 / 今日速读
                                                │  graph.js    │ D3 关系图谱
                                                │  index.html  │
                                                └──────────────┘
                          GitHub Actions cron 每日触发 fetch.py 并重新部署
```

- **存储口径**：UTC ISO8601；**展示口径**：Asia/Shanghai（北京时间）。
- 发布时间与采集时间分离存储；发布时间缺失时标注「发布时间未知」，不以采集时间冒充。
- 导出窗口为最近 30 天，数据库保留全部历史。

## fetch.py 模块组成

单文件脚本（约 470 行），按职责分为 6 段：

| 分段 | 关键内容 |
|---|---|
| 配置 | `SOURCES`（4 个信息源）、`DB_PATH`、`EXPORT_PATH`、`EXPORT_WINDOW_DAYS=30` |
| 去重工具 | `canonical_url()`（去跟踪参数 / 统一 host）、`url_hash()`、`title_hash()`（标题归一化）双哈希去重 |
| HTTP / 解析 | `http_get()`；`fetch_hn_api()`（Algolia API）、`fetch_rss()`（feedparser，含 arXiv 模板清洗、摘要截断 200 字） |
| 存储 | `init_db()` 建表；`upsert_items()` 用 `INSERT OR IGNORE` 保证幂等 |
| 关键词 / 图谱 | `ENTITY_LEXICON`（实体词典）、`STOPWORDS`、`extract_keywords()`（词典匹配 + 标题高频词）、`build_graph()`（新闻-关键词二部图，只保留连接 ≥2 条新闻的关键词） |
| 导出 / 主流程 | `build_digest()`（今日速读，规则聚类非 LLM）、`export_json()`、`run()`；CLI 参数 `--only <源id>`、`--fail-source <源id>`（容错测试） |

**容错策略**：单源失败被捕获并记入 `update_runs`（`ok / failed / no_new` 三态），不影响其他源与已有数据；「无新增」与「抓取失败」明确区分。

## 数据库结构（data/news.db）

**news 表 — 资讯明细**

| 字段 | 说明 |
|---|---|
| id | 主键自增 |
| url_hash | 规范化 URL 的 SHA256 前 16 位，UNIQUE |
| title_hash | 标题归一化哈希 |
| title / url / summary | 标题、原文链接、摘要 |
| source_id / source_name | 来源标识与展示名（hackernews / techcrunch / theverge / arxiv） |
| published_at | 原始发布时间（UTC ISO），可为 NULL |
| published_unknown | 发布时间缺失标记（0/1） |
| fetched_at | 采集时间（UTC ISO） |
| 约束 | `UNIQUE(url_hash)`、`UNIQUE(title_hash, source_id)` |

**update_runs 表 — 每次采集每来源的状态流水**：`run_at`、`source_id`、`status`、`fetched`、`inserted`、`message`。

## web/data.json 数据结构

```json
{
  "meta":   { "generated_at", "timezone_display", "total", "sources": [每源最新状态] },
  "news":   [ { id, title, url, summary, source_id, source_name,
                published_at, published_unknown, fetched_at } ],   // 最近 30 天
  "graph":  { "nodes": [ {type:"news"| "keyword", ...} ],
              "links": [ {source, target} ] },
  "digest": { "date", "total_today", "note", "topics": [{keyword, count, news_ids}] }
}
```

## 前端文件职责

| 文件 | 职责 |
|---|---|
| `index.html` | 顶栏（Logo、资讯流/图谱 Tab、更新状态徽标）；工具栏（今天/近7天/全部、搜索框、来源 chips、清除条件）；资讯流视图（今日速读卡片 + 列表 + 空态）；图谱视图（SVG + 图例）；详情抽屉；页脚来源状态；加载/错误遮罩 |
| `app.js` | IIFE 单例 `state`（view / range / query / source / data）；时间换算与今天/近 7 天判定；防抖搜索与多维过滤；`renderDigest()`、`renderFeed()`、来源 chips、采集状态渲染；新闻/关键词两种详情抽屉；视图切换与事件绑定。外部内容一律 `textContent` 渲染防 XSS |
| `graph.js` | D3 力导向图：新闻节点（按新旧度调透明度）+ 关键词节点（按关联数放大）；拖拽、滚轮缩放、悬停高亮关联节点、`focusKeyword()` 供资讯卡片关键词一键跳转定位 |
| `styles.css` | 全站视觉与响应式布局；`min-height:100vh` 修复页脚重叠，`[hidden]{display:none!important}` 修复 flex 覆盖 |

## CI/CD（.github/workflows/update.yml）

- **触发**：`cron "17 0 * * *"`（北京 08:17）、`workflow_dispatch` 手动触发、push 到 `main`。
- **update 任务**：checkout → Python 3.12 → 安装依赖 → `python fetch.py` → 自动提交 `data/news.db`、`web/data.json` → 上传 `web/` 为 Pages 产物。
- **deploy 任务**：依赖 update，调用 `actions/deploy-pages` 发布。
- 并发组 `pages`，`cancel-in-progress: true`。

## 本地运行

```bash
pip install -r requirements.txt
python fetch.py                       # 采集 + 去重 + 导出 web/data.json
cd web && python -m http.server 8080  # 打开 http://localhost:8080
```

Windows 也可直接双击 `启动预览.bat`（绑定 127.0.0.1:8765 并自动开浏览器）。
