# AI Design Decisions

> 這份文件把專案裡 AI 相關的取捨明確化：選了什麼、放棄了什麼、為什麼。
> 觀眾是評估這個專案的工程師（或面試官）。

---

## 1. Embedding：為什麼選 `BAAI/bge-m3`

**候選**：
- ChromaDB 內建 ONNX `MiniLM-L6-v2`（384 維，~80 MB）
- OpenAI `text-embedding-3-small`（雲端 API）
- `BAAI/bge-m3`（1024 維，~2 GB，本地、多語）✅

**決策**：預設 `bge-m3`，但保留 `EMBEDDING_MODEL=chroma-default` 切回 MiniLM 的逃生口。

**理由**：
- MiniLM 對英文導向，HR / 法務的繁中查詢命中率明顯下降（升級前實測：問「彈性上下班規定」搜不到 HR 內含相關內容的 doc，bge-m3 升級後立刻命中）。
- 不選 OpenAI embedding 是為了：(a) demo 不依賴雲端 API key (b) 多租戶資料能本地隔離 (c) 部署在 HF Spaces 不付外部 token 成本。
- `bge-m3` 的代價是 +2 GB 模型 + torch CPU build；Dockerfile 預下載到 image 內，避免 HF Space ephemeral disk 冷啟動每次重抓。

**遺留問題**：HF 免費版 16 GB RAM 在 bge-m3 + ChromaDB + FastAPI 之外吃緊；若想再加 reranker（~600 MB）需要 (a) 換 paid tier 或 (b) 改用 quantized 模型。目前 reranker 在 prod 預設 `OFF`，本機跑 eval 才開。

---

## 2. Retrieval pipeline：為什麼是 Hybrid + Rerank（且 rerank 預設 off）

**候選**：
- 純 dense
- 純 BM25
- **Hybrid（dense + BM25 + RRF）+ optional cross-encoder rerank** ✅

**決策**：預設 `RETRIEVAL_MODE=hybrid`；rerank 由 `RERANK_MODEL` env 控制。

**理由**：
- Dense 對「語意相近但用字不同」強；BM25 對「專有名詞 / 編號 / 法條」強。混用是業界共識。
- RRF (Reciprocal Rank Fusion) 用 rank 而非原始分數融合，**兩個 retriever 的分數尺度不對齊也不會打架**，是融合的 default-good。
- Cross-encoder rerank（`bge-reranker-v2-m3`）是 dense 的姊妹模型；用 query-doc 對對打分，精排 top-20 → top-5 通常給 +5%~+15% nDCG。但代價是 +600 MB + 每 query +100~400 ms。
- HF Spaces 免費版資源緊，rerank 預設關閉、由 env var 開啟；本機跑 `--rerank` 看數據。

**Eval 結果（53 題、top_k=5）**：
- 在這個小 dataset 上 dense 已飽和（hit_rate@5 = 1.0），hybrid 沒給絕對提升；BM25 噪音反讓 MRR 略降，rerank 修正回 dense 等級。
- 真正能展現 hybrid + rerank 優勢的場景是「KB 上千篇 / 文件含大量代號 / 法條 PDF」。
- **重點不是現在的數字漂亮，而是有度量、有 baseline，下次調 retrieval 不再憑感覺**。完整數據與限制：[`./eval-report.md`](./eval-report.md)。

---

## 3. Chunker：結構感知（含繁中法條）為什麼自寫

**候選**：
- LangChain `RecursiveCharacterTextSplitter`
- LlamaIndex `SentenceSplitter`
- **自寫純 stdlib chunker**（純 `re` + `dataclasses`，0 額外依賴）✅

**決策**：自寫；負責 Markdown 結構、繁中法條、表格與程式碼保留、heading breadcrumb prepend。

