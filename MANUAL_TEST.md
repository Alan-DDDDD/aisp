# AISP 專案驗證手冊

> 對應 PLAN.md 全部 phase 的實作狀態 + 前端可手測的所有流程清單。

---

## 0. 一句話總覽

AISP 是「多部門 AI Agent 平台」。**4 個部門共用同一份後端 runtime，行為差異全部由 workspace 設定（workspace.json + workflow.yaml + 知識庫）決定**。Phase 6 §22 起加上 **Self-Extending Agent — 系統遇到沒工具能解的 query，能自動寫工具、跑 sandbox、送人類審核**。

---

## 1. 規劃 vs 實作對照（最新 commit: `5c79eb7`）

| Phase | 計畫內容 | 狀態 | 驗證指標 |
|---|---|---|---|
| 1 | Skeleton + hard-coded workflow + FastAPI + Vue chat | ✅ | `/` 能對話 |
| 2 | LLM Provider 抽象 + Groq | ✅ | `.env` 設 `LLM_PROVIDER=groq` 後 chat 走真 LLM |
| 3 | KM / RAG 基礎 + ChromaDB + bge-m3 | ✅ | 啟動 log: `KB cs/faq 已存在（15 docs）` |
| 4 | Workspace 多部門（cs / hr / it / legal）| ✅ | 頂部按鈕切 workspace |
| 5 | Workflow as YAML + 自寫 DAG runtime | ✅ | `workspaces/cs/workflow.yaml` 改幾步立刻生效 |
| 6 | 完整 Agent 套件（policy / tone / risk / ticket_decision / clause_analyzer） | ✅ | trace 看到該部門對應 agent step |
| 7 | Admin UI（5 頁 + REST + PDF 上傳）| ✅ | `/admin` 各頁 |
| 8 | Demo polish（docs / Dockerfile / README）| ✅ | README 為入口 |
| 9 | 多語 embedding (bge-m3) | ✅ | log: `Initializing ... model=BAAI/bge-m3` |
| 10 | Mobile-first RWD 前端 | ✅ | 手機開仍可用 |
| 11 | 結構感知 chunker（Markdown + 法條）| ✅ | 法務 KB 查條款回 heading_path |
| 12 | Hybrid retrieval + rerank + eval harness | ✅ | `python -m scripts.run_eval` 跑得出 MRR |
| 13 | **Self-Extending Agent**（PLAN §22 M1-M7）| ✅ | `/admin/synthesis` 看得到 3 個 generated tools |
| **14** | **Chat ↔ Tool 整合 + Composer hard guard**（feature/tool-agent）| ✅ | chat 問轉換題會 USE 既有 tool 或 GAP 觸發合成 |

214 個 unit + e2e test 全綠。

---

## 2. cs workspace 完整對話流程

```
你在前端輸入訊息
  ↓ WebSocket /ws/rooms/<room_id>
Backend 觸發 cs_default_v2 workflow
  ↓
┌─ Layer 1（無依賴 — 立刻跑）
│  └─ [router] 分類意圖    Groq 8B    ~500ms
├─ Layer 2（depends_on router — 並行跑）
│  ├─ [tool_agent]  gap detect + tool dispatch  Groq 70B 多次  3-15s
│  ├─ [knowledge]   kb_search → docs            embed 0ms      ~200ms
│  ├─ [policy]      合規檢核                     Groq 8B        ~500ms
│  └─ [tone]        語氣建議                     Groq 8B        ~500ms
└─ Layer 3
   └─ [composer] 合成最終回覆 OR hard-guard 固定句  ~500ms

  ↓ WS 推回前端
ChatWindow 顯示 AI 訊息 + 點擊查看 Trace →
```

### 2.1 router

**目的**：把 user message 分到 6 個 category（loan / complaint / hr / it / legal / general）+ 一個 short_snake_case intent

**前端對應**：trace 第 1 個 step；訊息下方 badge「合規提示」/「語氣 X」等都源自下游 agent 但 trigger 在 router

### 2.2 tool_agent（**Phase 14 新增**）

**目的**：判斷現有工具能否解 user query，能就呼叫，不能就送合成

**內部流程**：

