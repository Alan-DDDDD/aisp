# AISP — Enterprise AI Agent Platform

> **Multi-Department Agentic Workspace.**
> 每個部門用 YAML 設定自己的 AI Agent 流程與知識庫，共用同一份後端 runtime。

🔗 **Live demo (frontend)**: https://aisp-855.pages.dev
🔧 **Backend runtime (HF Space)**: https://alan-ddddd-aisp.hf.space
💻 **Source code**: https://github.com/Alan-DDDDD/aisp

---

## 專案簡介

AISP 是一個多部門 AI Agent 平台。將 **Knowledge、Agent、Workflow** 抽象成獨立的 domain object，讓不同部門 (workspace) 共用同一份 runtime，但因為設定不同而呈現完全不同的對話行為。

專案內建 4 個示範部門：**客服、HR、IT Helpdesk、法務**。新增一個部門只需要建立 3 個檔案（`workspace.json` + `workflow.yaml` + 知識文件）並重啟後端，不需要修改任何 Python 程式碼。

---

## 核心特性

1. **自寫 Agent Orchestration Runtime** — resolver + spec + loader + DAG executor 約 200 行，未依賴 LangGraph、CrewAI、AutoGen；workflow YAML 不需要 `parallel:` 或 `depends_on:`，runtime 從步驟之間的 `$xxx` 引用**反推 DAG**，同層自動以 `asyncio.gather` 並行執行。
2. **9 個專責 agent 組成的 pipeline** — `router / knowledge / policy / tone / risk / composer / ticket_decision / clause_analyzer / tool_agent`；每個 agent 走 LLM 結構化輸出（JSON schema 強約束 + 容錯解析），單一職責、單一輸入輸出，方便獨立替換與測試。
3. **完整 Retrieval pipeline** — `BAAI/bge-m3` (1024 維、多語 dense) + BM25 (jieba 分詞) **Hybrid + RRF 融合**；可選 `BAAI/bge-reranker-v2-m3` cross-encoder 精排；結構感知 chunker 認得 Markdown 與繁中法條。
4. **Retrieval evaluation harness** — 53 題手寫 golden set 覆蓋 4 個 workspace，量 `recall@k / precision@k / hit_rate@k / MRR`；任何 retrieval 改動都跑 `python -m scripts.run_eval` 驗證，**改 RAG 不再憑感覺**。
5. **多租戶物理隔離** — ChromaDB collection 命名 `ws_<id>__<kb>`，retrieval 同時施加 `where: {workspace_id}` 過濾；單元測試保證隔離不破。
6. **AI Observability** — 每個 agent step 的輸入、輸出、延遲、所用模型皆寫入 trace；Admin UI 逐步重播任一次決策；Citation 帶 heading_path、score 與 retriever 來源（dense / bm25 / rrf）。
7. **LLM Provider 抽象** — 上層 agent 僅呼叫統一介面 `provider.chat(...)`；目前實作 Mock 與 Groq，並為 Ollama / Gemini / OpenRouter 預留接口；Mock 可離線 demo / 自動化測試。
8. **Composer 反幻覺三層保險** — (a) system prompt 三條硬規則：無 `[TOOL_RESULT]` 也無 `[KNOWLEDGE]` 區塊時 verbatim 輸出固定句；(b) `_build_context` 對「實質為空」的 tool_result（含 kb_search docs=[]）跳過注入；**(c) 程式碼層 hard guard — 無依據時根本不呼叫 LLM，直接 return 固定句**。第三層是真正可靠的保險絲，實測 8B 模型對嚴格 prompt 不夠服從，光靠 (a)(b) 還是會幻覺。
9. **Self-Extending Agent — 自動寫工具 + HITL 審核**（PLAN §22）— 系統遇到沒工具能解的 query 時，自動跑 8-stage pipeline：planner 拆 step → retrieval shortcut → judge LLM → spec enricher → code generator → test generator（**與 code 隔離產生**避免遷就 code 的測試）→ AST static check（whitelist 禁 `exec`/`eval`/`subprocess`）→ sandbox 跑 pytest + monkey-patch 觀察 IO，最多 3 round 修正。**所有 generated tool 一律經 HITL 審核才能進 registry**（Telegram bot + `/admin/synthesis` 雙通道），審完 hot-load 進 process 無需重啟。
10. **Chat ↔ Tool 端到端整合** — `tool_agent` step 接在 router 之後，把 user 對話導向：USE 既有工具 → 呼叫並把結果餵 composer；GAP → 觸發合成 + 等審；無 tool 需求 → 走原 RAG。`composer` 看到 `[TOOL_RESULT]` 區塊就用工具計算結果回覆（不再幻覺），沒看到就硬走 fallback 路徑。
11. **PDF 文件攝取** — Admin UI 直接上傳 PDF，後端以 pypdf 解析、結構感知 chunk、embed；多語文件可直接進入 KB。
12. **Mobile-first RWD** — 桌機雙欄、平板與手機改為抽屜式 Trace 面板，任何裝置皆可操作。

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
         │  9 agents    │  kb_search      │ Mock / Groq  │
         │ (含 tool_    │  ticket_create  │  (others 預留)│
         │  agent)      │  + generated*   │              │
         └──────────────┴────────┬────────┴──────────────┘
                                 │             ┌──────────────────────────────┐
                                 ├────────────▶│  Self-Extending Layer        │
                                 │             │  gap_detector → orchestrator │
                                 │             │  spec/code/test/sandbox      │
                                 │             │  approval(Telegram + web)    │
                                 │             │  *動態註冊 generated tools     │
                                 │             └──────────────────────────────┘
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

