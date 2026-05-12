# Enterprise AI Agent Platform — 完整規劃

> Multi-Department Agentic Workspace
>
> 一個讓企業各部門能設定自己的 **Agent 流程 + 知識庫 + 聊天室** 的平台。
>
> **三大核心一等公民**：Knowledge Management、Agent、Workflow。

---

## 0. 為什麼重新定位

舊定位（客服輔助 Copilot）的問題：
- 場景單一，看起來像「特定用途的內部工具」。
- AI 工程的部分被「客服情境」蓋住，面試官會以為你做的是「Chatbot 加 RAG」。

新定位的優勢：
- **AI Agent 本身就是主角**，客服只是其中一個示範部門。
- 展示「可組裝、可配置、可擴展」的 platform 思維 —— 這是 AI Platform / Agent Engineer 最稀缺的能力。
- 多部門 = 多場景，一次 demo 多個故事，但用同一套引擎。

---

## 1. 專案定位

| 項目 | 定義 |
|------|------|
| 英文名 | Enterprise AI Agent Platform |
| 副標 | Multi-Department Agentic Workspace |
| 類型 | 企業內部 AI Agent 平台（不是 chatbot，不是 no-code builder） |
| 一句話 | 「讓每個部門用設定檔，組出自己的 AI Agent 流程，配上自己的知識庫，跑在自己的聊天室裡。」 |

### 我不是在做什麼（要會講）
- 不是 ChatGPT clone
- 不是純 RAG demo
- 不是 LangChain wrapper
- 不是 no-code agent builder（不做拖拉 UI，重點在 runtime 與架構）

---

## 2. 核心價值主張

> 「我把 Knowledge、Agent、Workflow 抽出成三個獨立的 domain object，
>  每個部門可以用 YAML 設定自己的 agent 流程與知識範圍，
>  同一個 runtime 跑出完全不同的部門體驗。」

要傳達的訊號：
1. 懂 **Agent 工程化**（不是 prompt，是 system）
2. 懂 **平台思維**（抽象、可組合、可配置）
3. 懂 **多租戶 / Scoping**（部門隔離、KB 隔離）
4. 懂 **可觀測性**（每個 agent step 可被追蹤、可重播）

---

## 3. 目標職位（更偏 Platform / Infra）

- AI Agent Engineer
- AI Platform Engineer
- Applied AI Engineer
- LLM Infra Engineer
- Foundation / Tooling Engineer for AI

---

## 4. 核心展示情境（多部門）

設計 **4 個示範部門（Workspace）**，每個用同一套 platform，但呈現完全不同的樣貌：

| 部門 | 對象 | 典型問題 | Agent Workflow（精簡） | 主要知識庫 | 特殊工具 |
|------|------|---------|----------------------|----------|---------|
| 客服 (CS) | 外部客戶 | 「70歲可以申請車貸嗎？」 | Router → Knowledge → Policy → Tone → Composer | 產品 FAQ、業務 SOP | — |
| HR | 內部員工 | 「特休過期會結算嗎？」 | Intent → PolicyLookup → Empathy → Composer | HR 政策、員工手冊 | PolicyLookupTool |
| IT Helpdesk | 內部員工 | 「VPN 連不上怎麼辦？」 | Triage → KBSearch → Solution → TicketDecision | 故障排除手冊、Runbook | TicketCreateTool（mock） |
| 法務 | 內部部門 | 「這條 NDA 有問題嗎？」 | Intake → ClauseAnalyzer → RiskCheck → Recommend | 範本合約、合規條款 | ClauseExtractTool |

### 一次 Demo 講三個故事
1. **同一個 platform**，切換部門就完全變樣。
2. **同一份 agent 程式碼**，配置不同就有不同行為。
3. **加新部門 = 寫一份 YAML + ingest 文件**，不用改 code。

這個訊號比「我做了一個客服 bot」強 10 倍。

---

## 5. 核心概念與 Domain Model

這是整個 plan 最關鍵的章節。**先把名詞定好，後面整個系統都跟著走。**

```
Workspace (= Department)
├── KnowledgeBase[]           # 一個 workspace 可有多個 KB
│   └── Document → Chunk → Embedding
├── Agent[]                   # 該 workspace 啟用的 agents
├── Workflow                  # agent 的編排（一個 workspace 一條主流程，可擴充）
├── Tool[]                    # 該 workspace 可用的工具
└── ChatRoom[]                # 進行中的對話實例
    └── ChatMessage[]
        └── AgentTrace        # 該訊息觸發的 agent pipeline 紀錄
```

### 5.1 名詞定義

| Domain Object | 定義 | 範例 |
|---------------|------|------|
| **Workspace** | 一個邏輯隔離的「部門」，擁有自己的 KB、agents、workflow、chat rooms | `cs`, `hr`, `it`, `legal` |
| **KnowledgeBase** | 一組向量化的文件集合，掛在某個 workspace 下 | `cs.faq`, `hr.policy_v2` |
| **Agent** | 一個有明確職責、輸入、輸出的 LLM 呼叫單元（可選擇是否使用 tool） | `Router`, `Composer`, `RiskCheck` |
| **Workflow** | 一份 YAML/JSON 設定，定義 agents 的順序、資料流、條件分支 | `cs_default_v1.yaml` |
| **Tool** | Agent 可呼叫的 function（KB 檢索、外部 API、計算等） | `KBSearch`, `TicketCreate` |
| **ChatRoom** | 一個進行中的對話 session，綁定某個 workspace 的 workflow | room `#1042` 屬於 `cs` |
| **AgentTrace** | 一次 workflow 執行的完整紀錄（每個 agent 的 in/out/latency） | 可重播、可審計 |

