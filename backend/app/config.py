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