**為什麼不用框架的**：
- 框架的 splitter 看不懂繁中法條（`第三條 / 第三條之一 / 項 / 款 / (一) / ①`），會把單一條切斷在句中。
- 框架的 splitter 沒有「heading 路徑作為 chunk 上下文」的機制 — 法務最常見的問題是「保密義務」這種**只在 heading 出現、不在 body 重複的詞**，沒 breadcrumb 就會漏召。
- 框架的 splitter 不會把 Markdown 表格當原子單位；表格被切兩半 retrieval 就壞。

**自寫的代價**：
- 220 行 + 22 個單元測試
- 不會自動支援 .docx / .pptx 等格式（未來加，加在 ingest 層而非 chunker）

**目前覆蓋**：
- Markdown：heading（1–6 級）、表格、fenced code block
- 繁中法條：第N章 / 第N節 / 第N條（含「之一」修正版、中文與阿拉伯數字、行內標題）
- 子條款邊界：第N項 / 第N款 / (一)(二) / ①②（用於過長條文退回切分）
- 段落內：句界（中文 `。！？；` / 英文 `.!?`）

---

## 4. 8 個 agent：為什麼這樣切

**反方論點**："把所有事情塞進一個大 prompt 不就好了？少 N 次 LLM call、少 N 倍 latency、少 N 倍 token 成本。"

**為什麼仍切成 8 個**：
- **單一職責 → 單一 prompt → 單一錯誤面**：composer 漏字、policy 沒抓到風險、router 路由錯，trace 上一眼可分。一坨大 prompt 出錯是黑盒。
- **schema 可被外部驗證**：每個 agent 走 JSON schema 強約束，pydantic 出口校驗；錯了重試/降級的 fallback 是 agent 級不是整個 chat 重來。
- **並行**：同層 agent (`knowledge` + `policy` + `tone` + `risk`) 沒互相依賴，runtime 用 `asyncio.gather` 並行，整體 latency ≈ max(各 agent)，不是 sum。
- **可替換**：法務部門想換成自家風險規則 → 替 `risk` agent 即可，不動其他人。
- **可觀測**：trace 顯示每個 agent 的 input / output / latency / model，**面試時可以打開一筆 trace 講「為什麼 AI 給這個答案」**。

**8 個 agent 的職責邊界**：見 README 的「Agent 套件」表格；每個都有獨立的 system prompt（在 `app/agents/*.py`）。

---

## 5. Composer 反幻覺策略

`composer` 的 system prompt 強制（優先級由高至低）：
1. 嚴禁編造事實。任何具體數字、時間、流程步驟、聯絡電話、辦法名稱，都必須能在「可引用的知識來源」中找到對應依據。
2. 若「可引用的知識來源」為空或明顯不相關，**直接告知使用者「KB 無相關資訊，建議改詢問人工客服」**，不要套用常識補答。
3. 不確定時要承諾後續跟進，不要編造。
4. 回覆直接、不要重複問題；citation 自然融入。

**配套機制**：
- `composer_min_doc_score` (0.45) 過濾低分 chunk，避免 retrieval 抓到不相關內容後讓 LLM 寫得「看起來合理但其實亂答」。
- Citation 帶 `heading_path`，前端 UI 顯示「員工手冊 > 休假」這類 breadcrumb，使用者可追源。
- 沒命中時的 fallback 是「坦承不知道」，不是「給看似合理的答案」 — 對企業場景比「永遠給答案」更可靠。

---

## 6. LLM Provider 抽象：Mock 為什麼是頭等公民

`provider.chat(...)` 統一介面下：
- `mock`：固定樣板回應，**離線可跑、永遠可重現**。Demo 翻車 / API 額度爆掉 / CI 跑測試都靠它。
- `groq`：實作完成，主打超低延遲（Llama 3.1 8B-instant on LPU）。
- `ollama / gemini / openrouter`：介面預留、實作 stub `NotImplementedError`，加任一家只需要寫該檔的 ~50 行。