```
1. gap_detector.detect(message, workspace_id="cs")
   ├─ planner LLM 拆 step                  Groq 70B
   ├─ 每 step retrieval 找候選 tool         embedding
   ├─ similarity ≥ 0.85 → USE shortcut
   ├─ similarity ≤ 0.40 → GAP shortcut
   └─ middle → judge LLM 一次判決多 step   Groq 70B

2. 找第一個 USE step
   ├─ 有 → tool.input_schema 推 args (Groq 8B) → tool.call → tool_result
   └─ 無 USE 但有 GAP
      ├─ orchestrator.synthesize(spec)     Groq 70B 多次
      │   ├─ spec_enricher
      │   ├─ code_generator
      │   ├─ test_generator（與 code 隔離）
      │   ├─ static_check（AST whitelist）
      │   ├─ sandbox 跑 pytest
      │   └─ 最多 3 attempts
      ├─ 成功 → approval.submit → AWAITING_APPROVAL → Telegram 推訊息
      └─ 失敗 → AWAITING_HUMAN_RESCUE → Telegram 推 rescue
   ├─ 無 USE 無 GAP（全 no_tool_needed）→ 放行下游
```

**前端對應**：
- 點 trace 看 `tool_agent` step 的 Output：
  - `tool_called` 有值 → 呼叫成功
  - `tool_called=null, skipped_reason=no_tool_needed` → 沒呼叫工具，走 RAG
  - `tool_called=null, skipped_reason=awaiting_approval:<name>` → 合成成功等審
  - `tool_called=null, skipped_reason=synthesis_failed:...` → 合成失敗，看 `/admin/synthesis` rescue
  - `tool_called=null, skipped_reason=synthesis_exception:...` → LLM 失敗（例如 Groq rate limit）

### 2.3 knowledge / policy / tone

不變於 Phase 6。knowledge 把 user message 餵 kb_search（cs/faq, top_k=5），policy / tone 各跑 Groq 8B 一次。

### 2.4 composer（**Phase 14 加 hard guard**）

**邏輯**（程式碼層級保險）：
```
if (no tool_result OR tool_result 實質為空)
   AND (no relevant_docs):
    → 不呼叫 LLM
    → return "目前知識庫中沒有相關資訊，建議改詢問人工客服或對應部門。"
else:
    → 呼叫 LLM with 嚴格 prompt
    → LLM 依 [TOOL_RESULT] / [KNOWLEDGE] 區塊寫回覆
```

`_is_effectively_empty()` 把 `{"docs": [], "kb_name": "faq", "query": "x"}` 這種「我搜了什麼都沒找到」也視為空。

**前端對應**：trace 看 `composer` step 的 Input — 若 `tool_called=null` 且 `docs=[]`，Output text 必為固定句（無 LLM 創造空間，無幻覺）。

---

## 3. Admin UI 頁面對應

| 路徑 | 頁面 | 功能 |
|---|---|---|
| `/` | Chat | 與 AI 對話；右上「Admin」入 admin |
| `/admin` | Workspaces 列表 | 4 個部門卡片，每個顯示 KB / doc 數；點進去看詳情 |
| `/admin/workspaces/cs` | Workspace 詳情 | pipeline 視覺化 + workflow.yaml + KB 列表 + traces + tickets |
| `/admin/kbs/cs__faq` | KB 詳情 | 文件列表，點任一文件展開 chunks 看 embedding 切割 |
| `/admin/traces` | Trace Explorer | 全部 workspace 最近 50 筆對話，左列表右 step I/O |
| `/admin/synthesis` | **Self-Extending Agent**（Phase 13 加）| 3 個 tab：Synthesis Tasks / Generated Tools / Decision Audit |

### 3.1 Synthesis Dashboard — 3 個 tab

#### Tab: Synthesis Tasks
- 列所有合成過的 task（含失敗的）
- 每筆顯示 state badge（綠=REGISTERED / 藍=AWAITING_APPROVAL / 橘=AWAITING_HUMAN_RESCUE / 紅=FAILED）
- 點任一筆 → 右側 detail panel：
  - **Spec (enriched)** — Code Agent 拿到的補完規格
  - **Attempt history** — 每輪 sandbox 結果（pass/fail 數、錯誤訊息）
  - **Behavior observation** — sandbox 內 monkey-patch 抓到的 socket/open 活動
  - **Source code / tests** — 展開看 LLM 寫的 code 跟 tests
  - **Review history** — 誰按了 approve/reject/refine
- state=AWAITING_APPROVAL 時：右上有 **✅ Approve** / **❌ Reject** 按鈕

#### Tab: Generated Tools
- 列已 active 的工具
- 每行顯示：tool id、version、workspace、scope（workspace / global）、approved_by、approved_at
- 操作：**Promote → global** / **Deprecate**

