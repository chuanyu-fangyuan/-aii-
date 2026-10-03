#!/usr/bin/env bash
# AI 情报站 · 魔搭创空间启动脚本
#
# 为什么要有这个脚本（而不是直接 CMD uvicorn）：
#   采集流水线在 GitHub Actions 每 3 小时跑一次、把最新 data/news.db 提交回仓库。
#   而镜像只在「重新构建」时才带上新库 —— 启动时不拉一次，
#   演示站展示的永远是「构建那一刻」的旧数据。
#
# 策略：启动时先从 CDN 拉 main 分支的最新 news.db 覆盖内置快照；
#       拉不到（网络受限）就退回镜像内置的那份，保证服务一定起得来。
set -u

DB_PATH="/app/data/news.db"
# 默认用 jsDelivr 的 GitHub 加速节点（国内可达性比 raw.githubusercontent.com 好）。
# 要换源时设 NEWS_DB_URL 即可，不必改镜像。
DB_URL="${NEWS_DB_URL:-https://cdn.jsdelivr.net/gh/chuanyu-fangyuan/-aii-@main/data/news.db}"
# 魔搭容器出口到 jsDelivr 实测只有约 70KB/s（2.6MB 的库要 ~40 秒），
# 默认 20 秒必然超时退回旧快照；放宽到 120 秒。拉不到仍会退回内置快照，不影响启动。
TIMEOUT="${NEWS_DB_TIMEOUT:-120}"

mkdir -p "$(dirname "$DB_PATH")"

echo "[start] 拉取最新 news.db <- $DB_URL"
if curl -fsSL --max-time "$TIMEOUT" -o "${DB_PATH}.tmp" "$DB_URL"; then
  mv "${DB_PATH}.tmp" "$DB_PATH"
  echo "[start] 已更新为最新 news.db"
else
  rm -f "${DB_PATH}.tmp"
  echo "[start] 拉取失败，使用镜像内置 news.db（构建时快照）"
fi

# exec 让 uvicorn 成为主进程，魔搭的停止信号才能正常传达
exec uvicorn api.main:app --host 0.0.0.0 --port 7860
