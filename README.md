# AISP — Enterprise AI Agent Platform

> **Multi-Department Agentic Workspace.** 讓每個部門用 YAML 設定自己的 AI Agent 流程，
> 配上自己的知識庫，跑在自己的聊天室裡。

---

## What this is

不是 chatbot、不是 LangChain wrapper、不是 ChatGPT clone。

是一個把 **Knowledge / Agent / Workflow** 抽成 domain object 的 **多部門 AI Agent 平台** — 同一份 runtime 跑出 4 個完全不同行為的部門：客服、HR、IT、法務。

> **加新部門 = 寫 3 個檔案、重啟一次後端**，完全不用改 Python code。
> 詳見 [`docs/add-a-new-department.md`](./docs/add-a-new-department.md)。

---

## 為什麼值得看

1. **Workflow runtime 從零自寫**，~200 行（resolver + spec + loader + runtime）。沒靠 LangGraph、CrewAI、AutoGen 撐起來。
2. **依賴推導完全自動** — workflow YAML 沒有任何 `parallel:` 或 `depends_on:`，runtime 從 `$xxx` 引用反推 DAG，同層用 `asyncio.gather` 並行。
3. **多租戶物理隔離** — Chroma collection `ws_<id>__<kb>` + retrieval `where: {workspace_id}` 雙重過濾，有單元測試守在那。
4. **Provider 抽象到位** — `LLM_PROVIDER=mock|groq|...` 五秒切換，demo 翻車有 mock 兜底。
5. **可觀測性是設計的一部分** — 每個 agent step 的 input / output / latency / model 都進 trace，admin UI 可重播任一次決策。

---

## 架構

```
+--------------+    +--------------+    +--------------------------+
|  Chat UI     |    | Admin UI     |    | Workflow Runtime         |
|  (Vue3)      |    | (Vue3)       |    | (resolver + DAG executor)|
+------+-------+    +------+-------+    +-------------+------------+
       |                   |                          |
       +--- REST / WS -----+--- to FastAPI ---+       |
                                              |       v
                            +-----------------+----------------+
                            | Agent Registry | Tool Registry  |
                            +----------------+----------------+
                            | LLM Provider Abstraction        |
                            | (Mock / Groq / Ollama / ...)    |
                            +---------------------------------+
                            | KM Service (ChromaDB + ONNX     |
                            |  MiniLM, per-workspace scoping) |
                            +---------------------------------+
                            | SQLite (workspaces, rooms,      |
                            |  traces, tickets, kbs)          |
                            +---------------------------------+
```

完整架構與設計細節：[`docs/architecture.md`](./docs/architecture.md)

---

## Tech Stack

| 層 | 選用 | 為什麼 |
|----|------|--------|
| Frontend | Vue 3 + Vite + Pinia + Tailwind + vue-router | 開發快、企業感、無框架負擔 |
| Routing | vue-router 4 + 懶載入 admin | chat 首屏輕、admin 按需載入 |
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2.0 async | 業界主流、async 原生 |
| DB | SQLite (dev) → Postgres-ready | 零成本起步可升 |
| Vector DB | ChromaDB persistent + ONNX MiniLM | 內建 embedding，無 PyTorch 依賴 |
| LLM | Provider 抽象：Mock / Groq / Ollama / Gemini | 五秒切換，demo 不翻車 |
| Realtime | 原生 WebSocket | 不上 socket.io / Redis pub/sub |
| 部署 | HF Spaces (Docker) + Cloudflare Pages | 零成本，[`docs/deployment.md`](./docs/deployment.md) |

刻意不用：LangChain / LangGraph、CrewAI / AutoGen、Pinecone / Weaviate、Redis、K8s — 都會掩蓋平台價值或是過度設計。

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
cp .env.example .env             # 並填入 GROQ_API_KEY（或保持 LLM_PROVIDER=mock）
uvicorn app.main:app --port 8000
```

啟動 log 應該看到：
```
Registered tools: ['kb_search', 'ticket_create']
Registered default agents: ['router', 'knowledge', 'policy', 'tone', 'risk', 'composer', 'ticket_decision', 'clause_analyzer']
Seeded cs/faq with 15 documents
Preloaded 4 workflows: ['cs', 'hr', 'it', 'legal']
Application startup complete.
```

驗證：`curl http://localhost:8000/health`

