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

1. **自寫 Workflow Runtime** — resolver + spec + loader + DAG executor 約 200 行，未依賴 LangGraph、CrewAI、AutoGen 等框架。
2. **依賴關係自動推導** — Workflow YAML 不需要 `parallel:` 或 `depends_on:`；runtime 從步驟之間的 `$xxx` 引用反推 DAG，同層自動以 `asyncio.gather` 並行執行。
3. **多租戶物理隔離** — ChromaDB collection 命名 `ws_<id>__<kb>`，retrieval 同時施加 `where: {workspace_id}` 過濾；單元測試保證隔離不破。
4. **多語 RAG** — 預設 embedding 為 `BAAI/bge-m3`（1024 維、多語），中文知識庫命中率明顯優於 MiniLM；亦可切換回輕量 ONNX MiniLM。
5. **結構感知切塊** — 自寫 chunker 解析 Markdown（heading / 表格 / 程式碼）與繁中法條結構（章 / 節 / 條，含「之一」修正版、項款、(一)(二)、①②）；表格與程式碼保持原子不切，過長條文以子條款邊界優先切分，heading 路徑作為 breadcrumb prepend 進 chunk 文字，讓 embedding 直接取得段落上下文。
6. **LLM Provider 抽象** — 上層 agent 僅呼叫統一介面 `provider.chat(...)`；目前實作 Mock 與 Groq，並為 Ollama / Gemini / OpenRouter 預留接口。
7. **內建可觀測性** — 每個 agent step 的輸入、輸出、延遲、所用模型皆寫入 trace；Admin UI 可逐步重播任一次決策。
8. **PDF 文件攝取** — Admin UI 直接上傳 PDF，後端以 pypdf 解析、結構感知 chunk、embed，多語文件可直接進入 KB。
9. **Mobile-first RWD** — 桌機雙欄、平板與手機改為抽屜式 Trace 面板，任何裝置皆可操作。

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

## Tech Stack

| 層 | 選用 | 說明 |
|----|------|------|
| Frontend | Vue 3 + Vite + Pinia + Tailwind + vue-router | Mobile-first RWD；Admin 路由懶載入 |
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2.0 (async) | 業界主流的 async 組合 |
| Storage | SQLite (async)；Postgres-ready | 零成本起步、可平滑升級 |
| Vector DB | ChromaDB persistent + `BAAI/bge-m3` (sentence-transformers) | 1024 維多語 embedding；可透過 `EMBEDDING_MODEL=chroma-default` 切回輕量 ONNX MiniLM |
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

涵蓋範圍：workflow resolver、workflow loader、router 解析、KM 多租戶隔離、agent 套件、end-to-end pipeline。

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
│       ├── km/                 ChromaDB store / 結構感知 chunker / ingest / retriever（bge-m3）
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
├── PLAN.md                     原始 21 章完整規劃
├── PROGRESS.md                 每個 Phase 的實作紀錄
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

**測試**：`pytest` 全部通過（45 個測試，涵蓋 KM 隔離、resolver、workflow loader、chunker 結構與法條、pipeline e2e）。
**Bundle**：Frontend `npm run build` ~104 kB JS（gzip ~40 kB），Admin 頁面以路由懶載入分塊。
