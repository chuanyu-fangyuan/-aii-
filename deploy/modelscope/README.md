---
domain:
- nlp
tags:
- RAG
- FastAPI
- AI资讯
- 检索问答
license: MIT
---

# AI 情报站 · API 服务

这是 **[AI 情报站](https://github.com/chuanyu-fangyuan/-aii-)** 的后端 API，给 GitHub Pages 上的静态站点提供 AI 问答能力。

- 演示站（静态前端）：https://chuanyu-fangyuan.github.io/-aii-/
- 本创空间：只跑 FastAPI 后端（`/ask` 检索问答、`/api/stats` 成本看板、`/reviews` 人工审核）

## 部署说明（Docker 类型）

本空间是 **Docker** 类型，创空间构建根目录的 `Dockerfile`，服务监听 `0.0.0.0:7860`。

- **硬件**：免费 CPU（`platform/2v-cpu-16g-mem`，2 vCPU + 16GB，够装 torch + 中文嵌入模型）
- **环境变量**：在「设置 → 环境变量」里配 `DEEPSEEK_API_KEY`（DeepSeek 密钥，问答/摘要要用）
- **端口**：7860（创空间固定）

## 为什么部署在魔搭创空间

它**不需要绑信用卡**，免费 CPU 给 2 vCPU / 16GB 内存、且**国内直连**（演示时面试官不用翻墙）——
本服务要加载 torch + 中文嵌入模型（约 1GB 内存），多数海外免费层的 512MB 装不下，
Hugging Face 新账号建 Docker Space 又要绑卡。

## 接口

| 端点 | 说明 |
|---|---|
| `GET /health` | 健康检查（含库内新闻条数） |
| `POST /ask` | RAG 问答（公开，带每日配额） |
| `GET /api/stats` | 成本看板（token / 费用 / 配额使用） |
| `GET /docs` | OpenAPI 交互文档 |

## 公开演示的配额

`/ask` 对公网开放，因此带双闸门保护 API 额度：**单 IP 每日 5 次 + 全局每日 100 次**，
配额在检索之前判定（拒绝时不加载模型、不调 LLM，一分钱不花）。配额用尽返回 429 与友好提示。

## 已知边界

- 嵌入模型在**构建期预下载**进镜像，首次问答不会因为下载模型而卡住。
- 新闻库 `data/news.db`：构建时打包一份快照，**启动时再从 CDN 拉仓库最新版**覆盖。
- 存储是临时的：重启后内存里的配额计数清零（不影响新闻数据，数据来自仓库 `data/news.db`）。
