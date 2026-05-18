# 面試備忘：AISP — Enterprise AI Agent Platform

> 自己的 cheat sheet。對外講解、Q&A、trade-off 都對齊到這份。
> 對應 PLAN.md / PROGRESS.md / MANUAL_TEST.md。

---

## 1. 30 秒 elevator pitch

> 「AISP 是一個多部門 AI agent 平台。**3 個檔案就能新增一個部門**（workspace.json + workflow.yaml + 知識文件），共用同一份後端 runtime。
>
> 內建 9 個 agent、Hybrid retrieval（dense + BM25 + RRF + 可選 reranker）、Trace observability、PDF 攝取。
>
> 最有意思的是 Phase 13 開始做的 **Self-Extending Agent** — 系統遇到沒工具能解的 query，**自動寫工具、跑 sandbox、送 Telegram 給人類審核**，審過 hot-load 進 registry 直接可用。整套 HITL flow 是用程式 + 嚴格 prompt + 反幻覺 hard guard 三層保險來防止 LLM 失控。」

---

## 2. 三個故事

面試官問「介紹一個你自豪的設計決策」時，挑一個講。

### Story A：Workflow as YAML（Phase 5）

**情境**：4 個部門 pipeline 不同。CS 要合規 + 語氣；HR 要同理；IT 要工單；法務要條款分析。

**Naïve 解**：4 個 endpoint / 4 份 router。

**我選**：YAML 描述 DAG → runtime 從 step 之間的 `$xxx` 引用**反推依賴**，同層自動 `asyncio.gather` 並行。

```yaml
- id: composer
  agent: composer
  input:
    docs: $knowledge.docs    # ← runtime 自動偵測 composer depends on knowledge
    tone: $tone.tone
```

**為什麼**：
- 「新增部門不改 code」是這個 platform 的核心 value proposition
- 沒用 LangGraph / CrewAI — 自己寫 200 行 DAG executor，介面不被 framework 綁住
- 變數 resolver 處理 dict / list 遞迴內插，比 vanilla YAML expansion 更強

**Trade-off**：放棄類型檢查（YAML 不靜態驗證），換來零 deploy 修改部門行為。**用 startup-time validation + workflow.preload_all() catch parse error**。

### Story B：Self-Extending Agent — HITL + 反幻覺 hard guard（Phase 13/14）

**情境**：要把 platform 從「會用工具的 chatbot」升級到「會造工具的 agent」。

**LLM 寫的 code 不能直接信** — 即使 sandbox 通過，邏輯可能是錯的。怎麼擋？

**設計**：
1. **3-stage cascading gap detection** — retrieval shortcut 處理顯然 case，灰色區交給 Judge LLM，再灰問人類
2. **Code-Test 隔離** — code generator 跟 test generator 看不到對方的 context，避免 LLM 寫遷就 code 的測試（PLAN §22.5.4）
3. **AST static check + sandbox monkey-patch** — `exec/eval/subprocess` 直接禁；socket/open/httpx 用 monkey-patch 把行為錄下來給審核者看
4. **HITL 雙通道** — Telegram（行動審核）+ Web Dashboard（看 code diff / attempt history）
5. **嚴格 HITL 紅線** — 任何 generated tool 一律必須人類按 Approve 才進 registry，**沒有 auto-approve 後門**

**反幻覺三層保險（Phase 14）**：
- (a) system prompt 用 `[TOOL_RESULT]` / `[KNOWLEDGE]` 標籤明確區隔 evidence
- (b) `_build_context` 對 `{"docs": []}` 這種「實質為空」的 tool result 跳過注入
- (c) **程式碼層 hard guard** — 無依據時根本不呼叫 LLM，直接 return 固定句子

實測 (a)(b) 不夠 — 8B 模型對長 prompt 不夠服從，照樣幻覺。**(c) 是真正的保險絲**：沒呼叫 LLM = 零幻覺可能。

**Trade-off**：(c) 犧牲一些自然感（打招呼也會得到「目前知識庫中沒有相關資訊」），換來零幻覺保證。對企業客服場景值得。

### Story C：Hybrid Retrieval + Eval Harness（Phase 12）

**情境**：dense embedding（bge-m3）對「**Q: 70 歲能借車貸嗎？**」這種 query 有時抓不到正確的 FAQ — 因為 FAQ 文字常用「年齡限制 20-65」而非「70」。

**我做**：
- 加 BM25 sparse retrieval（jieba 中文分詞）
- RRF (Reciprocal Rank Fusion, k=60) 融合 dense + sparse
- 可選 cross-encoder reranker (bge-reranker-v2-m3)
- 寫 53 題 golden set + eval harness 量 `recall@k / precision@k / hit_rate@k / MRR`

**為什麼這順序**：
- 改 RAG 不能「感覺變好了」就 ship — eval harness 是 baseline
- BM25 + RRF 零成本（in-memory），rerank 才是 +600MB 模型

