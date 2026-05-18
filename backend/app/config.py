from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mode: str = "demo"
    llm_provider: str = "mock"
    llm_model: str = ""  # 空字串=用 provider 預設
    llm_ssl_verify: bool = True  # 企業網路有 self-signed CA 時可設 False

    gemini_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    sqlite_path: str = "./data/app.db"
    chroma_persist_dir: str = "./data/chroma"
    workspaces_dir: str = "./workspaces"

    # Embedding 模型：
    # - "chroma-default"：ChromaDB 內建 ONNX MiniLM-L6-v2（384 維，英文導向，輕）
    # - sentence-transformers 任何 HF model id（如 "BAAI/bge-m3" 多語言、1024 維、重）
    embedding_model: str = "BAAI/bge-m3"

    seed_on_boot: bool = True
    log_level: str = "INFO"

    # Composer：低於此分數的 retrieval doc 視為與問題無關，不傳給 LLM、不放 citation
    composer_min_doc_score: float = 0.45

    # Retrieval pipeline
    # - "dense"：只走 ChromaDB embedding cosine
    # - "bm25"：只走 BM25 關鍵字
    # - "hybrid"（預設）：兩者並跑、用 RRF 融合
    retrieval_mode: str = "hybrid"
    retrieval_top_k_dense: int = 20      # 融合前 dense 候選數
    retrieval_top_k_bm25: int = 20       # 融合前 BM25 候選數
    hybrid_rrf_k: int = 60               # RRF 標準 k 值
    bm25_only_default_score: float = 0.5  # BM25-only hit 沒有 cosine 時的 placeholder

    # Reranker：留空 = 不啟用；典型值 "BAAI/bge-reranker-v2-m3"
    # HF Spaces 免費版資源緊，預設關閉；本機跑 eval 可開
    rerank_model: str = ""
    rerank_top_n: int = 5                # 重排後保留幾筆

    # Groq 429 / 5xx 退避重試
    groq_max_attempts: int = 3           # 含首次共 3 次
    groq_max_retry_delay_s: float = 15.0  # 單次 sleep 上限，避免卡太久

    # ── Phase 6 — Gap Detection（PLAN §22.4）─────────────────────────────
    # Retrieval similarity shortcut 閾值
    gap_sim_high: float = 0.85          # >= 此值：跳過 judge 直接 USE
    gap_sim_low: float = 0.40           # <= 此值：跳過 judge 直接 GAP
    # Judge LLM 輸出的 confidence 解讀
    gap_conf_high: float = 0.85         # >= 此值：USE / COMPOSE / GAP 直接採信
    gap_conf_low: float = 0.40          # <= 此值：直接採信（多半是 GAP）
    # 灰色區（gap_conf_low < c < gap_conf_high）會送 HumanReviewInterface

    # Phase A 兩個角色的預設 model（可被 .env 覆寫）
    gap_planner_model: str = "llama-3.3-70b-versatile"
    gap_judge_model: str = "llama-3.1-8b-instant"

    # Retrieval
    gap_retrieval_top_k: int = 5

    # ── Phase 6 — Tool Synthesis（PLAN §22.5）───────────────────────────
    # 失敗修正迴圈最大 round 數（PLAN §22.5.6）
    synth_max_attempts: int = 3
    # sandbox 單次 pytest 執行 timeout（秒）
    synth_sandbox_timeout_s: int = 60
    # E2B API key（空字串 → 走 LocalSubprocessRunner）
    e2b_api_key: str = ""

    # ── Phase 6 — Telegram HITL（PLAN §22.4.4 / §22.5.7）─────────────────
    # 來自 BotFather 的 token（空 → Telegram 整套停用）
    tg_bot_token: str = ""
    # demo 階段固定推一個 chat_id（你自己）；多人版才做 mapping
    tg_chat_id: str = ""
    # polling（無公網 URL 也能用）/ webhook（PROD 公開 https URL）
    tg_mode: str = "polling"
    # 灰色區詢問人類的等待 timeout（秒，超過視為 fallback）
    tg_review_timeout_s: int = 600

    # Generated tools 的程式碼存放目錄（相對 backend 啟動 cwd）
    generated_tools_dir: str = "../workspaces/generated_tools"

    # ── TA3 — Chat auto-synthesis ──────────────────────────────────────
    # 從 chat 觸發合成時，合成成功且 side_effect=read_only 是否自動 approve。
    # True：demo 友善（user 一次對話內看到結果，合成 + 註冊 + 呼叫一氣呵成）
    # False：所有 generated tool 一律走人類審核（prod 預設）
    chat_auto_approve_read_only: bool = True
    # 從 chat 觸發合成時，第一個 GAP 才做合成；多 gap_step 留將來
    chat_synthesize_first_gap_only: bool = True

    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def sqlite_url(self) -> str:
        path = Path(self.sqlite_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{path}"


settings = Settings()