### 5.2 關鍵設計原則
- **Workspace 是最大的 scoping 單位**：KB、agent、workflow、room 全部 scoped to workspace。
- **Workflow 是配置，不是 code**：新增/修改流程不需 redeploy。
- **Agent 是有 schema 的 function**：input/output 都有 Pydantic schema。
- **Tool 與 Agent 分開**：Agent 是「決策」，Tool 是「動作」。

---

## 6. 系統架構

```
+--------------------+      WS / REST       +-----------------------------+
|  Chat UI           | <------------------> |  FastAPI Backend            |
|  (Vue3, per dept)  |                      |  - Room hub (WS)            |
+--------------------+                      |  - REST: rooms / messages   |
                                            |  - Admin: workspaces /      |
+--------------------+      REST            |    workflows / KB / agents  |
|  Admin / Designer  | <------------------> |                             |
|  (Vue3)            |                      +--------------+--------------+
+--------------------+                                     |
                                                           v
                                       +-------------------+-------------------+
                                       |  Workflow Runtime (Orchestrator)     |
                                       |  - load workflow.yaml                |
                                       |  - resolve variable bindings         |
                                       |  - dispatch agents (serial/parallel) |
                                       |  - emit AgentTrace                   |
                                       +-------------------+-------------------+
                                                           |
                          +--------------+-----------------+----------------+--------------+
                          v              v                 v                v              v
                  +---------------+ +-----------+   +-------------+  +-------------+ +-----------+
                  | Agent Registry| | Tool      |   | KM Service  |  | LLM Provider| | Trace     |
                  | (Router,      | | Registry  |   | (per-WS KB) |  | Abstraction | | Store     |
                  |  Knowledge,   | | (KBSearch,|   | ChromaDB +  |  | Mock/Ollama |  (SQLite)  |
                  |  Composer,...)| |  Ticket)  |   | bge-m3      |  | Gemini/Groq |           |
                  +---------------+ +-----------+   +-------------+  +-------------+ +-----------+
```

### 三層分工
1. **Platform Layer**：Workspace、Workflow、Agent Registry、Tool Registry。
2. **Runtime Layer**：Workflow Orchestrator、LLM Provider、KM Service。
3. **Interaction Layer**：WebSocket chat rooms、Admin REST API。

---

## 7. Agent / Workflow / KM 設計（核心三章）

### 7.1 Agent 設計

#### 7.1.1 Agent 的結構
每個 agent 是 `BaseAgent` 的實作，有明確 input/output schema：

```python
# backend/app/agents/base.py
from abc import ABC, abstractmethod
from pydantic import BaseModel

class AgentContext(BaseModel):
    workspace_id: str
    room_id: str
    trace_id: str
    history: list[dict]            # 對話歷史
    variables: dict                # workflow 累積的變數

class BaseAgent(ABC):
    id: str                        # 'router', 'knowledge', ...
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]

    @abstractmethod
    async def run(self, ctx: AgentContext, input: BaseModel) -> BaseModel: ...
```

#### 7.1.2 內建 Agent 類型（Phase 1~4 全部實作）

| Agent | 職責 | Input | Output | 是否用 LLM | 可選 Tool |
|-------|------|-------|--------|----------|----------|
| `RouterAgent` | 分類意圖 | message + history | `{intent, category, confidence}` | Yes | — |
| `KnowledgeAgent` | RAG 檢索 | query + filter | `{docs: [{title, chunk, score}]}` | No | KBSearchTool |
| `PolicyAgent` | 合規檢核 | intent, category | `{violations, citations}` | Yes | PolicyLookupTool |
| `ToneAgent` | 語氣建議 | history, sentiment | `{tone, rationale}` | Yes | — |
| `RiskAgent` | 風險標註 | composed inputs | `{risk_level, reasons}` | Yes | — |
| `ComposerAgent` | 最終生成 | all upstream | `{reply, citations}` | Yes | — |
| `TicketDecisionAgent` | 判斷是否要開單 (IT 部門用) | solution_text | `{should_create_ticket, summary}` | Yes | TicketCreateTool |
| `ClauseAnalyzerAgent` | 合約條款分析 (法務部門用) | clause_text | `{type, risk, suggestion}` | Yes | — |

**設計重點**：
- Agent 是 platform 提供的「料」，workflow 是「食譜」，不同部門組出不同菜。
- 加新 Agent = 寫一個 class + 註冊到 registry，**不用改 workflow runtime**。

### 7.2 Workflow 設計

#### 7.2.1 Workflow as Config (YAML)
這是整個平台的靈魂。每個 workspace 有一份 workflow.yaml：

```yaml
# workspaces/cs/workflow.yaml
id: cs_default_v1
workspace: cs
description: 客服部門預設流程
trigger: on_user_message

steps:
  - id: route
    agent: router
    input:
      message: $event.message
      history: $context.history
    output: intent

  - id: retrieve
    agent: knowledge
    input:
      query: $event.message
      kb: cs.faq                       # 該 workspace 的 KB
      filter:
        category: $intent.category
      top_k: 5
    output: docs

  - id: policy
    agent: policy
    input:
      intent: $intent
      category: $intent.category
    output: compliance
    parallel_with: [retrieve]          # 與 retrieve 並行

  - id: tone
    agent: tone
    input:
      history: $context.history
    output: tone_hint

  - id: compose
    agent: composer
    input:
      message: $event.message
      docs: $docs
      compliance: $compliance
      tone: $tone_hint
    output: reply

emit:
  type: ai_suggestion
  payload:
    draft: $reply.text
    citations: $reply.citations
    risks: $compliance.violations
    trace: $trace
```

#### 7.2.2 變數綁定規則
- `$event.*`：觸發事件的資料（例如 user message）
- `$context.*`：對話 context（history、workspace info）
- `$<step_id>` 或 `$<output_name>`：上游 step 的輸出
- `parallel_with`：標記與哪些 step 同時跑（DAG hint）

