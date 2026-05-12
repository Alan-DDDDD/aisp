# Progress Log

> 每個 Phase 的實作細節與驗收紀錄。完整規劃見 [`PLAN.md`](./PLAN.md)。

---

## Phase 1 — Skeleton + hard-coded workflow ✅

- FastAPI + SQLAlchemy 2.0 async + SQLite + Pydantic v2
- `BaseAgent` / `AgentContext` / `BaseTool` 契約
- LLM 抽象 + `MockProvider`
- `RouterAgent`（JSON 分類）+ `ComposerAgent`
- Hard-coded Router → Composer pipeline + AgentTrace
- REST + WebSocket hub
- Vue 3 + Vite + Pinia + Tailwind；ChatPage + ChatWindow + AiTracePanel

---

## Phase 2 — 接上真實 LLM ✅

- `GroqProvider`：OpenAI-compatible chat completions，支援 JSON mode
- `truststore` 自動使用 OS 憑證庫（解決企業網路 self-signed CA）
- Router 強化：剝 ```json 圍欄、找 `{...}` 子字串、category 白名單夾擊

---

## Phase 3 — KM / RAG 基礎 ✅

- ChromaDB persistent client（內建 ONNX MiniLM-L6 embedding）
- `KnowledgeBase` / `Document` / `Chunk` SQL schema
- Workspace-scoped collection 命名 `ws_<id>__<kb>`
- `KBSearchTool` + `KnowledgeAgent`；Router → Knowledge → Composer
- Seed-on-boot：啟動時自動 ingest FAQ
- Admin endpoints：列 KB、列 docs、看 chunks

---

## Phase 4 — Workspace + 多部門 ✅

- `Workspace` SQL 表；4 個 seed 部門 CS / HR / IT / Legal
- 每部門 workspace.json + knowledge/faq.json（總 37 條 FAQ）
- 公開 API `GET /api/workspaces`
- Frontend：頂部 selector（彩色按鈕 + doc count badge）

---

## Phase 5 — Workflow as Config (YAML) ✅

> 從這一刻起，改變部門行為不用動 code — 改 YAML 就好。

- `WorkflowDef` / `WorkflowStep` Pydantic schema
- 變數解析 `$event.x` / `$context.x` / `$<step>.x`，支援純引用、字串內插、dict/list 遞迴
- `WorkflowRuntime`：從 step input 自動推導依賴 → topological 分層 → 同層 `asyncio.gather` 並行
- Loader 啟動 preload + reload API
- 4 個部門各一份 workflow.yaml
- WS hub 改走 `run_workflow(workflow, event, context)`，舊 hard-coded orchestrator 已刪除

---

## Phase 6 — 完整 Agent 套件 ✅

新增 5 個 agents + 1 個 tool：

| Agent / Tool | 職責 | 用於 |
|--------------|------|------|
| `PolicyAgent` | 合規檢核 → violations / citations / compliance_note | CS |
| `ToneAgent` | 語氣建議 | CS / HR |
| `RiskAgent` | 風險等級 | Legal |
| `ClauseAnalyzerAgent` | 條款分析 | Legal |
| `TicketDecisionAgent` | IT 工單決策 | IT |
| `TicketCreateTool` | 寫 SQLite tickets 表 | IT |

各部門 workflow 形狀：

| Workspace | Pipeline | 特色 |
|-----------|----------|------|
| CS | router → knowledge → policy + tone → composer | 5 step；合規與語氣雙軌 |
| HR | router → knowledge + tone → composer | 4 step；同理優先 |
| IT | router → knowledge + ticket_decision → composer | 4 step；自動開單 |
| Legal | router → clause_analyzer + knowledge → risk → composer | 5 step；條款 + 風險 |

新增功能：
- `ComposerInput` 擴充 `policy / risk / tone_rationale / clause_analysis / ticket`
- `WsAiSuggestionOut.extras` 透傳給前端
- AI 訊息下方彩色 badge：工單 / 風險 / 合規 / 語氣 / 條款
- 把 Router 的 JSON 解析抽到 `agents/_json_util.py` 共用

實測：
```
cs    | 5 steps, 1523ms | policy citations + compliance_note
hr    | 4 steps,  682ms | tone 自動選擇
it    | 4 steps,  970ms | ticket T-95A7787E 自動寫入 SQLite
legal | 5 steps,  665ms | risk + clause_analysis 並行
```

---

## Phase 7 — Admin UI ✅

5 個 admin 頁面 + 7 個新 API endpoints：

| 頁面 | 路徑 | 內容 |
|------|------|------|
| Workspaces 列表 | `/admin` | 4 部門卡片，doc / KB count |
| Workspace 詳情 | `/admin/workspaces/:id` | pipeline 視覺化 + YAML + KB + traces + tickets |
| KB 詳情 | `/admin/kbs/:id` | 文件列表，展開看 chunks |
| Trace Explorer | `/admin/traces` | 左列表 + 右 step I/O |
| Chat | `/` | 原本對話介面 |

新 API：`GET /api/admin/workspaces/{id}`、`/rooms`、`/workflow`、`POST .../workflow/reload`、`/kbs/{id}/documents`、`/documents/{id}/chunks`、`/traces`、`/tickets`

技術調整：vue-router 4.6 + 懶載入；前端總 bundle ~103 kB JS + 17 kB CSS（gzip ~44 kB）

---

## Phase 8 — Demo Polish ✅

- `docs/architecture.md` — 系統架構文字版
- `docs/concepts.md` — 名詞表
- `docs/add-a-new-department.md` — 5 分鐘加新部門教學
- `docs/deployment.md` — HF Spaces + CF Pages 部署
- `docs/demo-script.md` — 5 分鐘面試 demo 腳本
- `Dockerfile` + `.dockerignore` — HF Spaces 部署用
- README 重寫為 portfolio 首頁

---

## 測試覆蓋

| 類別 | 數量 |
|------|------|
| KM (ingest, isolation) | 2 |
| Workflow runtime smoke | 2 |
| Variable resolver | 7 |
| Router JSON parser | 5 |
| Workflow YAML loader | 3 |
| Phase 6 agents fallback | 4 |
| **總計** | **23 passed** |