**數字**：
| Workspace | dense MRR | hybrid MRR | hybrid + rerank MRR |
|---|---|---|---|
| cs | 1.0 | 0.92 | **1.0** |
| hr | 1.0 | 0.96 | **1.0** |
| legal | 1.0 | 0.92 | 0.92 |

**Trade-off**：hybrid 沒比 dense 好（甚至略差）！因為 cs/hr 的 FAQ 文字夠均勻，dense 就夠。**結論寫進 README — 不假裝 hybrid 是 universal win**。

---

## 3. 常見 Q&A

### Q1：為什麼不用 LangChain / LangGraph？

> LangGraph 的 graph executor 確實能取代我的 200 行 workflow runtime。但 (a) graph 是 code-defined 而非 config-defined — 我的 platform 賣點是「YAML 改部門行為不動 code」；(b) LangGraph 的 state 設計綁 TypedDict，跟我 Pydantic-first 的契約不合；(c) framework 抽象洩漏成本高，自己寫 200 行更可控。
>
> 對 reviewer 講：「我不是要做 chatbot 框架，是要做能 demo 平台組合能力的 backend skeleton。」

### Q2：Self-Extending Agent 萬一 LLM 寫了惡意 code 怎麼辦？

> 三層擋：
>
> 1. **AST static check** — `subprocess`、`os.system`、`exec`、`eval`、`__import__` 直接禁，import whitelist 限制只能 import `app.*` / `pydantic` / `datetime` 等
> 2. **Sandbox monkey-patch** — `socket` / `open` / `httpx` 在 sandbox 內被攔截錄下來，行為紀錄給人類審核者看
> 3. **強制 HITL** — 任何 generated tool 必須人類按 Approve 才進 process。**沒有 auto-approve 路徑**
>
> 紅線：MVP 不做完整 sandboxed runtime — approved tool 跑在主 process。理由：「(a) AST + 行為觀察 + 人類審核三層已過濾過；(b) 完整 sandbox（Docker / Firecracker / Wasm）是 U1 升級項，prod 要做」

### Q3：為什麼 chat 沒有「async 等合成 + WebSocket 推進度」？

> Phase 14 故意做同步：使用者送訊息 → 等 10-30s → 看結果。**這是個 trade-off**。
>
> Async 的問題：(a) 要管 session 狀態追蹤；(b) 要在 UI 顯示「正在學工具」spinner；(c) 合成完用什麼通道推回 — 同一 room 還是用 push notification？
>
> MVP 階段 same-turn sync 比較容易示範完整 loop。**U8 streaming 進度推送列為下一步升級**，PLAN §22.13 寫清楚。

### Q4：tool_agent 為什麼放 router 之後、knowledge / policy / tone 並行而非串行？

> 因為 tool_agent 跟 knowledge / policy / tone 都只依賴 router 的意圖分類，沒有彼此依賴。**workflow runtime 從 `$xxx` 引用反推 DAG**，這 4 個自然在同層 `asyncio.gather` 並行。
>
> 副效應：tool_agent 命中工具時 knowledge 的 RAG 結果浪費，但 composer 會優先用 tool_result。為此小浪費而換 latency 上限是 `max(各 step)` 而非 `sum`。
>
> Future：可以加 `skip_on:` 條件跳過，但目前 latency overhead 不大（knowledge 100ms vs tool_agent 3-15s），先不做。

### Q5：composer 三層反幻覺保險是 over-engineering 嗎？

> 不是。實測過程中我親眼看到 8B 模型在 prompt 寫「無依據必須輸出固定句」的情況下，**還是回**「根據工具結果，100 平方公尺約等於 11.15 坪。我呼叫了「面積轉換工具」來計算這個結果」 — 整段是幻覺。
>
> Prompt-only 不夠強。第三層 hard guard（沒依據直接 return，不呼叫 LLM）才是真正可靠的保險絲。**Trade-off 是打招呼也會得到「目前知識庫中沒有相關資訊」**，但對企業客服場景，準確度 > 自然感。

### Q6：你寫的 200 行 workflow runtime 跟生產級框架差在哪？

> 差：error retry / circuit breaker / observability hooks / 多租戶 quota / message bus / persistent state。
>
> 但我的 runtime 有 **(a) 從 input 自動推 DAG**（少數 framework 內建）、**(b) Pydantic 契約強約束**、**(c) 變數 resolver 支援 dict/list 遞迴內插**。
>
> 對工作面試：「我不在重複造輪子。我是在示範 framework 設計能力 — 如果接你們 prod 系統，我能說出該用 LangGraph 還是自寫，理由是什麼」

### Q7：Groq rate limit 怎麼處理？

> 用 free tier（llama-3.3-70b-versatile, 100k TPD）做 demo。撞限時：
>
> - **429 retry-with-backoff** 已實作（commit 33edb38），3 次指數退避
> - **撞 daily limit** 時整套合成 pipeline 卡住 — 因為 spec_enricher / code_gen / test_gen 都用 70B
> - **此時 composer 的 hard guard 接管** — 不呼叫 LLM 直接回固定句子（chat 不掛、不幻覺）
>
> Prod 解：(a) 升 Dev Tier，(b) Provider 抽象層支援 fallback 到其他 LLM（OpenRouter / Gemini），(c) 自架 vLLM serve 70B。