#### 7.2.3 Workflow Runtime（Orchestrator）
```
load workflow.yaml
↓
build DAG (依 parallel_with / input 依賴)
↓
for each ready node:
    resolve inputs (從 $bindings 取值)
    dispatch agent.run(ctx, input)
    record AgentTrace
    把 output 寫回 variables
↓
emit final event 到 WebSocket
```

#### 7.2.4 不同部門範例

```yaml
# workspaces/it/workflow.yaml （簡化）
steps:
  - id: triage
    agent: router
    output: intent
  - id: search
    agent: knowledge
    input: { kb: it.runbook, query: $event.message }
    output: docs
  - id: solution
    agent: composer
    input: { docs: $docs, message: $event.message }
    output: reply
  - id: ticket_decide
    agent: ticket_decision           # IT 專屬
    input: { solution: $reply }
    output: ticket
```

```yaml
# workspaces/hr/workflow.yaml （簡化）
steps:
  - id: intent
    agent: router
    output: intent
  - id: policy_lookup
    agent: knowledge
    input: { kb: hr.policy, query: $event.message }
    output: docs
  - id: empathy
    agent: tone
    input: { history: $context.history }
    output: tone_hint
  - id: compose
    agent: composer
    input: { docs: $docs, tone: $tone_hint }
    output: reply
```

> **面試亮點**：「我可以五分鐘新增一個部門 —— 寫一份 YAML，ingest 文件，就跑起來了。Workflow runtime 完全不用動。」

### 7.3 KM（Knowledge Management）設計

#### 7.3.1 KM 是一等公民
不是「RAG 順便做」。KM 有自己的生命週期：
- **Ingest**：把原始文件（FAQ/SOP/PDF/MD）切塊、嵌入、入庫。
- **Organize**：metadata（部門、分類、版本、有效期）。
- **Version**：同一份文件更新時保留歷史版本，可指定 workflow 用哪個版本。
- **Scope**：每個 KB 屬於一個 workspace，跨 workspace 預設不可見。
- **Permission**（Phase 5+）：哪些 agent / workflow 可以查哪些 KB。

#### 7.3.2 資料模型
```
KnowledgeBase
  id, workspace_id, name (e.g. "cs.faq"), embedding_model,
  chunk_strategy, created_at, version

Document
  id, kb_id, source_type (faq|sop|pdf|md|url), title,
  raw_text, metadata (json: {category, tags, effective_date, ...}),
  version, status (active|archived), updated_at

Chunk
  id, document_id, chunk_index, text,
  embedding_id (在 ChromaDB 的 ref)
```

#### 7.3.3 Ingest Pipeline
```
upload doc(s) ──> normalize (md/pdf → text)
            ──> chunk (semantic, 400~600 tokens, overlap 60)
            ──> bge-m3 embed
            ──> ChromaDB upsert (collection = "ws_<id>__<kb_name>")
            ──> SQLite metadata write
            ──> emit event: kb_updated
```

#### 7.3.4 Retrieval（給 KnowledgeAgent 用）
- 必要：`workspace_id` filter（絕不跨 workspace 拿資料）
- 可選：`metadata` filter（category / version）
- 預設 Top-K = 5
- 進階（Phase 5）：rerank with `bge-reranker-v2-m3`

#### 7.3.5 KM 管理介面（Admin UI）
- 列出 workspace 下的所有 KB
- 上傳文件、查看 chunk 預覽
- 重新 ingest 單一文件
- 看某個 chunk 被哪幾次對話命中（觀測性）

### 7.4 Tool 設計

> Agent = 決策；Tool = 動作。把它分開是 platform 思維的關鍵。

#### 7.4.1 Tool Registry
```python
# backend/app/tools/base.py
class BaseTool(ABC):
    id: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]

    @abstractmethod
    async def call(self, ctx: AgentContext, input: BaseModel) -> BaseModel: ...
```

#### 7.4.2 內建 Tool
| Tool | 用途 | 使用者 (Agent) |
|------|------|--------------|
| `KBSearchTool` | 向量檢索 | KnowledgeAgent |
| `PolicyLookupTool` | 條文檢索（規則庫） | PolicyAgent |
| `TicketCreateTool` | Mock 開單（寫到 SQLite） | TicketDecisionAgent |
| `WebFetchTool`（選配） | 抓網頁 | KnowledgeAgent |

#### 7.4.3 Phase 5 進階：LLM Tool Calling
讓 LLM 直接決定要呼叫哪個 tool（OpenAI/Gemini function calling format）。
這個放最後做，因為要的是 platform 骨架先穩。

---

## 8. MVP 分階段（重新規劃）

> 圍繞 KM / Agent / Workflow 三條主線。

### Phase 1 — Skeleton + 單一 hard-coded workflow
端到端通：客戶送訊息 → workflow 跑 → 回 mock 建議。

- [ ] FastAPI + WebSocket Hub（單一 room）
- [ ] Vue3 chat UI（先不分部門）
- [ ] `BaseAgent`、`AgentContext`、`BaseTool` 介面定義
- [ ] 一個 hard-coded workflow：Router(mock) → Composer(mock)
- [ ] SQLite：conversations, messages, agent_traces

**驗收**：能在 UI 看到「使用者訊息 → AI 草稿 + trace」。

### Phase 2 — LLM Provider 抽象層
- [ ] `LLMProvider` interface
- [ ] Mock / Ollama / Gemini 三 providers
- [ ] Router、Composer 接上真實 LLM
- [ ] Trace 顯示 model / latency / tokens

### Phase 3 — KM 基礎（單一 KB）
- [ ] `KnowledgeBase`、`Document`、`Chunk` schema
- [ ] Ingest 腳本（FAQ JSON → chunks → ChromaDB）
- [ ] KnowledgeAgent + KBSearchTool
- [ ] UI 顯示「知識來源」卡片

