---
title: Aisp
emoji: 👁
colorFrom: green
colorTo: yellow
sdk: docker
pinned: false
short_description: Enterprise AI Agent platform with YAML workflows
---

# AISP — Enterprise AI Agent Platform

> **Multi-Department Agentic Workspace.**
> 每個部門用 YAML 設定自己的 AI Agent 流程與知識庫，共用同一份後端 runtime。

🔗 **Live demo (frontend)**: https://aisp-855.pages.dev
🔧 **Backend runtime (HF Space)**: https://alan-ddddd-aisp.hf.space
💻 **Source code**: https://github.com/Alan-DDDDD/aisp

---

## 專案簡介

AISP 是一個多部門 AI Agent 平台。將 **Knowledge、Agent、Workflow** 抽象成獨立的 domain object，讓不同部門 (workspace) 共用同一份 runtime，但因為設定不同而呈現完全不同的對話行為。

專案內建 4 個示範部門：**客服、HR、IT Helpdesk、法務**。新增一個部門只需要建立 3 個檔案（`workspace.json` + `workflow.yaml` + 知識文件）並重啟後端，不需要修改任何 Python 程式碼。詳見 [`docs/add-a-new-department.md`](./docs/add-a-new-department.md)。

---

## 核心特性

1. **自寫 Agent Orchestration Runtime** — resolver + spec + loader + DAG executor 約 200 行，未依賴 LangGraph、CrewAI、AutoGen；workflow YAML 不需要 `parallel:` 或 `depends_on:`，runtime 從步驟之間的 `$xxx` 引用**反推 DAG**，同層自動以 `asyncio.gather` 並行執行。
2. **8 個專責 agent 組成的 pipeline** — `router / knowledge / policy / tone / risk / composer / ticket_decision / clause_analyzer`；每個 agent 走 LLM 結構化輸出（JSON schema 強約束 + 容錯解析），單一職責、單一輸入輸出，方便獨立替換與測試。
3. **完整 Retrieval pipeline** — `BAAI/bge-m3` (1024 維、多語 dense) + BM25 (jieba 分詞) **Hybrid + RRF 融合**；可選 `BAAI/bge-reranker-v2-m3` cross-encoder 精排；結構感知 chunker 認得 Markdown 與繁中法條。詳見 [`docs/eval-report.md`](./docs/eval-report.md)。
4. **Retrieval evaluation harness** — 53 題手寫 golden set 覆蓋 4 個 workspace，量 `recall@k / precision@k / hit_rate@k / MRR`；任何 retrieval 改動都跑 `python -m scripts.run_eval` 驗證，**改 RAG 不再憑感覺**。
5. **多租戶物理隔離** — ChromaDB collection 命名 `ws_<id>__<kb>`，retrieval 同時施加 `where: {workspace_id}` 過濾；單元測試保證隔離不破。
6. **AI Observability** — 每個 agent step 的輸入、輸出、延遲、所用模型皆寫入 trace；Admin UI 逐步重播任一次決策；Citation 帶 heading_path、score 與 retriever 來源（dense / bm25 / rrf）。
7. **LLM Provider 抽象** — 上層 agent 僅呼叫統一介面 `provider.chat(...)`；目前實作 Mock 與 Groq，並為 Ollama / Gemini / OpenRouter 預留接口；Mock 可離線 demo / 自動化測試。
8. **Composer 反幻覺策略** — system prompt 強制 (a) 不得編造未在 citation 內出現的事實 (b) citation 為空時須直接坦承「KB 無相關資訊」；前端 citation UI 顯示分數與 heading_path，讓回答可追源。
9. **PDF 文件攝取** — Admin UI 直接上傳 PDF，後端以 pypdf 解析、結構感知 chunk、embed；多語文件可直接進入 KB。
10. **Mobile-first RWD** — 桌機雙欄、平板與手機改為抽屜式 Trace 面板，任何裝置皆可操作。

---

## Architecture

