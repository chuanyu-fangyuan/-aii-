# ============================================================
# AI 情报站 · API 镜像（多阶段构建）
#
#   builder：装依赖 + 预下载嵌入模型，编译器与 pip 缓存不进最终镜像
#   runtime：只带 venv / 模型 / 代码，非 root 运行
#
# 边界说明（为什么镜像里只有 API）：
#   - 静态站（web/）由 GitHub Pages 托管，不需要容器
#   - 采集 + 分析流水线由 GitHub Actions 跑（见 .github/workflows/update.yml），
#     容器只读它产出的 data/news.db，不承担写库职责
#
# 构建：
#   docker build -t ai-daily-brief-api .
# 运行：
#   docker run -p 8000:8000 -v "$PWD/data:/app/data" ai-daily-brief-api
# 或直接用编排：docker compose up --build
# ============================================================

# 基础镜像可覆盖：Docker Hub 直连受限时用镜像源，例如
#   docker compose build --build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
ARG PYTHON_IMAGE=python:3.12-slim

# ---------- 阶段 1：builder ----------
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# 备用：某些包在 slim 下无预编译 wheel 时需要本地编译
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# 依赖装进独立 venv，整体拷到 runtime，省掉在 runtime 重跑 pip
# TORCH_INDEX_URL：PyPI 在 Linux 上的 torch 默认带 CUDA 运行时（镜像 +2GB），
# 本容器不用 GPU，改从 CPU 源取；网络受限时可覆盖为空串退回官方源
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && if [ -n "$TORCH_INDEX_URL" ]; then \
        /opt/venv/bin/pip install --extra-index-url "$TORCH_INDEX_URL" -r requirements.txt; \
    else \
        /opt/venv/bin/pip install -r requirements.txt; \
    fi

# 预下载嵌入模型（BAAI/bge-small-zh-v1.5，约 95MB）：
# 否则容器第一次检索才联网下载，演示时表现为「首个问题卡住十几秒」。
# 国内直连 huggingface.co 不通，用镜像站（与 retrieval.py 的默认行为一致）。
ENV HF_ENDPOINT=https://hf-mirror.com \
    HF_HOME=/opt/hf
RUN /opt/venv/bin/python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('BAAI/bge-small-zh-v1.5'); \
print('[build] embedding model cached')"

# ---------- 阶段 2：runtime ----------
FROM ${PYTHON_IMAGE} AS runtime

# HF_HUB_OFFLINE=1：模型已在构建期落盘，运行期不必再去 huggingface 做版本检查。
# 不设这一项时，离线/弱网环境下每次加载模型都会先尝试 HEAD 请求、超时后才回落本地缓存，
# 日志里还会留下 name resolution 报错，看着像故障。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_ENDPOINT=https://hf-mirror.com \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    PATH="/opt/venv/bin:$PATH"

# 非 root 运行：容器内进程只有读代码 + 写 /app/data 的权限
RUN groupadd --system app \
 && useradd --system --gid app --create-home app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/hf /opt/hf
COPY --chown=app:app . .

RUN mkdir -p /app/data && chown -R app:app /app/data

USER app

EXPOSE 8000

# 探活到 /health 的业务状态，不只看端口通不通
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "\
import json, urllib.request; \
d = json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)); \
raise SystemExit(0 if d.get('status') == 'ok' else 1)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