### Phase 4 — Workspace + 多部門
- [ ] `Workspace` 概念落地（DB + API + UI 切換）
- [ ] KB 綁定到 workspace（命名 `ws_<id>__<kb>`）
- [ ] ChatRoom 綁定 workspace
- [ ] UI 加上 workspace selector
- [ ] Seed 2 個部門：CS、IT

### Phase 5 — Workflow as Config
- [ ] Workflow YAML schema 定義（Pydantic）
- [ ] Workflow Orchestrator（變數綁定、parallel hint）
- [ ] 每個 workspace 一份 workflow.yaml
- [ ] 移除 hard-coded workflow

**這是整個平台「成立」的一刻**。

### Phase 6 — 完整 Agent 套件 + 4 部門
- [ ] Policy / Tone / Risk / TicketDecision / ClauseAnalyzer agents
- [ ] 4 個部門全部就緒（CS / HR / IT / Legal）
- [ ] 每個部門對應的 KB 與 seed 文件

### Phase 7 — Admin UI（最大加分項）
- [ ] Workspace 管理頁
- [ ] Workflow 檢視頁（顯示 YAML + DAG 圖）
- [ ] KB 管理頁（上傳、預覽 chunk、reingest）
- [ ] Trace explorer（看歷史對話的 pipeline）

### Phase 8 — Demo Polish
- [ ] 4 個部門各 2~3 個典型對話腳本
- [ ] Demo GIF、README、架構圖
- [ ] 一份「新增第 5 個部門」的教學文檔（展示可擴展性）

---

## 9. 技術選型（沿用前版，補強）

### Frontend
- Vue 3 + Composition API + Pinia + Tailwind + Vite
- WebSocket native（無 socket.io）
- 圖：Workflow DAG 用 `vue-flow` 或乾脆畫 SVG

### Backend
- FastAPI（async + WebSocket）
- Pydantic v2（schema 核心）
- SQLAlchemy 2.0 async
- SQLite (dev) → Postgres-ready
- YAML：`pyyaml`

### AI / KM
- LLM Provider：Mock / Ollama / OpenRouter / Gemini / Groq
- Embedding：`BAAI/bge-m3`
- Vector DB：ChromaDB（local persist，per-workspace collection）
- Reranker（選配 Phase 5+）：`bge-reranker-v2-m3`

### 不選什麼（要會講）
| 不選 | 理由 |
|------|------|
| LangChain / LangGraph | 抽象過重，會掩蓋你自己設計的 platform 價值 |
| CrewAI / AutoGen | 同上，且我們的 workflow 已 config-driven，不需要 |
| Pinecone / Weaviate | 零成本起步用 Chroma |
| Redis pub/sub | 單機 WS 夠用，不過度設計 |
| 拖拉式 workflow builder | 重點是 runtime，不是 UI 玩具 |

---

## 10. LLM Provider 抽象層

（沿用前版 §9，重點是 `LLMProvider` interface + Factory + env 切換。）

新增：
- 每個 **agent definition** 可指定預設 model（例如 Router 用便宜模型，Composer 用強模型）。
- Provider 可在 workspace 層級覆寫（例如 Legal 部門堅持用 Gemini）。

```yaml
# workflow.yaml 片段
overrides:
  router: { provider: groq, model: llama-3.1-8b }
  composer: { provider: gemini, model: gemini-1.5-pro }
```

---

## 11. 資料庫 Schema

```
workspaces
  id, name, description, created_at, status

knowledge_bases
  id, workspace_id, name, embedding_model, version, created_at

documents
  id, kb_id, source_type, title, raw_text, metadata(json),
  version, status, updated_at

chunks
  id, document_id, chunk_index, text, embedding_ref

agents (Optional — 也可純 Python 註冊)
  id, workspace_id (nullable=global), name, type, config(json)

workflows
  id, workspace_id, name, version, yaml_content, is_active, created_at

chat_rooms
  id, workspace_id, status (open|closed),
  participants(json), created_at, closed_at, summary

chat_messages
  id, room_id, sender_role (user|agent_ai|operator),
  content, created_at, trace_id (nullable)

agent_traces
  id, room_id, message_id,
  workflow_id, steps(json: [{agent_id, input, output, latency_ms, error}]),
  total_latency_ms, created_at

tool_invocations
  id, trace_id, step_id, tool_id, input(json), output(json),
  latency_ms, created_at

tickets (IT 部門 demo 用)
  id, room_id, summary, status, created_at
```

---

## 12. API 設計

### 12.1 對外（Chat 端）
```
POST   /api/workspaces/{ws}/rooms                 開房
POST   /api/rooms/{id}/messages                   送訊息（同時也用 WS）
GET    /api/rooms/{id}                            取對話 + trace
POST   /api/rooms/{id}/close                      關房 + 摘要

WS     /ws/rooms/{id}                             收 ai_suggestion / operator_hint
```

### 12.2 Admin（Platform 端）
```
GET    /api/admin/workspaces                      列出
POST   /api/admin/workspaces                      建立
GET    /api/admin/workspaces/{ws}/workflow        取 workflow yaml
PUT    /api/admin/workspaces/{ws}/workflow        更新 workflow yaml（驗證 schema）
GET    /api/admin/workspaces/{ws}/kbs             列 KB
POST   /api/admin/workspaces/{ws}/kbs             建立 KB
POST   /api/admin/kbs/{kb}/documents              上傳 doc → 觸發 ingest
GET    /api/admin/kbs/{kb}/documents/{doc}/chunks 預覽 chunk

GET    /api/admin/agents                          列出可用 agent 類型
GET    /api/admin/tools                           列出可用 tool

GET    /api/admin/traces?workspace=...&q=...      Trace explorer
```

---

## 13. UI / UX 規劃

### 13.1 兩種 App（同一份前端，路由切換）
1. **Chat App**：使用者跟 AI 對話（依 workspace 不同樣貌）
2. **Admin / Designer App**：設定 workspace、看 workflow、管理 KB

### 13.2 Chat App
頂部 workspace selector（demo 用），主畫面是 chat + AI Trace 側欄。

