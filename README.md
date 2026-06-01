---
sdk: docker
title: Aisp
short_description: Enterprise AI Agent platform with YAML workflows
---

# AISP — Enterprise AI Agent Platform

[![tests](https://img.shields.io/badge/tests-214%20passing-brightgreen)]()
[![phase](https://img.shields.io/badge/phase-14-blue)]()
[![backend](https://img.shields.io/badge/backend-FastAPI%20%2B%20SQLAlchemy%202-009688)]()
[![frontend](https://img.shields.io/badge/frontend-Vue%203%20%2B%20Vite-42b883)]()
[![llm](https://img.shields.io/badge/LLM-Cerebras%20%7C%20Groq%20%7C%20Mock-orange)]()
[![python](https://img.shields.io/badge/python-3.11%2B-3776ab)]()

多部門 AI Agent 平台。每個部門（workspace）用 YAML 設定自己的 agent pipeline 與知識庫，共用同一份後端 runtime；換部門就是換一份設定，不寫 Python。

- Frontend：https://aisp-855.pages.dev
- Backend（HF Space）：https://alan-ddddd-aisp.hf.space
- Source：https://github.com/Alan-DDDDD/aisp

## 為什麼做這個

LangGraph、CrewAI、AutoGen 這類框架在玩 demo 時很順，但要長期維護一個「多部門共用、能換模型、能加工具、能換 retrieval 策略」的真實平台，抽象洩漏的成本很高。AISP 把這套東西自己寫一遍 — 不是因為框架不好，是因為想把每一層的 contract 自己定，看看 200 行 DAG runtime 加 YAML 能撐到哪裡。

目前撐起來的：4 個部門、9 個 agent、hybrid retrieval + rerank、會自己寫工具 + HITL 審核、Telegram bot、214 個 test、53 題 retrieval eval。

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
         ┌──────────────┬─────────────────┬───────────────────┐
         │ Agent Reg.   │   Tool Reg.     │   LLM Providers   │
         │  9 agents    │  kb_search      │  per-role routing │
         │  含 tool_    │  ticket_create  │  Cerebras / Groq  │
         │  agent       │  + generated*   │  Mock             │
         └──────────────┴────────┬────────┴───────────────────┘
                                 │             ┌──────────────────────────────┐
                                 ├────────────▶│  Self-Extending Layer        │
                                 │             │  gap_detector → orchestrator │
                                 │             │  spec / code / test / E2B    │
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

## Workflow runtime

Workflow 是 YAML。每個 step 宣告自己吃哪些 agent 的 output（用 `$step_id.field` 引用）；runtime 從這些引用反推依賴關係，同層的 step 自動 `asyncio.gather` 並行。沒有 `parallel:` 或 `depends_on:` 關鍵字。

```yaml
steps:
  - id: router
    agent: router
    input: { message: $event.message }
  - id: knowledge
    agent: knowledge
    input: { category: $router.category }
  - id: composer
    agent: composer
    input:
      knowledge: $knowledge
      tool_result: $tool_agent.tool_result
```

寫一個新 agent 只需要兩件事：定義 input/output 的 Pydantic schema、寫 `run(ctx, input) -> output`。runtime 跟 trace 機制都會自動接上。

### 提前停下

cs 收到 hr 問題、it 收到法務問題這種跨部門 query，整條 pipeline 不該再往下跑。Step 上可以宣告 `halt_when_false: $router.in_scope`：引用的值是 falsy，runtime 立刻終止整條 pipeline、emit `halt_emit` 裡指定的固定回覆，跳過所有後續 step（含 tool_agent 的合成路徑）。

```yaml
- id: router
  agent: router
  input: { message: $event.message }
  halt_when_false: $router.in_scope
  halt_emit:
    draft: $router.scope_refusal_text
    citations: []
```

「判定是不是 in-scope」是 router 的語意責任、「停下 pipeline」是 runtime 的機制責任，兩件事分開放。寫 agent 的人不用在自己的 prompt 裡 check 部門邊界，YAML 換個 step 也能套用同樣短路機制。

## Retrieval

`bge-m3`（1024 維、多語）dense + BM25（jieba 中文分詞）並行，RRF 融合。可選 `bge-reranker-v2-m3` cross-encoder 精排（多 ~600 MB 模型、+100-400 ms latency）。Chunker 認得 Markdown 結構跟繁中法條（章/節/條/項/款）。

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

### Eval

53 題手寫 golden set，跑 `recall@k / precision@k / hit_rate@k / MRR`。每次調 retrieval 參數都跑這個對比，數字不退步才 merge。

`MRR @ top_k=5`：

| Workspace | dense | hybrid | hybrid + rerank |
|-----------|------:|-------:|----------------:|
| `cs`    | 1.0000 | 0.9167 | 1.0000 |
| `hr`    | 1.0000 | 0.9583 | 1.0000 |
| `it`    | 1.0000 | 1.0000 | 1.0000 |
| `legal` | 1.0000 | 0.9231 | 0.9231 |

hybrid 比 dense 略掉是因為 BM25 對中文同義詞不敏感、會把 dense 的好 hit 排下去；rerank 把它救回來。legal 那 0.9231 是兩題沒救起來，逐題 miss 看 `python -m scripts.run_eval` 輸出。

## Agents

平台內建 9 個 agent。每個負責一個子任務，組合方式由 workspace 自己的 `workflow.yaml` 決定。

| Agent | 職責 | 輸出 |
|-------|------|------|
| `router` | 依訊息分類意圖（loan / hr / it / legal / complaint / general） | `{intent, category}` |
| `knowledge` | 從 workspace KB 取 top-k chunks，帶回 citations | retrieved hits + citations |
| `tool_agent` | 跑 gap detection：USE 既有工具 / GAP 觸發合成 / no_tool_needed 放行 | `{tool_called, tool_result, candidates, skipped_reason, gap_specs}` |
| `policy` | 合規檢核：金管會、勞基法、個資法、需揭露事項 | `{violations, compliance_note}` |
| `tone` | 建議回覆語氣 | `{tone, rationale}` |
| `risk` | 風險等級（low / medium / high） + 理由 | `{risk_level, reasons}` |
| `ticket_decision` | IT 部門專用：判斷是否該自動開工單 | `{should_create_ticket, summary, rationale}` |
| `clause_analyzer` | 法務部門專用：將條款內容結構化 | `{clause_type, risks, suggestion}` |
| `composer` | 整合所有上游 output + KB chunks + tool_result，產生最終回覆 | 回覆文字 + citations |

CS workflow 長這樣：`router` → (`tool_agent` / `knowledge` / `policy` / `tone` 並行) → `composer`。IT 多一個 `ticket_decision`，法務多一個 `clause_analyzer`。

## Composer 反幻覺

8B 模型對 prompt 約束的服從度有限。光靠 system prompt 寫「沒證據就回固定句」實測還是會幻覺（例如使用者問「100 公分等於幾英寸」，沒工具沒 KB 資料時，模型仍然會自己算）。所以放了三層：

1. System prompt 三條硬規則 — 沒 `[TOOL_RESULT]` 也沒 `[KNOWLEDGE]` 就 verbatim 輸出固定句
2. `_build_context` 跳過「實質為空」的 tool_result（含 `kb_search` 回 `docs=[]`）
3. **程式碼層 hard guard — 無依據時根本不呼叫 LLM，直接 return 固定句**

第三層才是真正擋得住的那一層。第一二層是好習慣，但模型不見得理你。

## Self-Extending Agent

系統碰到「沒工具能解這個 step」時，會自動跑一條 pipeline 把工具寫出來，HITL 審核通過才註冊上線。

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
│              E2B Sandbox（pytest + Observer）                │
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

幾個值得講的設計：

| 設計 | 為什麼 |
|------|--------|
| Per-step 而非 per-query | 一個 query 可能既要用既有工具又需要新工具，step 粒度才能精準判斷 |
| Cascading gap detection | 純 retrieval 抓不到語意差別、純 LLM 太貴；shortcut 處理顯然 case、灰色區再丟 Judge LLM、再灰再問人類 |
| Code-Test 隔離（兩次 LLM call） | 同一個 context 看 code 寫 test，會寫出遷就 code 的測試 — 從 spec 獨立生才驗得到 spec |
| AST static check | 字串搜尋會誤判 `"eval"` 是字串還是函式呼叫；AST 才能精確分辨 |
| E2B 雲端 sandbox | 真正的 Linux container 隔離；本機沒 key 時 fallback 到 LocalSubprocessRunner（不隔離，dev only） |
| Sandbox 行為觀察 | 不做 declarative permission（會壓抑生成成功率）；改 monkey-patch `socket` / `open` / `httpx` 把 LLM 寫的工具實際碰了什麼 IO 露給審核者看 |
| HITL 雙通道 | Telegram 適合行動裝置即時審核；Web Dashboard 適合審 code diff + 看 attempt history |

`/admin/synthesis` 三個 tab：合成任務（狀態 + attempts + source + tests + behavior + review）、已註冊工具（Promote to global / Deprecate）、決策稽核（依 route 過濾 shortcut_high / judge / human）。

## Multi-provider LLM routing

Groq free tier 70B 每天 100k token 不夠一個人開發又跑 demo，Cerebras free tier 給 1M TPD、~1800 tok/s。所以 bootstrap 按 agent 角色分派 provider：

- `composer` / synthesis（planner / spec / code / test 生成）→ Cerebras `gpt-oss-120b`（OpenAI 開源、120B；可用清單見 cloud.cerebras.ai/?tab=models，靠 `CEREBRAS_DEFAULT_MODEL` 切換）
- `gap_judge` → Groq `llama-3.1-8b-instant`（量小、額度吃不完）
- 其他 agent（router / policy / tone / risk / ticket_decision / clause_analyzer）→ `LLM_PROVIDER` 全域 default

每個 role 用 env var 獨立 override（`COMPOSER_PROVIDER`、`GAP_PLANNER_PROVIDER`、`GAP_JUDGE_PROVIDER`）。空字串就 fallback 到全域。

## 即時進度反饋

送出訊息後到收到 AI 回覆之間，等待時間可能從 5 秒到 30 秒（合成路徑會更久）。WS 補了三種事件：

- `ai_thinking_start` — workflow 開始跑，前端立刻插入 placeholder bubble
- `ai_stage_changed` — 跨入新階段（understanding / retrieving / composing），placeholder 文字跟著換
- `tool_synthesis_triggered` — tool_agent 觸發合成；placeholder 切到「正在為您生成工具」+ 提示 10-30 秒

跑完之後，如果這次有觸發合成，最終 AI 訊息底下會多一格黃色提示框「需審核 — 新工具已生成，需系統管理員審核完成後才能正式使用」，讓使用者知道後續流程。

## Tech Stack

| 層 | 選用 |
|---|---|
| Frontend | Vue 3 + Vite + Pinia + Tailwind + vue-router（Mobile-first RWD；Admin 路由懶載入） |
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2.0（async） |
| Storage | SQLite（async）；schema 對 Postgres-ready |
| Vector DB | ChromaDB persistent + `BAAI/bge-m3`；可切回 Chroma 內建 MiniLM（384 維、無 PyTorch） |
| Sparse retrieval | `rank_bm25` + `jieba` |
| Reranker | `BAAI/bge-reranker-v2-m3` cross-encoder（optional） |
| Eval harness | 自寫 `recall@k / precision@k / MRR` + 53 題 golden set |
| Doc Ingest | pypdf + 自寫結構感知 chunker（Markdown / 繁中法條 / 表格 / 程式碼） |
| LLM | Mock / Groq / Cerebras，per-role routing 在 bootstrap |
| Realtime | 原生 WebSocket + 客端自動重連 |
| HITL bot | `python-telegram-bot` 22.x（optional `[telegram]`）+ `truststore` 注入 OS CA |
| Sandbox | E2B Cloud（PROD）或 LocalSubprocessRunner（dev fallback）+ Observer monkey-patch |
| Deployment | HF Spaces（Docker）+ Cloudflare Pages |

### 為什麼沒用

- **LangChain / LangGraph / CrewAI / AutoGen**：自寫 200 行 DAG runtime + Pydantic schema 把每個 agent 的 contract 釘死，比抽象洩漏好維護
- **Pinecone / Weaviate**：規模到不了；ChromaDB persistent 同進程 embed + 搜尋省 latency
- **Redis**：WebSocket 是單機，廣播用 in-process dict；多機才需要 pub/sub
- **Kubernetes**：HF Space 單 container 夠用
- **Docker / Firecracker 自架 sandbox**：E2B 已是真隔離的雲端 container；自架是 PLAN §22.13 升級項

## Quick Start

需求：Python 3.11+、Node.js 20+。

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # Windows
# source .venv/bin/activate      # macOS / Linux
pip install -e .
cp .env.example .env             # 填 GROQ_API_KEY 或保留 LLM_PROVIDER=mock
uvicorn app.main:app --port 8000
```

首次啟動會下載 bge-m3 embedding 模型（~2 GB）。啟 reranker 另下載 ~600 MB cross-encoder。要省的話 `.env` 設 `EMBEDDING_MODEL=chroma-default` 切回 384 維 MiniLM。

`GROQ_API_KEY` 在 [console.groq.com](https://console.groq.com/keys) 免費申請。free tier 對 `llama-3.3-70b-versatile` 限 100k tokens/day；如果要跑合成路徑，建議多申請一份 [Cerebras Cloud](https://cloud.cerebras.ai) 的 key（free 1M TPD）然後在 `.env` 設：

```
CEREBRAS_API_KEY=...
COMPOSER_PROVIDER=cerebras
GAP_PLANNER_PROVIDER=cerebras
# 可省略 — 不設就吃 CEREBRAS_DEFAULT_MODEL（預設 gpt-oss-120b）
GAP_PLANNER_MODEL=gpt-oss-120b
```

啟動 log 看得到 `LLM routing — default=groq, composer=cerebras, planner=cerebras, judge=groq` 就代表 routing 生效。

健康檢查：`curl http://localhost:8000/health`。

### Telegram HITL（選用）

Web dashboard `/admin/synthesis` 永遠可用，沒 token 也行。要加 Telegram 即時審核：

```bash
pip install -e ".[telegram]"
```

`.env`：

```
TG_BOT_TOKEN=<向 @BotFather 申請>
TG_CHAT_ID=<先傳訊息給 bot，呼叫 getUpdates 看 chat.id>
TG_MODE=polling
```

沒設 token 系統 fallback 到 `FakeBot`（不打網路、單測能跑），HITL 全走 web。

### Frontend

```bash
cd frontend
npm install
npm run dev
```

http://localhost:5173 開起來後切換頂部部門按鈕試各部門：

| 部門 | 示範問題 |
|------|----------|
| 客服 | 70 歲可以申請車貸嗎？ |
| HR | 我可以休幾天特休？ |
| IT Helpdesk | 我的公司筆電遺失了（會觸發自動開單） |
| 法務 | 怎麼簽 NDA？ |

點任一 AI 回覆開 Trace 面板。頂部 **Admin** 是後台。

### Tests

```bash
cd backend
pytest tests/
```

涵蓋：

- workflow resolver / loader / DAG executor
- 9 個 agent + e2e pipeline
- KM 多租戶隔離 + chunker（Markdown / 法條） + BM25 + RRF + eval metrics
- Synthesis：planner / judge / spec_enricher / code/test generator / AST check / sandbox / orchestrator retry / registry hot-load
- HITL：approval state machine（10 state）/ telegram sender / notifier / callback router
- Chat-Tool pipeline：tool_agent 8 條 path + router→tool_agent→composer e2e
- 反幻覺 hard guard + `_is_effectively_empty` 8 case 邊界
- Tool discoverability filter

### Retrieval Eval

```bash
cd backend
python -m scripts.run_eval                  # dense vs hybrid
python -m scripts.run_eval --rerank         # 加 cross-encoder
python -m scripts.run_eval --workspace cs   # 限單一 workspace
```

輸出 markdown 報告（stdout），可重導到檔案。eval 用獨立的 `backend/.eval-data/`，不會污染 dev 資料。

## 專案結構

```
AI_SP/
├── backend/                    FastAPI + AI orchestration
│   └── app/
│       ├── agents/             9 個 agent
│       ├── tools/              kb_search、ticket_create + runtime-generated
│       ├── synthesis/          gap detection、code/test generator、static check、sandbox、approval state machine
│       ├── telegram/           Telegram bot、HITL notifier、callback router
│       ├── providers/          LLM provider 抽象（mock / groq / cerebras）
│       ├── workflow/           spec / resolver / runtime / loader / bootstrap / seeder
│       ├── km/                 ChromaDB store / 結構感知 chunker / hybrid retriever / rerank / eval
│       ├── api/                chat + admin REST + synthesis
│       ├── ws/                 WebSocket hub
│       ├── db/                 SQLAlchemy async models
│       └── schemas/            Pydantic schemas
├── workspaces/generated_tools/ runtime 產生的工具 source（gitignored）
├── frontend/                   Vue 3 + Vite + Pinia + Tailwind
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
├── Dockerfile                  HF Spaces 部署用
└── README.md                   本文件
```

## 進度

| Phase | 內容 | 狀態 |
|-------|------|------|
| 1 | Skeleton + hard-coded workflow | ✅ |
| 2 | LLM Provider 抽象 + Groq | ✅ |
| 3 | KM 基礎 + Knowledge Agent | ✅ |
| 4 | Workspace + 4 部門 seed | ✅ |
| 5 | Workflow as Config（YAML） | ✅ |
| 6 | 完整 Agent 套件（Policy / Tone / Risk / TicketDecision / ClauseAnalyzer）+ Tools | ✅ |
| 7 | Admin UI（4 頁面 + REST API + PDF 上傳） | ✅ |
| 8 | Docs / Dockerfile / Demo polish | ✅ |
| 9 | 多語 embedding 升級（MiniLM → bge-m3） | ✅ |
| 10 | 前端 mobile-first RWD | ✅ |
| 11 | 結構感知 chunker：Markdown / 繁中法條 / 表格 / 程式碼 | ✅ |
| 12 | Hybrid retrieval（BM25 + RRF）+ Cross-encoder rerank + Eval harness | ✅ |
| 13 | Self-Extending Agent：gap detection + tool synthesis + HITL（Telegram + Web） | ✅ |
| 14 | Chat ↔ Tool 整合 + composer 三層反幻覺 + 多 provider routing（Cerebras / Groq）+ E2B sandbox + 即時進度反饋 | ✅ |

214 個 test 全綠；53 題 retrieval eval 在 `python -m scripts.run_eval`；frontend `npm run build` ~124 kB JS gzip ~47 kB。
