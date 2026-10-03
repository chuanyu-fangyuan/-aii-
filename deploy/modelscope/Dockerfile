# ============================================================
# AI 情报站 · 魔搭创空间（ModelScope Studio）镜像
#
# 与仓库根 Dockerfile 的区别（为什么单独一份）：
#   - 端口固定 7860 —— 魔搭创空间只对外暴露这个端口
#   - 构建机在国内（魔搭 = 阿里云）：pip 主源走清华镜像，比官方 PyPI 快且稳
#   - CMD 改成 start.sh：启动时先拉一次最新 news.db，再启动 API
#
# 数据策略（关键）：
#   采集流水线在 GitHub Actions 跑、把最新 data/news.db 提交回仓库。
#   本镜像构建时会把仓库当前的 news.db 一起打包（兜底快照，保证能启动）；
#   容器启动时再从 CDN 拉 main 分支的最新版覆盖 —— 拉到用最新的，
#   拉不到退回镜像内置的。这样「数据尽量新」和「服务一定起得来」两头都占。
# ============================================================

ARG PYTHON_IMAGE=python:3.12-slim

# ---------- 阶段 1：builder ----------
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# 构建机在国内：pip 主源用清华镜像；torch 不在清华源的默认同步里，
# 用 --extra-index-url 兜底到 PyTorch 官方 CPU 轮子（避免拉 2GB 的 CUDA 版）。
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip -i "$PIP_INDEX_URL" \
 && /opt/venv/bin/pip install -i "$PIP_INDEX_URL" --extra-index-url "$TORCH_INDEX_URL" -r requirements.txt

# 预下载嵌入模型（BAAI/bge-small-zh-v1.5，约 95MB），走国内镜像站，
# 否则容器第一次检索才联网下载，演示时首问会卡十几秒。
ARG HF_ENDPOINT=https://hf-mirror.com
ENV HF_ENDPOINT=${HF_ENDPOINT} \
    HF_HOME=/opt/hf
RUN /opt/venv/bin/python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('BAAI/bge-small-zh-v1.5'); \
print('[build] embedding model cached')"

# ---------- 阶段 2：runtime ----------
FROM ${PYTHON_IMAGE} AS runtime

ARG HF_ENDPOINT=https://hf-mirror.com
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_ENDPOINT=${HF_ENDPOINT} \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    PATH="/opt/venv/bin:$PATH"

# curl：start.sh 用它拉最新 news.db
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system app \
 && useradd --system --gid app --create-home app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/hf /opt/hf
COPY --chown=app:app . .

# start.sh 防 CRLF（Windows 编辑过的 .sh 在 Linux 会执行失败）+ 赋可执行权限
RUN mkdir -p /app/data \
 && chown -R app:app /app/data \
 && sed -i 's/\r$//' /app/deploy/modelscope/start.sh \
 && chmod +x /app/deploy/modelscope/start.sh

USER app

EXPOSE 7860

# start-period 给足：冷启动要加载嵌入模型 + 拉一次 news.db
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "\
import json, urllib.request; \
d = json.load(urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=3)); \
raise SystemExit(0 if d.get('status') == 'ok' else 1)"

CMD ["bash", "deploy/modelscope/start.sh"]