```
        ┌─────────────────────┐   ┌─────────────────────┐
        │   Chat UI (Vue 3)   │   │   Admin UI (Vue 3)  │
        │   RWD + Pinia       │   │  Workspace / KB /   │
        │   WebSocket client  │   │  Workflow / Traces  │
        └──────────┬──────────┘   └──────────┬──────────┘
                   │     REST / WebSocket    │
                   └────────────┬────────────┘
                                ▼
                   ┌─────────────────────────┐
                   │        FastAPI          │
                   │   /chat  /admin/*  /ws  │
                   └────────────┬────────────┘
                                ▼
                ┌────────────────────────────────┐
                │      Workflow Runtime          │
                │  YAML → spec → resolver →      │
                │  DAG executor (asyncio.gather) │
                └────────────────┬───────────────┘
                                 ▼
         ┌──────────────┬─────────────────┬──────────────┐
         │ Agent Reg.   │   Tool Reg.     │ LLM Provider │
         │  8 agents    │  kb_search      │ Mock / Groq  │
         │              │  ticket_create  │  (others 預留)│
         └──────────────┴────────┬────────┴──────────────┘
                                 ▼
                ┌────────────────────────────────┐
                │  KM Service                    │
                │  ChromaDB + bge-m3 (1024-d)    │
                │  per-workspace collection      │
                └────────────────┬───────────────┘
                                 ▼
                ┌────────────────────────────────┐
                │  SQLite (async, SQLAlchemy 2)  │
                │  workspaces / rooms /          │
                │  messages / traces / tickets   │
                └────────────────────────────────┘
```

設計細節請參考 [`docs/architecture.md`](./docs/architecture.md) 與 [`docs/per-question-flow.md`](./docs/per-question-flow.md)。

---

## Retrieval Pipeline

```
Query
  │
  ├─▶ Dense (bge-m3 → ChromaDB cosine, top-20)
  │
  └─▶ BM25 (jieba 中文分詞 → rank_bm25, top-20)
              │
              ▼
        RRF Fusion (k=60)
              │
              ▼
   Cross-encoder Rerank (optional, bge-reranker-v2-m3, top-5)
              │
              ▼
         Citations → Composer
```

| 階段 | 何時用 | 工作量 |
|------|--------|--------|
| Dense retrieval | 永遠開 | bge-m3 embedding 一次 query call |
| BM25 sparse | `retrieval_mode=hybrid`（預設） | in-memory 索引，lazy build，ingest 時 invalidate |
| RRF fusion | hybrid 模式 | 純算術，無 LLM call |
| Cross-encoder rerank | `RERANK_MODEL` 設值時開啟 | +600 MB 模型、+100~400 ms / query |

**Evaluation 數據（top_k=5、53 題 golden set）**：

| Workspace | dense `MRR` | hybrid `MRR` | hybrid + rerank `MRR` |
|-----------|-----------:|-------------:|----------------------:|
| `cs`    | 1.0000 | 0.9167 | **1.0000** |
| `hr`    | 1.0000 | 0.9583 | **1.0000** |
| `it`    | 1.0000 | 1.0000 | 1.0000 |
| `legal` | 1.0000 | 0.9231 | 0.9231 |

解讀與限制（包含「為什麼 hybrid 在小 dataset 上不一定贏」）寫在 [`docs/eval-report.md`](./docs/eval-report.md)。**重點是現在有度量，下次調整 retrieval 不再靠感覺**。

---

## Agent 套件

平台內建 8 個 agent，每個負責一個特定子任務；workflow YAML 決定哪些 agent 跑、誰先誰後、結果如何串接。

| Agent | 職責 | 輸出 |
|-------|------|------|
| `router` | 依訊息分類意圖（loan / hr / it / legal / complaint / general）以決定下游路由 | `{intent, category}` |
| `knowledge` | 依 router 結果到 workspace KB 取 top-k chunks，並帶回 citations | retrieved hits + citations |
| `policy` | 合規檢核：是否觸及金管會、勞基法、個資法等規範或需揭露事項 | `{violations, compliance_note}` |
| `tone` | 建議回覆語氣（empathetic / professional / direct / cautious / apologetic） | `{tone, rationale}` |
| `risk` | 風險等級判定（low / medium / high）含理由，作為合規與升級依據 | `{risk_level, reasons}` |
| `ticket_decision` | IT 部門專用：判斷是否該自動開工單（含 priority），呼叫 `ticket_create` tool | `{should_create_ticket, summary, rationale}` |
| `clause_analyzer` | 法務部門專用：將條款內容結構化（類型、風險點、建議修改） | `{clause_type, risks, suggestion}` |
| `composer` | 整合上游全部輸出 + KB chunks 產生最終回覆；禁止編造、無 citation 時須直接坦承 | 回覆文字 + citations |