```
[Workspace: 客服 ▾]  [Room #1042]                       [AI Trace ▾]
─────────────────────────────────────────────────────────
[user]  70歲可以申請車貸嗎？
[AI]    您好，70 歲以上仍可協助評估…
        [Citations: SOP-車貸 v2.3, FAQ #128]
─────────────────────────────────────────────────────────
[input box]
```

側欄 AI Trace：每個 step 一張卡片（agent name / latency / 展開看 in/out）。

### 13.3 Admin App（這頁會讓面試官眼睛一亮）

**Workspace 詳情頁**
```
+--------------------------------------------------+
| Workspace: hr                                    |
| Workflow [edit yaml] [view DAG]                  |
| ┌────────────────────────────────────┐           |
| │  router → policy_lookup → empathy  │           |
| │              → composer            │           |
| └────────────────────────────────────┘           |
|                                                  |
| Knowledge Bases                                  |
|   - hr.policy   (32 docs, last ingest: 3h ago)  |
|   - hr.handbook (12 docs)                       |
|                                                  |
| Agents in use: router, knowledge, tone, composer|
| Tools in use:  KBSearchTool, PolicyLookupTool   |
|                                                  |
| Recent traces  [Open Trace Explorer →]          |
+--------------------------------------------------+
```

**Trace Explorer**：可挑某次對話，重看每個 agent 怎麼判斷的 — 這是「可審計」的核心展示。

---

## 14. RAG / KM 詳細設計

### 14.1 Collection 命名規則
每個 workspace 的 KB 在 ChromaDB 是獨立 collection：
```
ws_cs__faq
ws_cs__sop
ws_hr__policy
ws_it__runbook
ws_legal__contracts
```
KnowledgeAgent 永遠強制 prefix `ws_<workspace_id>__`，**防止跨部門檢索**。

### 14.2 Chunk 策略
- 預設 size 500 tokens，overlap 60
- FAQ：一條 Q&A 一個 chunk（不切）
- SOP / PDF：semantic split（先用段落 + 句界，後續可換 SemanticChunker）

### 14.3 Metadata（每個 chunk 必帶）
```json
{
  "workspace": "cs",
  "kb": "faq",
  "doc_id": "doc_128",
  "title": "高齡申貸條件",
  "category": "loan",
  "version": "v2.3",
  "effective_date": "2025-01-01"
}
```
Retrieval 時可依 `category` / `version` 過濾。

### 14.4 觀測性
每個 chunk 紀錄被哪幾個 trace 命中（用 `tool_invocations` 反查），admin UI 可看「最常被引用的 chunk」、「從未被命中的 chunk」 —— 這是 KM 健康度指標。

---

## 15. 部署方案（完整版）

### 15.1 部署目標與限制

**目標**
- 零成本（個人 side project，不想為 demo 付 monthly fee）
- 一鍵打開（面試官點連結 30 秒內看到畫面）
- 可重現（任何人 fork repo 都能 deploy）
- 故障可降級（LLM 掛了還能 demo、KB 掛了還能聊）

**已知限制（免費 PaaS 通病）**
- Idle 後會 sleep（冷啟動 30~60 秒）
- RAM 多半 ≤ 512MB（少數有 16GB）
- 無免費 persistent disk
- CPU 慢，跑 embedding 會卡

### 15.2 元件部署位置

| 元件 | 推薦平台 | 備援 | 理由 |
|------|---------|------|------|
| Frontend (Vue3) | **Cloudflare Pages** | Vercel / Netlify | 真正免費、edge 部署、自動 HTTPS |
| Backend (FastAPI) | **Hugging Face Spaces (Docker)** | Render Free / Fly.io | 16GB RAM 給足 embedding 模型 |
| Vector DB (Chroma) | **與 backend 同容器（persist）** | — | 不獨立服務，省一個元件 |
| Metadata DB (SQLite) | **與 backend 同容器** | — | seed-on-boot 重建 |
| LLM | **env 切換**（Mock / Gemini / Groq） | Ollama (local) | 預設 Mock 確保不會掛 |
| Trace / Log | stdout + HF Spaces logs | Sentry Free | demo 階段夠用 |

### 15.3 後端託管平台比較

| 平台 | Free RAM | Idle Sleep | Persistent Disk | 適合 ML | 對這專案的建議 |
|------|---------|-----------|-----------------|--------|--------------|
| **HF Spaces (Docker)** | 16GB | 48h 無流量 sleep | 無（付 $5/mo 可加 20GB） | ★★★★★ | **首選**，RAM 充裕、ML 語境合適 |
| **Render Free** | 512MB | 15 分鐘 sleep | 無（付 $7/mo 可加） | ★★ | 備案，要採「離線 embedding」策略 |
| **Fly.io Free** | 256MB×3 | 不 sleep | 有（3GB free） | ★ | RAM 太小，跑 Chroma 吃緊 |
| **Railway** | — | — | — | — | 已取消免費方案 |
| **本機 + Cloudflare Tunnel** | 無上限 | 不 sleep（你電腦得開機） | 無上限 | ★★★★★ | 真實 demo 最穩，但要你電腦在線 |

### 15.4 環境變數與 Secrets

```bash
# 平台選擇
MODE=demo                     # demo | cloud | local
LLM_PROVIDER=mock             # mock | ollama | gemini | groq | openrouter

# LLM Keys（依 provider 而定，secret store）
GEMINI_API_KEY=...
GROQ_API_KEY=...
OPENROUTER_API_KEY=...

# 路徑（容器內）
CHROMA_PERSIST_DIR=/data/chroma
SQLITE_PATH=/data/app.db
WORKSPACES_DIR=/app/workspaces      # seed 資料在 repo 裡

# 行為旗標
SEED_ON_BOOT=true
ENABLE_RERANKER=false          # Phase 5+ 才開
LOG_LEVEL=INFO

# CORS（frontend 網域）
ALLOWED_ORIGINS=https://aisp.pages.dev,http://localhost:5173
```