**重點是現在有度量，下次調整 retrieval 不再靠感覺**。完整逐題 misses、解讀、limitation 由 `python -m scripts.run_eval` 重現。

---

## Agent 套件

平台內建 9 個 agent，每個負責一個特定子任務；workflow YAML 決定哪些 agent 跑、誰先誰後、結果如何串接。

| Agent | 職責 | 輸出 |
|-------|------|------|
| `router` | 依訊息分類意圖（loan / hr / it / legal / complaint / general）以決定下游路由 | `{intent, category}` |
| `knowledge` | 依 router 結果到 workspace KB 取 top-k chunks，並帶回 citations | retrieved hits + citations |
| `tool_agent` | 對 user message 跑 gap_detector → USE 命中既有工具呼叫 / GAP 觸發合成 / no_tool_needed 放行 | `{tool_called, tool_result, candidates, skipped_reason, gap_specs}` |
| `policy` | 合規檢核：是否觸及金管會、勞基法、個資法等規範或需揭露事項 | `{violations, compliance_note}` |
| `tone` | 建議回覆語氣（empathetic / professional / direct / cautious / apologetic） | `{tone, rationale}` |
| `risk` | 風險等級判定（low / medium / high）含理由，作為合規與升級依據 | `{risk_level, reasons}` |
| `ticket_decision` | IT 部門專用：判斷是否該自動開工單（含 priority），呼叫 `ticket_create` tool | `{should_create_ticket, summary, rationale}` |
| `clause_analyzer` | 法務部門專用：將條款內容結構化（類型、風險點、建議修改） | `{clause_type, risks, suggestion}` |
| `composer` | 整合上游全部輸出 + KB chunks + tool_result 產生最終回覆；無依據時 hard guard 直接 return 固定句（不呼叫 LLM）| 回覆文字 + citations |

典型 workflow（CS）：`router` → (`tool_agent` / `knowledge` / `policy` / `tone` 同層並行) → `composer`。
IT 部門再追加 `ticket_decision`、法務追加 `clause_analyzer`、CS 啟用 `tool_agent`；組合方式由各 workspace 的 `workflow.yaml` 控制。

---

## Self-Extending Agent

當系統遇到「沒有現成工具能解決這個 step」的 query，平台會自動進入工具合成流程：產生 spec、寫 code、寫 test（與 code 隔離產生）、AST 靜態檢查、sandbox 執行、行為觀察，最後把整包送到 **Telegram 或 Web Dashboard 等人類核准**才註冊上線。設計動機是把這個 platform 從「會用工具的 AI Chat」推進到「會造工具的 AI Work」。

### Pipeline