典型 workflow：`router` → (`knowledge` / `policy` / `tone` / `risk` 同層並行) → `composer`。
IT 部門再追加 `ticket_decision`、法務追加 `clause_analyzer`；組合方式由各 workspace 的 `workflow.yaml` 控制。

---

## Tech Stack

| 層 | 選用 | 說明 |
|----|------|------|
| Frontend | Vue 3 + Vite + Pinia + Tailwind + vue-router | Mobile-first RWD；Admin 路由懶載入 |
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2.0 (async) | 業界主流的 async 組合 |
| Storage | SQLite (async)；Postgres-ready | 零成本起步、可平滑升級 |
| Vector DB | ChromaDB persistent + `BAAI/bge-m3` (sentence-transformers) | 1024 維多語 embedding；可透過 `EMBEDDING_MODEL=chroma-default` 切回輕量 ONNX MiniLM |
| Sparse retrieval | `rank_bm25` + `jieba`（中文精確分詞） | Hybrid 模式下與 dense 並跑、RRF 融合 |
| Reranker（可選） | `BAAI/bge-reranker-v2-m3` cross-encoder | `RERANK_MODEL` env 開啟；hybrid 排序抖動可修正回 dense 等級 MRR |
| Eval harness | 自寫 `recall@k / precision@k / MRR` + 53 題 golden set | `python -m scripts.run_eval` 對比 dense / hybrid / rerank |
| Doc Ingest | pypdf + 自寫結構感知 chunker | 支援 PDF、Markdown、JSON、純文字；自動辨識 Markdown 結構與繁中法條（章 / 節 / 條 / 項 / 款） |
| LLM | Provider 抽象：Mock + Groq 已實作（Ollama / Gemini / OpenRouter 介面預留） | Mock 用於離線示範與測試 |
| Realtime | 原生 WebSocket + 客端自動重連 | 不依賴 socket.io 或 Redis pub/sub |
| Deployment | HF Spaces (Docker) + Cloudflare Pages | 詳見 [`docs/deployment.md`](./docs/deployment.md) |

### 未採用的技術

LangChain / LangGraph、CrewAI / AutoGen、Pinecone / Weaviate、Redis、Kubernetes。
這些選項要嘛抽走平台層最有價值的設計決策，要嘛屬於目前規模下的過度設計。

---

## Quick Start

需求：Python 3.11+、Node.js 20+

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # Windows
# source .venv/bin/activate      # macOS / Linux
pip install -e .
cp .env.example .env             # 填入 GROQ_API_KEY，或保持 LLM_PROVIDER=mock
uvicorn app.main:app --port 8000
```

> 首次啟動會下載 bge-m3 模型 (~2 GB)。
> 若僅需英文場景或希望縮減體積，可在 `.env` 設定 `EMBEDDING_MODEL=chroma-default`，改用 Chroma 內建的 ONNX MiniLM（384 維、無 PyTorch 依賴）。

啟動 log 範例：
```
Initializing SentenceTransformerEmbeddingFunction (model=BAAI/bge-m3)
Registered tools: ['kb_search', 'ticket_create']
Registered default agents: ['router', 'knowledge', 'policy', 'tone', 'risk', 'composer', 'ticket_decision', 'clause_analyzer']
Seeded cs/faq with 15 documents
Preloaded 4 workflows: ['cs', 'hr', 'it', 'legal']
Application startup complete.
```

健康檢查：`curl http://localhost:8000/health`

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

開啟 http://localhost:5173 後，點選頂部的部門按鈕切換 workspace，並嘗試各部門的示範問題：

| 部門 | 示範問題 |
|------|----------|
| 客服 | 70 歲可以申請車貸嗎？ |
| HR | 我可以休幾天特休？ |
| IT Helpdesk | 我的公司筆電遺失了（會觸發自動開單） |
| 法務 | 怎麼簽 NDA？ |

點擊任一 AI 回覆即可開啟 Trace 面板，檢視該次提問背後所有 agent step 的輸入、輸出與延遲。
進入頂部 **Admin** 可瀏覽 workspace 詳情、workflow YAML、知識庫內容、PDF 上傳、Trace 紀錄。