**Secret 管理**
- HF Spaces：在 Space settings 設 Secrets，環境變數自動注入
- Render：Dashboard 設 Environment Variables
- 本地：`.env` + python-dotenv（**不進 git**，加 `.gitignore`）

### 15.5 資料持久化策略（重點）

**核心思路：把可變資料分三類，分別處理。**

| 資料類型 | 範例 | 策略 |
|---------|------|------|
| **Embedding / 索引**（重，但只讀） | ChromaDB persist files | **離線預生成 + ship 進 Docker image** |
| **Seed 結構性資料**（小，可重建） | Workspace 設定、KB 文件 | repo 中 `workspaces/` 目錄，啟動時 seed |
| **執行期資料**（會增長） | chat_messages, agent_traces | 容器內 SQLite，demo 結束可丟 |

**為什麼這樣分？**
- 免費 PaaS 沒 persistent disk，所以「能放進 image 就放進 image」
- Chunk + embedding 是「冷資料」，不會在生產動態增加，預生成最划算
- Demo 用的 chat 紀錄丟掉沒差（每次 demo 重新開始更乾淨）

**具體做法**
```
# 本地（或 CI）執行
$ python scripts/build_embeddings.py
  → 讀取 workspaces/*/knowledge/
  → 用 bge-m3 切塊 + 嵌入
  → 寫入 ./data/chroma/  (ChromaDB persist 格式)
  → 寫入 ./data/seed.sqlite (workspace + KB metadata)

# Docker build 時 COPY 進 image
COPY ./data /data
```
這樣 runtime container **完全不需要載 bge-m3 模型**（除非要支援 demo 過程中即時 ingest 新文件）。

### 15.6 Seed-on-Boot 流程

容器啟動時自動跑：

```
1. 檢查 /data/app.db 是否存在
   → 不存在：從 /data/seed.sqlite 複製，或從 workspaces/*.yaml 重建
2. 檢查 /data/chroma/ 是否有 collection
   → 沒有：從 image 內 seed 還原（COPY 進來時應已就緒）
3. 載入 workspaces/<id>/workflow.yaml，驗證 schema
4. 註冊所有 agents 與 tools
5. 啟動 FastAPI + WebSocket
```

對應 `backend/app/main.py` 的 startup hook：
```python
@app.on_event("startup")
async def boot():
    if os.getenv("SEED_ON_BOOT", "true").lower() == "true":
        await seed_workspaces()
        await ensure_kb_collections()
    register_agents()
    register_tools()
```

### 15.7 三種運行模式（用 ENV 切換）

| 模式 | 用途 | `LLM_PROVIDER` | 特性 |
|------|------|----------------|------|
| `MODE=demo` | 公開展示、面試 | `mock` 或 `groq` | seed 4 部門，永遠跑得動 |
| `MODE=cloud` | 部署到 HF / Render 跑真實 LLM | `gemini` / `groq` | 需要 API key |
| `MODE=local` | 開發、完全離線 | `ollama` | 跑本機 Ollama |

切換只需改一個環境變數，code 不動。

### 15.8 Dockerfile（後端範例）

```dockerfile
# backend/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安裝依賴
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

# 應用碼
COPY app ./app
COPY workspaces /app/workspaces

# 預生成的 embedding（重點：image 自帶資料）
COPY data /data

ENV PYTHONUNBUFFERED=1 \
    CHROMA_PERSIST_DIR=/data/chroma \
    SQLITE_PATH=/data/app.db \
    WORKSPACES_DIR=/app/workspaces

EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
```

> HF Spaces 預設聽 `7860`，Render 預設 `10000`（讀 `$PORT`），可在 CMD 用 `${PORT:-7860}` 兼容。

### 15.9 CI/CD Pipeline（GitHub Actions）

**三條獨立 workflow**：

```yaml
# .github/workflows/backend.yml
name: Backend CI/CD
on:
  push:
    paths: ['backend/**', 'workspaces/**']
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install uv && uv sync
      - run: uv run pytest backend/tests
      - run: uv run ruff check backend
  build-embeddings:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python scripts/build_embeddings.py
      - uses: actions/upload-artifact@v4
        with: { name: data, path: data/ }
  deploy-hf:
    needs: build-embeddings
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with: { name: data, path: data/ }
      - name: Push to HF Spaces
        env: { HF_TOKEN: ${{ secrets.HF_TOKEN }} }
        run: |
          git remote add hf https://user:${HF_TOKEN}@huggingface.co/spaces/<user>/aisp
          git push hf main --force
```

```yaml
# .github/workflows/frontend.yml — Cloudflare Pages 用 GitHub 直連即可，不需 workflow
```

### 15.10 冷啟動與 Keep-alive 策略

**問題**：HF Spaces / Render 免費版 idle 後睡，第一次請求要等 30~60 秒。

**對策（從便宜到貴）**
1. **接受冷啟動**，在前端首頁顯示「初次載入中…約 30 秒」的友善 loading，並先 ping `/health` 觸發 wake-up。
2. **Cron-job.org**（免費）每 14 分鐘 ping `/health`。注意 HF Spaces 對 ToS 較嚴格，HF 偏好讓 Space 自然休眠。
3. **GitHub Actions schedule**（每 10 分鐘觸發 health ping）— 但會用掉免費 minutes。
4. **本機 + Cloudflare Tunnel**：你電腦開著就不睡，demo 期間用這個最穩。

**Demo 前 5 分鐘**：手動點開 backend URL 預熱，等回 `200` 再開始 demo。

### 15.11 故障降級（Graceful Degradation）