### 2. Frontend

```bash
cd frontend
npm install
# 若 default registry 被擋：npm install --registry https://registry.npmmirror.com
npm run dev
```

打開 http://localhost:5173 → 頂部點 4 個彩色按鈕切部門 → 問各自的問題：

- 客服：「**70 歲可以申請車貸嗎？**」
- HR：「**我可以休幾天特休？**」
- IT：「**我的公司筆電遺失了**」（觸發自動開單）
- 法務：「**怎麼簽 NDA？**」

點頂部 **Admin** 看 workspace 詳情、workflow YAML、KB chunks、trace explorer。

### 3. 跑測試

```bash
cd backend
pytest tests/                              # 23 passed
```

---

## 專案結構

```
AI_SP/
├── docs/                       架構、概念、部署、demo script
├── backend/                    FastAPI + AI orchestration
│   └── app/
│       ├── agents/             8 個 agent（router/knowledge/policy/tone/risk/composer/ticket_decision/clause_analyzer）
│       ├── tools/              kb_search、ticket_create
│       ├── providers/          LLM provider 抽象（mock + groq）
│       ├── workflow/           spec / resolver / runtime / loader / bootstrap / seeder
│       ├── km/                 ChromaDB store / ingest / retriever
│       ├── api/                chat + admin REST
│       ├── ws/                 WebSocket hub
│       ├── db/                 SQLAlchemy models
│       └── schemas/            Pydantic schemas
├── frontend/                   Vue 3 + Vite + Pinia + Tailwind
│   └── src/
│       ├── pages/
│       │   ├── ChatPage.vue
│       │   └── admin/          AdminWorkspaces / AdminWorkspaceDetail / AdminKbDetail / AdminTraces
│       ├── components/         WorkspaceSelector / ChatWindow / AiTracePanel
│       ├── stores/             Pinia
│       └── ws/                 WebSocket client (auto-reconnect)
├── workspaces/                 4 個部門：cs / hr / it / legal
│   └── <id>/
│       ├── workspace.json
│       ├── workflow.yaml       <- runtime 從這讀
│       └── knowledge/faq.json
├── Dockerfile                  HF Spaces 部署用
├── PLAN.md                     原始 21 章完整規劃
├── PROGRESS.md                 每個 Phase 的實作紀錄
└── README.md                   本檔
```

---

## 文檔索引

| 文件 | 內容 |
|------|------|
| [`PLAN.md`](./PLAN.md) | 原始 21 章完整規劃（決策脈絡） |
| [`docs/architecture.md`](./docs/architecture.md) | 系統架構、三層分工、Domain model |
| [`docs/concepts.md`](./docs/concepts.md) | 名詞表（對外講法 vs 內部實作） |
| [`docs/add-a-new-department.md`](./docs/add-a-new-department.md) | 5 分鐘加新部門教學 |
| [`docs/deployment.md`](./docs/deployment.md) | HF Spaces + Cloudflare Pages 部署 |
| [`docs/demo-script.md`](./docs/demo-script.md) | 5 分鐘面試 demo 逐步腳本 |
| [`PROGRESS.md`](./PROGRESS.md) | 每個 Phase 的實作與驗收細節 |

---

## 開發狀態

| Phase | 內容 | 狀態 |
|-------|------|------|
| 1 | Skeleton + hard-coded workflow | ✅ |
| 2 | LLM Provider 抽象 + Groq | ✅ |
| 3 | KM 基礎 + Knowledge Agent | ✅ |
| 4 | Workspace + 4 部門 seed | ✅ |
| 5 | Workflow as Config (YAML) — **平台「成立」的一刻** | ✅ |
| 6 | 完整 Agent 套件（Policy/Tone/Risk/TicketDecision/ClauseAnalyzer）+ Tools | ✅ |
| 7 | Admin UI（5 頁面 + 7 API） | ✅ |
| 8 | Docs / Dockerfile / Demo polish | ✅ |

`pytest`：23 passed。Frontend `npm run build`：~103 kB JS（gzip 44 kB）。
