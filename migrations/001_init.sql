-- 001_init.sql: AI 知识库升级 schema
-- 适用于 PostgreSQL 16 + pgvector
-- 用法: psql -f migrations/001_init.sql

-- ============================================================
-- 1. 启用 pgvector 扩展
-- ============================================================
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- 2. news 表（完整版，含 AI 分析字段）
-- ============================================================
CREATE TABLE IF NOT EXISTS news (
    id SERIAL PRIMARY KEY,
    url_hash TEXT NOT NULL UNIQUE,
    title_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    summary TEXT DEFAULT '',
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    published_unknown BOOLEAN NOT NULL DEFAULT FALSE,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- AI 分析字段（Week 1 新增）
    ai_category TEXT,                    -- 分类：模型/应用/芯片硬件/开源/融资创业/政策监管/研究突破/其他
    ai_summary_zh TEXT,                  -- 中文摘要（50-100 字）
    importance SMALLINT NOT NULL DEFAULT 0,  -- 重要性 1-5
    verification TEXT,                   -- 可信度：confirmed / unverified / disputed / pending
    verification_note TEXT,              -- 验证说明
    entities_json TEXT DEFAULT '[]',     -- 提取的实体列表 JSON
    ai_status TEXT NOT NULL DEFAULT 'pending',  -- pending / analyzing / done / error

    -- 向量字段（Week 2 新增）
    embedding vector(512),              -- bge-small-zh-v1.5 输出 512 维

    UNIQUE(title_hash, source_id)
);

-- ============================================================
-- 3. AI 分析错误日志
-- ============================================================
CREATE TABLE IF NOT EXISTS ai_errors (
    id SERIAL PRIMARY KEY,
    news_id INTEGER REFERENCES news(id) ON DELETE CASCADE,
    error_type TEXT NOT NULL,            -- timeout / json_parse / api_error / rate_limit
    error_message TEXT,
    retry_count SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 4. LLM 调用追踪（可观测性）
-- ============================================================
CREATE TABLE IF NOT EXISTS llm_traces (
    id SERIAL PRIMARY KEY,
    model TEXT NOT NULL,                 -- deepseek-v3 / bge-small-zh-v1.5
    purpose TEXT NOT NULL,               -- analyze / rag / eval / embedding
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    cost_yuan NUMERIC(10, 6) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok',   -- ok / error
    news_id INTEGER REFERENCES news(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 5. 待审核队列（HITL）
-- ============================================================
CREATE TABLE IF NOT EXISTS pending_review (
    id SERIAL PRIMARY KEY,
    news_id INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE,
    review_type TEXT NOT NULL,           -- category / verification / summary
    original_value TEXT,
    suggested_value TEXT,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending / approved / rejected
    reviewer_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ
);

-- ============================================================
-- 6. Agent 运行记录（Week 3）
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_runs (
    id SERIAL PRIMARY KEY,
    task_description TEXT NOT NULL,
    state_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'running',  -- running / completed / failed
    tool_calls INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- ============================================================
-- 7. 索引
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_news_ai_status ON news(ai_status);
CREATE INDEX IF NOT EXISTS idx_news_source_id ON news(source_id);
CREATE INDEX IF NOT EXISTS idx_news_published_at ON news(COALESCE(published_at, fetched_at) DESC);
CREATE INDEX IF NOT EXISTS idx_news_ai_category ON news(ai_category);
CREATE INDEX IF NOT EXISTS idx_llm_traces_purpose ON llm_traces(purpose, created_at);
CREATE INDEX IF NOT EXISTS idx_pending_review_status ON pending_review(status);

-- 向量索引（ivfflat，需要足够数据后重建为 hnsw）
-- 注意：embedding 列有值后再创建索引，否则 ivfflat 需要至少 rows_per_probe * 10 条数据
-- CREATE INDEX IF NOT EXISTS idx_news_embedding ON news USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- ============================================================
-- 8. update_runs 表（沿用，适配 PG 语法）
-- ============================================================
CREATE TABLE IF NOT EXISTS update_runs (
    id SERIAL PRIMARY KEY,
    run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_id TEXT NOT NULL,
    status TEXT NOT NULL,
    fetched INTEGER DEFAULT 0,
    inserted INTEGER DEFAULT 0,
    message TEXT DEFAULT ''
);