| 故障點 | 偵測 | 降級行為 |
|--------|------|---------|
| LLM Provider 超時 / 5xx | 3 秒 timeout | 切到 `MockProvider`，UI 標示「使用備援回覆」 |
| KB 檢索失敗 | catch exception | KnowledgeAgent 回空陣列，Workflow 繼續 |
| 某個 Agent 拋錯 | per-step try/except | Trace 記錯，下游 agent 收到空 input，Composer 走備案 prompt |
| WebSocket 斷線 | 前端心跳 | 自動重連 + 重抓最新訊息 |
| Workflow YAML 解析失敗 | startup 時驗證 | 啟動就 fail，不要部署壞掉的版本 |

**原則**：寧可給差一點的回覆，也不要白屏。

### 15.12 Demo 前置 Checklist

**Demo 前一天**
- [ ] 跑一次完整 CI/CD，確認所有 workflow 綠燈
- [ ] HF Spaces / Render dashboard 確認最新 image 已部署
- [ ] 4 個 workspace 都用真實 demo 訊息走一次
- [ ] 錄一份 3 分鐘 demo 影片（Loom）當保險
- [ ] 把 demo URL、admin URL、影片連結放在 README 頂部

**Demo 前 30 分鐘**
- [ ] 開 backend URL 預熱，等 `/health` 200
- [ ] 開 admin UI 確認 4 個 workspace、所有 KB 都在
- [ ] 切到 Mock provider 跑一次（避免 LLM 額度問題）
- [ ] 再切到 Groq / Gemini 跑一次（真實效果）

**Demo 前 5 分鐘**
- [ ] 三個瀏覽器分頁：CS chat、IT chat、Admin
- [ ] DevTools console 清空、網路面板開好（萬一要 troubleshoot）
- [ ] Loom 備援影片在桌面，遇到災難立刻切

**Demo 收尾**
- [ ] 收尾時直接打開 GitHub repo，秀架構圖與 README
- [ ] 提供「自己 fork + deploy」的一行指令連結

### 15.13 部署成本試算

| 場景 | 月成本 |
|------|--------|
| 完全免費（HF Spaces + CF Pages + Mock LLM） | **$0** |
| 加雲端 LLM（Groq / Gemini 免費額度內） | **$0** |
| 加 persistent disk（HF $5 或 Render $7） | $5~7 |
| 升級不 sleep（Render Starter $7） | $7 |
| 全套升級 + 監控 | ~$15 |

**結論**：side project demo 階段堅持 **$0** 完全可行。

---

## 16. Repository 結構

```
AI_SP/
├── README.md
├── PLAN.md
├── docs/
│   ├── architecture.md
│   ├── concepts.md             # Workspace / Agent / Workflow / KM 名詞表
│   ├── workflow-spec.md        # YAML schema 參考
│   ├── add-a-new-department.md # 「五分鐘新增部門」教學
│   └── diagrams/
├── workspaces/                 # seed workspace（直接放 repo 裡，啟動時 load）
│   ├── cs/
│   │   ├── workflow.yaml
│   │   └── knowledge/
│   │       ├── faq.json
│   │       └── sop/
│   ├── hr/
│   ├── it/
│   └── legal/
├── prompts/
│   ├── router.md
│   ├── composer.md
│   ├── policy.md
│   └── ...
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── chat.py
│   │   │   └── admin.py
│   │   ├── ws/
│   │   ├── workflow/
│   │   │   ├── schema.py       # Pydantic models for workflow.yaml
│   │   │   ├── loader.py
│   │   │   └── orchestrator.py
│   │   ├── agents/
│   │   │   ├── base.py
│   │   │   ├── registry.py
│   │   │   ├── router.py
│   │   │   ├── knowledge.py
│   │   │   ├── policy.py
│   │   │   ├── tone.py
│   │   │   ├── risk.py
│   │   │   ├── composer.py
│   │   │   ├── ticket_decision.py
│   │   │   └── clause_analyzer.py
│   │   ├── tools/
│   │   │   ├── base.py
│   │   │   ├── registry.py
│   │   │   ├── kb_search.py
│   │   │   ├── policy_lookup.py
│   │   │   └── ticket_create.py
│   │   ├── km/
│   │   │   ├── ingest.py
│   │   │   ├── chunker.py
│   │   │   ├── store.py        # Chroma wrapper
│   │   │   └── retriever.py
│   │   ├── providers/
│   │   │   ├── base.py
│   │   │   ├── factory.py
│   │   │   ├── mock.py
│   │   │   ├── ollama.py
│   │   │   └── gemini.py
│   │   ├── models/             # SQLAlchemy
│   │   ├── schemas/            # Pydantic
│   │   └── db/
│   ├── tests/
│   └── Dockerfile
└── frontend/
    ├── src/
    │   ├── pages/
    │   │   ├── ChatPage.vue
    │   │   ├── AdminWorkspaces.vue
    │   │   ├── AdminWorkflow.vue
    │   │   ├── AdminKB.vue
    │   │   └── TraceExplorer.vue
    │   ├── components/
    │   │   ├── WorkspaceSelector.vue
    │   │   ├── ChatWindow.vue
    │   │   ├── AiTracePanel.vue
    │   │   └── WorkflowDag.vue
    │   ├── stores/
    │   └── ws/
    └── vite.config.ts
```

---

## 17. 開發 Roadmap（重新對齊）

6~8 週，每週 8~12h。

| 週次 | 階段 | 主要交付 |
|------|------|---------|
| W1 | Phase 1+2 | Skeleton + Provider 抽象 + hard-coded workflow 跑通 |
| W2 | Phase 3 | KM 基礎（單一 KB）+ KnowledgeAgent 上線 |
| W3 | Phase 4 | Workspace 落地，KB 與 Room scoped；CS / IT 兩部門 |
| W4 | Phase 5 | Workflow as Config（YAML loader + orchestrator） |
| W5 | Phase 6 | 補齊全部 agents + HR / Legal 部門 |
| W6 | Phase 7a | Admin UI：workspace + workflow viewer + KB manager |
| W7 | Phase 7b + 8a | Trace Explorer + 4 部門 demo data |
| W8 | Phase 8b | README、架構圖、Demo GIF、教學文檔 |