#### Tab: Decision Audit
- 列 Phase A（gap_detector）每次決策的 audit log
- 篩選：decision（USE/COMPOSE/GAP）、route（shortcut_high / shortcut_low / judge / human / no_tool_needed）
- 點任一筆展開看完整 reasoning + candidates

---

## 4. 完整 HITL 合成流程（Telegram + Web Dashboard 雙通道）

```
chat: 100 公分換英吋
  ↓
tool_agent 發現無對應 tool
  ↓
orchestrator.synthesize → spec / code / test / sandbox
  ↓
approval.submit
  ├─ DB: 寫 ToolSynthesisTask(state=AWAITING_APPROVAL)
  └─ Telegram: notifier.notify_approval → 推訊息給 chat_id 1936181097
      ▼
  你的 Telegram:
  ┌────────────────────────┐
  │ 🔍 新工具待審核          │
  │ Tool: cm_to_inch        │
  │ 測試: ✅ 4 passed        │
  │ [✅ Approve] [❌ Reject] │
  │ [📝 Refine with hint]    │
  └────────────────────────┘
      或
  網頁 /admin/synthesis → Tasks tab → 點該 task → 右側按 Approve

  ↓ 按 Approve
ApprovalService.approve():
  ├─ 寫檔到 workspaces/generated_tools/<name>.py
  ├─ 動態 import 進 tool_registry（hot-load 無需重啟）
  ├─ retriever.add_tool（embed 新 tool 進 index）
  └─ DB: state=REGISTERED + GeneratedTool row

  ↓ Telegram 訊息變成 ✅ 已處理 (approve)。

下次 chat 同樣問題:
  ↓
tool_agent → gap_detector 看到新 tool similarity 高 → USE
  ↓
composer 用 tool_result 寫回覆 → "我用 cm_to_inch 算了一下，結果是 39.37 吋"
```

---

## 5. 前端測試 Checklist（請依序操作）

> 全部用 cs workspace 測（其他 3 個 hr/it/legal 未啟用 tool_agent，仍走原 RAG）。

### 5.1 已註冊工具會被 USE

| 步驟 | 操作 | 預期 |
|---|---|---|
| 1 | 打開 `http://localhost:5173` → 確認在 **客服** workspace | 頂部 badge `客服` 被選中 |
| 2 | 輸入「現在攝氏 32 度是華氏幾度?」| AI 回「華氏 89.6 度」之類具體數字 |
| 3 | 點 AI 訊息下方「點擊查看 Trace →」| 看到 6 個 step：router / tool_agent / knowledge / policy / tone / composer |
| 4 | 點 `tool_agent` step 展開 Output | `tool_called: "celsius_to_fahrenheit"`、`tool_result: {"fahrenheit": 89.6}` |
| 5 | 點 `composer` step 展開 Input | 看到 `tool_called` / `tool_result` 已注入 |

### 5.2 沒對應工具 → 觸發合成 → 等審核

> 需要 Groq 70B daily quota 還沒撞 — 若已撞會走 5.3 路徑。

| 步驟 | 操作 | 預期 |
|---|---|---|
| 1 | 輸入「把 100 公分換成英吋」（或其他**沒對應既有 tool** 的轉換）| AI 回固定句「目前知識庫中沒有相關資訊...」（合成尚未完成，下次再問）|
| 2 | 切到 `/admin/synthesis` → Tasks tab | 看到新 task `cm_to_inch`，state=AWAITING_APPROVAL |
| 3 | 點該 task → 展開 Source code | 看到 LLM 寫的 BaseTool subclass + pytest |
| 4 | 點 Attempt history | sandbox: X passed / 0 failed |
| 5 | 點右上 ✅ Approve | state 變 REGISTERED |
| 6 | 切到 Generated Tools tab | 多一行 `cm_to_inch`，scope=workspace |
| 7 | 回 chat 再問同樣問題「把 100 公分換成英吋」| 這次 trace 看到 tool_agent USE 它，AI 回真實計算結果 |
| 8 | 同時 Telegram 那邊也應該有 [🔍 新工具待審核] 訊息（如果 token 設了） | 按那邊的 Approve / 按 web Approve 效果一樣 |

### 5.3 沒對應工具 + LLM 撞 rate limit → composer hard guard 守住