**為什麼 Mock 不是測試專用**：
- 面試 demo 場景：網路不穩 / API 沒充值 / 主辦方的 firewall 擋 Groq → 切回 mock 立刻可演 router 路由、KB 命中、citation 與 trace；只是 composer 回的是固定字串。**Demo 翻車的兜底**。
- CI：跑 23 個 backend 測試完全不依賴外部 LLM，CI 永遠綠。

---

## 7. AI Observability：trace 不只是 log

每筆 chat 訊息背後存了一份 `AgentTrace`：
- `workflow_id`：用了哪份 workflow YAML
- `steps[]`：每個 agent step 的
  - `agent_id` / `step_id`
  - `input` / `output`（完整 JSON）
  - `latency_ms` / `model`
  - `error`（如果有）
- `total_latency_ms`

Admin UI 的 Trace Explorer 可以重播任一次決策，包含：
- 點開單一 step 看 LLM 的 input / output
- 看 retrieval 給了哪些 citation、分數、來源 retriever（dense / bm25 / rrf）
- 看哪一步出錯、用了哪個模型

對企業 use case 這是 **audit log + 除錯工具 + 上線後 quality assurance 的同一個東西**。對面試是「我有沒有想過上線之後出問題怎麼辦」的直接答案。

---

## 8. 為什麼不用 LangChain / LangGraph

**前提**：本人讀過兩個框架的 source，也評估過用它們重寫這個專案。**刻意不用**的理由：

1. **平台價值會被框架吃掉**。本專案的核心賣點是「workflow 用 YAML 配，agent 之間的依賴 runtime 自動推導 DAG」。如果改成 `LangGraph` 的 `StateGraph(...)` API，這些設計決策就變成「LangGraph API 的呼叫者」 — 看不出有思考過 platform 抽象。
2. **抽象漏太厲害**。LangChain 的 `Chain / Runnable / Tool` 三層在中等規模就會打架，社群已有大量反思（Hamel Husain、Eugene Yan、Simon Willison 等）。Anthropic 的 [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) 直接建議從 primitives 構建。
3. **debug 困難**。LangChain 的 stack trace 很常埋在 `RunnableLambda(callable=<lambda>)` 五層 wrap 裡；自寫的 trace 每一層都看得清。
4. **依賴打架**。LangChain 對 `langchain-core / langchain-community / langsmith` 的拉扯讓 dep tree 很難穩定，HF Spaces image 動輒 +800 MB。本專案總 Docker image ~3 GB（torch + bge-m3 是大頭）；加 LangChain 會變 ~4 GB。

**承認的代價**：
- HR 用「LangChain / LangGraph」關鍵字過履歷可能會漏掉這專案 → 履歷與 LinkedIn 主動寫「evaluated LangChain / LangGraph, decided to build from primitives because ...」把缺口翻成主動選擇。
- 沒寫過 LangChain code 對 junior 缺有風險 → 在面試前快速跑一份 LangGraph hello world，能準確比較「同一份 workflow 用兩種寫法各長什麼樣」。

---

## 9. 還沒做但有想過的（roadmap）

- **Contextual chunking**（Anthropic 2024）：在 chunk 前面 prepend 整份 doc 的 LLM 摘要，retrieval miss 號稱 -49%。代價是攝取時每 chunk +1 LLM call。等加入大規模 PDF 時做。
- **HyDE / 多 query 變體**：對短而模糊的 query 把 LLM 編一個假答案、用它的 embedding 搜尋。每題 +1 LLM call，效果在小 query 上顯著。
- **Agentic RAG**：query rewriter + retrieval 多輪 + self-critique。當前 dataset 沒這個需求；做了會把 LLM 額度與 latency 翻 3~5 倍，效益 < 成本。
- **Multi-vector / parent-child chunking**：同 chunk 多個 embedding 觀點（標題 / 內文 / 假設問題）。
- **OCR**：給純圖片 PDF 用。HF Spaces 免費版資源裝不下，先排後面。

不做這些不是「不會」，是「在目前 dataset 上做沒回報」 — 對應的 baseline 都在 [`./eval-report.md`](./eval-report.md) 可隨時驗證。
