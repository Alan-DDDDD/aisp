# Hugging Face Spaces (Docker SDK) deployment
# Build context: repo root
# Listens on $PORT (HF Spaces sets 7860 by default)

FROM python:3.11-slim

# OS deps for chromadb (sqlite3, libgomp for onnxruntime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only PyTorch 先裝（避免 pip 把 CUDA 版的 torch 拉進來，省 ~1.8GB image）。
# sentence-transformers 之後看到 torch 已存在就不會再 resolve 它。
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch

# Install python deps（layer cache）
COPY backend/pyproject.toml backend/README.md* ./backend/
RUN pip install --no-cache-dir -e ./backend

# Pre-download embedding 與 reranker 模型到 image 內，避免每次冷啟動花時間抓 model。
# HF Spaces free tier 沒 persistent disk，每次重啟都會用 image 內的快取。
ARG EMBEDDING_MODEL=BAAI/bge-m3
ARG RERANK_MODEL=BAAI/bge-reranker-v2-m3
ENV SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence-transformers \
    HF_HOME=/app/.cache/huggingface
RUN mkdir -p /app/.cache && chmod -R 777 /app/.cache
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('${RERANK_MODEL}')"

# 應用碼 + seed workspaces
COPY backend/app /app/backend/app
COPY workspaces /app/workspaces

# 容器內讀寫資料路徑（HF Spaces free 重啟會還原 — 這是預期行為）
ENV PYTHONUNBUFFERED=1 \
    MODE=cloud \
    LLM_PROVIDER=mock \
    SQLITE_PATH=/app/data/aisp.db \
    CHROMA_PERSIST_DIR=/app/data/chroma \
    WORKSPACES_DIR=/app/workspaces \
    SEED_ON_BOOT=true \
    LOG_LEVEL=INFO \
    EMBEDDING_MODEL=BAAI/bge-m3 \
    RERANK_MODEL=BAAI/bge-reranker-v2-m3 \
    PORT=7860

RUN mkdir -p /app/data && chmod 777 /app/data

WORKDIR /app/backend
EXPOSE 7860

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