```
Query
  │
  ▼
┌────────────────── Phase A：Gap Detection ──────────────────┐
│  Planner LLM 拆 steps                                       │
│      │                                                      │
│      ▼                                                      │
│  per step：retrieval similarity                             │
│      │                                                      │
│      ├─ ≥ 0.85 → shortcut HIGH  → USE                       │
│      ├─ ≤ 0.40 → shortcut LOW   → GAP                       │
│      └─ middle → Judge LLM (batched)                        │
│                       │                                     │
│                       └─ confidence gray → Telegram HITL    │
│                                                             │
│  每個決策寫一筆 tool_decisions_audit                          │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌────────────────── Phase B：Tool Synthesis ──────────────────┐
│  Spec Enricher LLM（補 input/output fields、examples）        │
│      │                                                      │
│      ▼                                                      │
│  Code Generator LLM       ─ ─ ─ 與 Code 隔離 ─ ─ ─           │
│      │                                       │              │
│      ▼                                       ▼              │
│  AST Static Check                Test Generator LLM         │
│  （import whitelist、              （只看 spec，不看 code）   │
│   禁 exec/eval/open/subprocess）                            │
│      │                                       │              │
│      └──────────────────┬────────────────────┘              │
│                         ▼                                   │
│              Sandbox 執行（pytest）                          │
│         + Observer（socket / open / httpx 監控）              │
│                         │                                   │
│      ┌──────────────────┴──────────────────┐                │
│      │ pass → AWAITING_APPROVAL            │                │
│      │ fail → feedback into next round     │  最多 3 輪    │
│      │ 3 fail → AWAITING_HUMAN_RESCUE      │                │
│      └─────────────────────────────────────┘                │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
            ┌── HITL 雙通道 ──┐
            │ Telegram bot   │
            │ Web Dashboard  │ ──▶ Approve → 寫檔 + 註冊到 tool_registry
            └────────────────┘ ──▶ Refine + hint → 重跑
                               ──▶ Reject → 標 DISCARDED
```

### 重要設計決策

| 設計 | 為什麼 |
|------|--------|
| **Cascading gap detection** | 純 retrieval 抓不到語意差別、純 LLM 太貴；用 similarity shortcut 處理顯然 case、灰色區交給 Judge LLM、再灰再問人類 |
| **Per-step 而非 per-query** | 一個 query 可能同時用既有工具又需要新工具；step 粒度才能精準判斷 |
| **Code-Test 隔離（不同 LLM call）** | 同一個 context 看 code 寫 test，會寫出遷就 code 的測試 — 從 spec 獨立生才能驗 spec |
| **AST 靜態檢查** | 字串搜尋會誤判 `"eval"` 是字串還是函式呼叫；AST 才能精確分辨 |
| **Sandbox 行為觀察** | 不做 declarative permission（會壓抑生成成功率）；改 monkey-patch `socket` / `open` / `httpx` 把 LLM 寫出來的工具實際碰了什麼網路 / 檔案露給審核者看 |
| **Workspace scoped + 可 promote** | 各部門先自己用，admin 可升級為全 workspace 共用 — 避免一個 tool 污染整個平台 |
| **HITL 雙通道** | Telegram 適合行動裝置即時審核；Web Dashboard 適合審 code diff + 看 attempt history |

### 觀測與管理

`/admin/synthesis` 三個 tab：

| Tab | 內容 |
|-----|------|
| Synthesis Tasks | 每個合成任務的狀態、attempts、source code、test 結果、behavior observation、review history；可直接 Approve / Reject |
| Generated Tools | 已註冊的合成工具列表，支援 Promote to global、Deprecate |
| Decision Audit | Phase A 每次 USE / COMPOSE / GAP 決策的稽核 log，可依 route（shortcut_high / judge / human）過濾 |

### 新增資料結構