### 3. 執行測試

```bash
cd backend
pytest tests/
```

涵蓋範圍：workflow resolver、workflow loader、router 解析、KM 多租戶隔離、chunker（Markdown + 法條）、BM25 tokenize、RRF fusion、eval metrics、hybrid retriever、agent 套件、end-to-end pipeline。

### 4. 跑 retrieval 評估

```bash
cd backend
python -m scripts.run_eval                  # dense vs hybrid 對比
python -m scripts.run_eval --rerank         # 加 cross-encoder 精排（會下載 ~600MB 模型）
python -m scripts.run_eval --workspace cs   # 只跑某個 workspace
```

評估結果與分析：[`docs/eval-report.md`](./docs/eval-report.md)。Eval 使用獨立的 `backend/.eval-data/`，不會污染正式 dev 資料夾。

---

## 專案結構

```
AI_SP/
├── docs/                       架構、概念、流程、部署、demo script
├── backend/                    FastAPI + AI orchestration
│   └── app/
│       ├── agents/             8 個 agent（router / knowledge / policy / tone / risk / composer / ticket_decision / clause_analyzer）
│       ├── tools/              kb_search、ticket_create
│       ├── providers/          LLM provider 抽象（mock + groq）
│       ├── workflow/           spec / resolver / runtime / loader / bootstrap / seeder
│       ├── km/                 ChromaDB store / 結構感知 chunker / hybrid retriever（dense + BM25 + RRF）/ rerank / eval harness
│       ├── api/                chat + admin REST
│       ├── ws/                 WebSocket hub
│       ├── db/                 SQLAlchemy async models
│       └── schemas/            Pydantic schemas
├── frontend/                   Vue 3 + Vite + Pinia + Tailwind（RWD）
│   └── src/
│       ├── pages/
│       │   ├── ChatPage.vue                 雙欄 / 抽屜
│       │   └── admin/                       Workspaces / WorkspaceDetail / KbDetail / Traces
│       ├── components/         WorkspaceSelector / ChatWindow / AiTracePanel
│       ├── stores/             Pinia
│       └── ws/                 WebSocket client（auto-reconnect）
├── workspaces/                 4 個部門：cs / hr / it / legal
│   └── <id>/
│       ├── workspace.json
│       ├── workflow.yaml       runtime 從這裡讀
│       └── knowledge/faq.json
├── Dockerfile                  HF Spaces 部署用（CPU torch + 預下 bge-m3）
└── README.md                   本文件
```

---

## 開發進度

| Phase | 內容 | 狀態 |
|-------|------|------|
| 1 | Skeleton + hard-coded workflow | ✅ |
| 2 | LLM Provider 抽象 + Groq | ✅ |
| 3 | KM 基礎 + Knowledge Agent | ✅ |
| 4 | Workspace + 4 部門 seed | ✅ |
| 5 | Workflow as Config (YAML) — 平台組合能力建立 | ✅ |
| 6 | 完整 Agent 套件（Policy / Tone / Risk / TicketDecision / ClauseAnalyzer）+ Tools | ✅ |
| 7 | Admin UI（4 頁面 + REST API + PDF 上傳） | ✅ |
| 8 | Docs / Dockerfile / Demo polish | ✅ |
| 9 | 多語 embedding 升級（MiniLM → bge-m3） | ✅ |
| 10 | 前端 mobile-first RWD | ✅ |
| 11 | 結構感知 chunker：Markdown / 繁中法條 / 表格 / 程式碼 | ✅ |
| 12 | Hybrid retrieval（BM25 + RRF）+ Cross-encoder rerank + Evaluation harness | ✅ |

**測試**：`pytest` 全部通過（59 個測試；含 chunker 結構與法條、BM25 tokenize、RRF fusion、eval metrics、hybrid retriever、KM 多租戶隔離、pipeline e2e）。
**Eval**：53 題手寫 golden set；dense / hybrid / +rerank 三組指標寫在 [`docs/eval-report.md`](./docs/eval-report.md)。
**Bundle**：Frontend `npm run build` ~104 kB JS（gzip ~40 kB），Admin 頁面以路由懶載入分塊。