### Q8：4 個 workspace seed 是不是太刻意？

> 是 demo data，但設計上有用。每個 workspace 的 `workflow.yaml` shape 不同：
>
> - CS：5 step（含 policy + tone 雙軌合規）
> - HR：4 step（去掉 policy，同理優先）
> - IT：4 step（加 ticket_decision 自動開單）
> - Legal：5 step（加 clause_analyzer，risk 串在 knowledge 之後）
>
> 這展示 platform 的組合能力 — **「workflow 不同 → 同樣 agent 套件 → 4 個不同行為」是這個 project 的賣點**。

### Q9：為什麼有 9 個 agent，不是 1 個 big agent？

> 單一職責原則。每個 agent 一個 prompt、一個輸入輸出契約、一個 LLM call。好處：
>
> - 替換成本低（換 router 不影響其他）
> - trace 可讀（每個 step 在 UI 上獨立顯示）
> - 可並行（DAG runtime 自動）
> - 測試容易（每個 agent 單測，再加 e2e）
>
> 反例 — 如果做 1 個 big agent 接全部訊息走完整 reasoning：(a) prompt 會爆；(b) 出錯不知是哪一步；(c) 無法並行。

### Q10：怎麼證明這不是「能跑就好」的 toy project？

> 三個證據：
>
> 1. **214 個 unit + e2e test** — 涵蓋 workflow runtime / retrieval / agent fallback / synthesis pipeline 8 stage / sandbox / approval state machine / 反幻覺 guard
> 2. **53 題 golden set + eval harness** — RAG 改動有客觀指標，不靠感覺
> 3. **完整 HITL flow + 反幻覺 hard guard** — 我親自跑 demo 撞到 8 個 bug（README "Limitations" 與 commit history 都列出來），每個 bug 有對應 fix commit 跟 test

---

## 4. 講解時的重點 metaphor / catchphrase

| 概念 | 對外的話術 |
|---|---|
| Self-Extending Agent | 「會造工具的 AI Work，不只會用工具」 |
| HITL 紅線 | 「audit-based safety + 強制人類核准 — MVP 不做 enforce，但留 path」 |
| 反幻覺 hard guard | 「Prompt 守則跟程式碼 guard 都做。前者建議 LLM 怎麼做，後者保證它做不了什麼」 |
| YAML workflow | 「行為差異全 config，不動 Python」 |
| Eval harness | 「改 RAG 不靠感覺」 |
| Code-Test 隔離 | 「同一 context 寫 code 跟 test 等於寫 self-referential proof」 |

---

## 5. 對外有哪些可以講的「下一步」（PLAN §22.13）

挑 3 個面試最容易引發討論的：

1. **U1 Permission Model** — capability-based 工具權限，approved tool 也跑在 sandbox。從 audit-based 升級到 enforce-based。
2. **U4 Property-based / Mutation testing** — 用 Hypothesis 對 generated tool 做 property test、用 mutmut 檢查 test 有區辨力。解決今天 demo 撞到的 spec_enricher 寫錯數字問題。
3. **U11 Web Dashboard 取代 Telegram** — 多 reviewer + code diff viewer + 整合企業 SSO，是 prod 必要升級。

---

## 6. 我會主動講什麼（沒人問也說）

- **「我自己跑 demo 撞到 8 個 bug，每個 fix 是一個獨立 commit。這條 commit history 就是 LLM-based system 真實工程難度的紀錄。」**（指 feature/tool-agent 分支的 6 個 fix commit）

- **「Composer 的反幻覺從 prompt 加固到程式碼 hard guard 共改了三次。第三次才真正可靠。這是學到的：對 weaker model，prompt 是建議，code 才是保證。」**

- **「Phase 6 §22 是我加在原 8-phase plan 之外的整套設計，PLAN.md 寫了 800 行 design doc，14 個決策日誌。不是後來補的 — 是先寫 design 才寫 code，跟 PROGRESS.md 的 Phase 9 記錄對得起來。」**

---

## 7. 避免講的話 / 反 pattern

- ❌ 「這是 prod-ready」 — **不是**。MVP 階段 sandbox 沒做完整隔離（U1），審核流程沒做多人 quorum（U7），單機 SQLite。要老實說。

- ❌ 「用了 LangChain」 — 沒用。**有人問再說「故意不用，理由 X」**，沒問不主動帶。

- ❌ 「Agent / Workflow / Tool 都是我發明的」 — 不是。每個概念引用業界共識（OpenAI function calling、Voyager paper、AutoGen 的 agent pattern）。**承認站在巨人肩上，但能說清自己的 design choice**。

- ❌ 「LLM 寫的 code 我審過了，沒問題」 — Demo 撞到的 spec_enricher 寫錯轉換因子那一例，**就是 LLM-generated 結果不可信的證據**。**老實說：「LLM 會錯，所以 HITL 與 hard guard 才必要」**。