- `tool_decisions_audit` — Phase A 每次決策（含信心、候選、reasoning）
- `tool_synthesis_tasks` — 合成任務狀態機（10 個 state）+ attempt history
- `generated_tools` — 已註冊的合成工具
- `tool_review_history` — 審核紀錄（approve / reject / refine + hint）

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
| LLM | Provider 抽象：Mock + Groq 已實作（Ollama / Gemini / OpenRouter 介面預留） | Mock 用於離線示範與測試；Groq 預設 8B fast + 70B versatile 雙模型分流 |
| Realtime | 原生 WebSocket + 客端自動重連 | 不依賴 socket.io 或 Redis pub/sub |
| HITL bot | `python-telegram-bot` 22.x（optional dep `[telegram]`）+ `truststore` 注入 OS CA | 沒 token 自動 fallback 到 FakeBot；polling / webhook 雙模式 |
| Sandbox | 自寫 LocalSubprocessRunner + `e2b-code-interpreter`（optional dep `[sandbox]`）| Local 跑 `subprocess.run + run_in_executor` + monkey-patch socket/open/httpx 觀察 IO |
| Deployment | HF Spaces (Docker) + Cloudflare Pages | 詳見 Dockerfile；前端為靜態 build，後端為 FastAPI |

### 未採用的技術

| 技術 | 理由 |
|---|---|
| LangChain / LangGraph / CrewAI / AutoGen | 抽象洩漏成本高；workflow-as-YAML + 200 行 DAG runtime 更可控；agent 契約走自家 Pydantic schema 才能跨 step |
| Pinecone / Weaviate | 規模未到，ChromaDB persistent 已夠；同進程 embed + 搜尋省 latency |
| Redis | WebSocket 是單機，廣播用 in-process dict；多機才需要 pub/sub |
| Kubernetes | HF Space 單 container 跑得起來；多 instance 才需要 orchestrator |
| e2b（強制做 sandbox） | optional dep 保留；LocalSubprocess fallback 在 dev 機跟 HF Space 都 work，免外部 API key |
| Docker / Firecracker 自架 sandbox | 完整隔離 runtime 是 PLAN §22.13 U1 升級項；MVP 用 AST static check + 行為觀察 + HITL 三層擋|

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

> 首次啟動會下載 bge-m3 embedding 模型 (~2 GB)。若 `.env` 啟用 reranker (`RERANK_MODEL=BAAI/bge-reranker-v2-m3`) 另下載 ~600 MB cross-encoder。
> 若僅需英文場景或希望縮減體積，可在 `.env` 設定 `EMBEDDING_MODEL=chroma-default`，改用 Chroma 內建的 ONNX MiniLM（384 維、無 PyTorch 依賴）。