### 每週驗收（自我交付）
週末錄 2 分鐘影片：**「這週新增了什麼能力？」** 看自己能不能講清楚。

---

## 18. Demo Script（多部門版，5~6 分鐘）

### 開場 30s
> 「這是一個企業 AI Agent 平台。
>  核心是三個一等公民：Knowledge、Agent、Workflow。
>  每個部門可以用 YAML 設定自己的流程，掛上自己的知識庫，
>  跑在自己的聊天室裡。」

### Step 1（1m）— CS 部門
- 切到「客服」workspace
- 客戶問：「70歲可以申請車貸嗎？」
- AI 回覆 + Citations + 右側顯示完整 Trace
- 「這是 5 個 agent 跑完的結果，每一步都可看可重播。」

### Step 2（1m）— 切到 IT 部門
- 切換 workspace 到「IT Helpdesk」
- 員工問：「VPN 連不上」
- 走的是 **完全不同的 workflow**（Triage → KBSearch → Solution → TicketDecision）
- TicketDecisionAgent 判斷「需要開單」 → 呼叫 `TicketCreateTool` → UI 顯示 ticket #
- **強調**：「同一個 runtime，不同 config，行為完全不一樣。」

### Step 3（1m）— Admin / Workflow Designer
- 打開 IT 的 workflow.yaml
- 顯示 DAG 圖
- 「想加一個 sentiment agent？改 YAML，存檔，下一句訊息就生效。」
- 現場示範（已準備好 toggle）

### Step 4（1m）— KM 管理
- 進 HR 部門的 KB 管理頁
- 「政策更新了一條」 → 上傳 → ingest → 預覽 chunk
- 馬上去 HR 聊天室問相關問題 → 拿到新答案 + 引用新文件

### Step 5（1m）— Trace Explorer
- 打開歷史對話的 trace
- 展開某次 Composer agent 的 input / output / 用的 prompt / model / latency
- 「這在金融、醫療、法務場景是必要的 —— 每個決策都可審計。」

### 收尾 30s（最關鍵）
> 「我想展示的不是『AI 能做什麼』，
>  而是『AI 怎麼變成企業可組裝、可管理、可演進的元件』。
>
>  Agent 是 Python 類；
>  Workflow 是 YAML 設定；
>  Knowledge 是受版本控管的資產；
>  整個平台多部門隔離、可審計、可重播。
>
>  加新部門 = 寫一份 YAML + 上傳文件，五分鐘搞定。」

---

## 19. 風險與取捨

| 風險 | 應對 |
|------|------|
| Workflow runtime 寫得太複雜 | Phase 5 先只支援 linear + parallel hint，不做條件分支與 loop |
| 4 個部門做不完 | 縮到 2~3 個，但 workflow / KB 抽象必須做完 |
| LLM 真實效果不穩 | Demo 預設 Mock + 預錄真實回覆；切到 Groq 拿低延遲 |
| Admin UI 太重 | 優先順序：Workspace list > Workflow viewer > KB manager > Trace explorer > Editor |
| 過度工程化 | 不做 Auth、不做多 user role、不做 WebSocket 跨服務、不做 K8s |

### 紅線（堅決不做）
- 不做拖拉式 workflow builder（重點是 runtime，不是 UI 噱頭）
- 不做使用者註冊登入（demo 用 seed 帳號）
- 不做正式 RBAC（workspace scoping 夠用）

---

## 20. 延伸方向（給面試官講「下一步」）

依優先序：

1. **LLM Tool Calling**：讓 Agent 動態決定要呼叫哪個 tool（function calling）。
2. **Workflow 條件分支與 Loop**：例如 RiskAgent 判斷高風險時，回頭再跑一次 Composer。
3. **Evaluation Harness**：每個 workflow 配 test set，自動跑 regression。
4. **Workflow Versioning + A/B**：兩份 workflow 同時跑、比較結果。
5. **External Tool Integrations**：真實連 Jira / Slack / CRM。
6. **Permission Model**：哪個 agent 能呼叫哪個 tool / KB（policy as code）。
7. **Streaming Compose**：Composer 邊生成邊推 WS。

---

## 21. 真正要傳達的價值（一行版）

> **我不是在做 AI 應用，我在做 AI Agent 的 runtime 與管理層。**

這就是這個專案要證明的事。

---

## 附錄 A — 第一週 Checklist

- [ ] `git init` 與 repo 結構（依 §16）
- [ ] `BaseAgent`、`BaseTool`、`AgentContext` 三個 interface 先定好
- [ ] 一個假的 Router、一個假的 Composer（都回 mock 字串）
- [ ] FastAPI WebSocket + Vue chat UI 跑通
- [ ] 訊息進來 → 跑 hard-coded 兩步 workflow → trace 寫進 DB → WS 推回前端
- [ ] README 寫一行：「Day 1: agent runtime skeleton up。」

**第一週的目標只有一個：把 Agent runtime 的骨架立起來，YAML config 與 workspace 都還沒進來，但 BaseAgent 的 contract 已經正確。**

---

## 附錄 B — 名詞速查（給自己背的）

| 對外（面試）這樣講 | 內部實際是 |
|-------------------|----------|
| Agent runtime | `BaseAgent.run()` + orchestrator |
| Workflow engine | YAML loader + DAG dispatcher |
| KM service | ChromaDB 包裝 + ingest pipeline |
| Multi-tenant scoping | `workspace_id` filter everywhere |
| Trace & audit | `agent_traces` 表 + Trace Explorer UI |
| Tool registry | `BaseTool` + dict 註冊 |
| LLM provider abstraction | `LLMProvider` interface + factory |

把這張表背熟，面試問什麼都能對得上。