| 步驟 | 操作 | 預期 |
|---|---|---|
| 1 | 輸入「把 100 平方公尺換成坪」（Groq 70B daily 已用光時）| AI **一字不差**回「目前知識庫中沒有相關資訊，建議改詢問人工客服或對應部門。」**絕無幻覺數字** |
| 2 | 點 trace 看 `tool_agent` step | `skipped_reason: synthesis_exception:Client error '429 Too Many Requests'` |
| 3 | 點 `composer` step | `model: null`、`latency_ms < 10`、Output text 為固定句（無 LLM 呼叫）|

### 5.4 純 RAG 路徑（既有 KB 能解的問題）

| 步驟 | 操作 | 預期 |
|---|---|---|
| 1 | 輸入「70 歲可以申請車貸嗎?」| AI 引用 cs/faq 內容回答，含 citation badge |
| 2 | trace 看 `tool_agent` step | `skipped_reason: no_tool_needed`（router 判一般 FAQ，無 tool 需求）OR `gap_detected`（gap_detector 認為要 tool 但合成失敗）|
| 3 | `knowledge` step | docs 有 chunks |
| 4 | composer Output | 引用 KB 段落寫回覆 |

### 5.5 Admin 觀測

| 步驟 | 操作 | 預期 |
|---|---|---|
| 1 | `/admin` 看 4 個 workspace 卡片 | 4 部門列出 |
| 2 | 點 cs 卡片 | 看到 workflow.yaml 視覺化 6 個 step（含 tool_agent）|
| 3 | 該頁底下 traces 列表 | 你剛才測試的對話都在 |
| 4 | `/admin/traces` | 跨 workspace 列表 |
| 5 | `/admin/synthesis` → Decision Audit tab | 每次 tool_agent 觸發 gap_detector 的決策 log |
| 6 | Decision Audit 篩 `decision=GAP` | 看到 5.2 / 5.3 產生的 GAP 紀錄 |
| 7 | Decision Audit 篩 `decision=USE` | 看到 5.1 命中既有 tool 的紀錄 |

---

## 6. 已知 limitations

| 項目 | 影響 | 緩解 / 未來方案 |
|---|---|---|
| Groq free tier 70B 每日 100k token | 一天大概 6-10 次完整合成 | 升 Dev Tier，或自架 vLLM serve llama-70b |
| spec_enricher 對單位轉換方向判斷不穩 | 例：m² ↔ 坪 LLM 可能算反 → spec.examples 數字錯 → tests 失敗 → AWAITING_HUMAN_RESCUE | PLAN §22.13 U4 property-based testing / 加 formula 驗算 step |
| chat 是同步等合成 | 觸發合成的對話會等 10-30s | PLAN §22.13 U8 streaming + WebSocket 推進度 |
| chat 沒有「我學到工具了，請再問一次」主動通知 | 使用者要自己再問 | U8 同上 |
| 只有 cs workspace 啟用 tool_agent | hr/it/legal 仍走原 RAG | 驗證 cs 跑通後逐個 workspace 加 |
| Telegram bot 用 polling 模式 | 啟動慢、要 outbound | TG_MODE=webhook + 設公網 URL |
| 不做 compose chain | gap_detector 回 COMPOSE 時 fallback 成「無 tool」 | PLAN §22.13 U2 compose promotion |

---

## 7. 對應的關鍵 commit

```
5c79eb7 Composer: hard short-circuit when no evidence — bypass LLM entirely
3c16914 Tool discoverability + composer empty-tool-result guard
4474848 Synthesis: harden spec_enricher prompt against inverted conversion factors
734e046 Composer: hard-fence hallucination — output fixed sentence when no evidence
8b9f197 Synthesis: drop adversarial test generation entirely
3568af4 TA3 fix: remove auto-approve bypass — all generated tools require HITL
2227287 TA6: e2e pipeline test for tool_agent + composer wiring
79568f9 TA4 + TA5: wire tool_agent into cs workflow + composer uses tool_result
5aadc17 TA3: ToolAgent triggers auto-synthesis on GAP
2bfb6f6 TA2: ToolAgent integrates with gap_detector
c6e1590 TA1: ToolAgent core — retrieval-based tool selection + arg generation
f20127d Docs: README — add Self-Extending Agent section (Phase 13)
3e13028 Frontend: Synthesis Dashboard for Self-Extending Agent
6f8cf9c Phase 6: Self-Extending Agent — synthesis + Telegram HITL
33edb38 HF runtime: enable reranker by default + Groq 429 retry-with-backoff
4f0e894 RAG: hybrid retrieval, optional rerank, evaluation harness + AI docs
```

跑 `git log --oneline` 看完整歷史。