> `GROQ_API_KEY` 可從 [console.groq.com](https://console.groq.com/keys) 免費申請；free tier 對 `llama-3.3-70b-versatile` 限 100k tokens/day，Self-Extending Agent 完整合成一次約耗 8-12k token，**demo 規模建議升 Dev Tier 或預期單日合成 ≤ 8 次**。

啟動 log 範例：
```
Initializing SentenceTransformerEmbeddingFunction (model=BAAI/bge-m3)
Registered tools: ['kb_search', 'ticket_create']
Registered default agents: ['router', 'knowledge', 'policy', 'tone', 'risk', 'composer', 'ticket_decision', 'clause_analyzer', 'tool_agent']
Seeded cs/faq with 15 documents
Preloaded 4 workflows: ['cs', 'hr', 'it', 'legal']
load_all_active: N/N generated tools loaded
ToolRetriever indexed M tools
Application startup complete.
```

健康檢查：`curl http://localhost:8000/health`

### Telegram HITL（選用）

若要啟用 Self-Extending Agent 的 Telegram 審核通道（網頁 `/admin/synthesis` 永遠可用，無 token 也行）：

```bash
pip install -e ".[telegram]"      # 安裝 python-telegram-bot
```

`.env` 設：
```
TG_BOT_TOKEN=<向 @BotFather 申請>
TG_CHAT_ID=<你的 chat_id；先傳訊息給 bot，呼叫 getUpdates 看 chat.id>
TG_MODE=polling                   # dev 用；prod 改 webhook
```

未設 token 時系統自動 fallback 到 `FakeBot`（不打網路、單測能跑）；HITL 審核全走 web dashboard。

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

涵蓋範圍：
- **Core**：workflow resolver、workflow loader、router 解析、KM 多租戶隔離、chunker（Markdown + 法條）、BM25 tokenize、RRF fusion、eval metrics、hybrid retriever、agent 套件、end-to-end pipeline
- **Synthesis (Phase 13)**：planner / judge / spec_enricher / code_generator / test_generator / static_check (AST whitelist) / sandbox (LocalSubprocess) / orchestrator retry loop / registry hot-load
- **HITL (Phase 13)**：approval state machine（10 state）/ telegram sender / notifier / callback router / pending requests / review
- **Chat ↔ Tool (Phase 14)**：tool_agent 8 條 path（USE / GAP / no_tool_needed / arg gen / validation / call failure / tool missing / arg parse fail）+ e2e pipeline 跑 router→tool_agent→composer
- **反幻覺 hard guard**：composer 對無依據時不呼叫 LLM 的 short-circuit + `_is_effectively_empty` 8 case 邊界
- **Tool discoverability**：retriever 跳過 `discoverable=False` 的 builtin tools

### 4. 跑 retrieval 評估

```bash
cd backend
python -m scripts.run_eval                  # dense vs hybrid 對比
python -m scripts.run_eval --rerank         # 加 cross-encoder 精排（會下載 ~600MB 模型）
python -m scripts.run_eval --workspace cs   # 只跑某個 workspace
```

輸出為 markdown 報告（stdout），可重導入檔案保存。Eval 使用獨立的 `backend/.eval-data/`，不會污染正式 dev 資料夾。

---

## 專案結構

```
AI_SP/
├── backend/                    FastAPI + AI orchestration
│   └── app/
│       ├── agents/             9 個 agent（router / knowledge / tool_agent / policy / tone / risk / composer / ticket_decision / clause_analyzer）
│       ├── tools/              kb_search、ticket_create + runtime-generated（合成工具）
│       ├── synthesis/          gap detection、code/test generator、static check、sandbox、approval state machine
│       ├── telegram/           Telegram bot（polling / webhook 模式）、HITL notifier、callback router
│       ├── providers/          LLM provider 抽象（mock + groq）
│       ├── workflow/           spec / resolver / runtime / loader / bootstrap / seeder
│       ├── km/                 ChromaDB store / 結構感知 chunker / hybrid retriever（dense + BM25 + RRF）/ rerank / eval harness
│       ├── api/                chat + admin REST + synthesis（detect-gaps / synthesize / approve）
│       ├── ws/                 WebSocket hub
│       ├── db/                 SQLAlchemy async models
│       └── schemas/            Pydantic schemas
├── workspaces/generated_tools/ runtime 產生的工具 source（gitignored）
├── frontend/                   Vue 3 + Vite + Pinia + Tailwind（RWD）
│   └── src/
│       ├── pages/
│       │   ├── ChatPage.vue                 雙欄 / 抽屜
│       │   └── admin/                       Workspaces / WorkspaceDetail / KbDetail / Traces / Synthesis
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
| 13 | Self-Extending Agent — gap detection + tool synthesis + HITL（Telegram + Web Dashboard） | ✅ |
| 14 | Chat ↔ Tool 整合 — `tool_agent` 接 router 後接 composer，含 composer 三層反幻覺保險 | ✅ |

**測試**：`pytest` 全部通過（214 個測試；新增 chat-tool pipeline e2e、tool_agent 路徑覆蓋、composer hard guard、discoverable filter、empty-result 判定）。
**Eval**：53 題手寫 golden set；dense / hybrid / +rerank 三組指標見 `python -m scripts.run_eval`。
**Bundle**：Frontend `npm run build` ~124 kB JS（gzip ~47 kB），Admin 頁面以路由懶載入分塊（含 Synthesis Dashboard）。

## 相關文件

| 檔案 | 內容 |
|---|---|
| [`MANUAL_TEST.md`](./MANUAL_TEST.md) | 對照前端操作的驗證手冊：規劃 vs 實作 + 6 step pipeline 流程 + Admin UI 對應功能 + 5 條 frontend 測試 checklist + 已知 limitations |
| [`DEMO_RECORDING.md`](./DEMO_RECORDING.md) | Demo gif 錄製腳本：4 條 demo（USE / HITL / 反幻覺 / YAML reload）的操作步驟與 ScreenToGif 操作要點 |
