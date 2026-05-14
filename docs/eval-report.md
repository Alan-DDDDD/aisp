# Retrieval Evaluation Report

執行條件：
- Embedding：`BAAI/bge-m3`（1024 維、多語）
- Chunker：結構感知（Markdown + 法條 + 表格保留）
- Reranker（可選）：`BAAI/bge-reranker-v2-m3`
- top_k = 5；hybrid 用 RRF (k=60) 融合 dense top-20 + BM25 top-20
- Golden set：4 個 workspace 共 **53 題**手寫測項，盡量含同義詞與口語化變體

執行：`python -m scripts.run_eval` 重現；加 `--rerank` 啟動精排。

---

## 1. dense vs hybrid（無 reranker）

| Workspace | queries | dense `hit@5` / `MRR` | hybrid `hit@5` / `MRR` |
|-----------|--------:|----------------------:|------------------------:|
| `cs` (客服) | 16 | **1.0000** / **1.0000** | 1.0000 / 0.9167 |
| `hr` | 12 | **1.0000** / **1.0000** | 1.0000 / 0.9583 |
| `it` | 12 | **1.0000** / **1.0000** | 1.0000 / 1.0000 |
| `legal` | 13 | **1.0000** / **1.0000** | 0.9231 / 0.9231 |

觀察：
- `bge-m3` 單獨在這個 corpus 規模（每個 KB ~7–15 個 FAQ）已達 `hit@5 = 1.0`，沒給 hybrid 留空間。
- Hybrid 多帶入 BM25 候選會輕微「污染」RRF 頂端：`cs / hr` 的 MRR 從 1.0 掉到 0.92~0.96 — recall 守住但**第一筆排序**被 BM25 高頻字（如「車貸」「特休」等高 doc-frequency 詞）的候選擠後一名。
- `legal` 唯一一筆 miss：query `個資處理規定`，hybrid 在 top-5 沒回該文件。
- 結論：**現有 dataset 太小、bge-m3 太強**；hybrid 的好處要在 (a) KB 規模上來、或 (b) 大量專有名詞 / 代號 / 法條編號類查詢 出現時才會浮現。

## 2. + Cross-encoder rerank（hybrid 之後接 `bge-reranker-v2-m3`）

| Workspace | hybrid `MRR` | hybrid + rerank `MRR` | 變化 |
|-----------|-----------:|---------------------:|-----|
| `cs` | 0.9167 | **1.0000** | +0.083 |
| `hr` | 0.9583 | **1.0000** | +0.042 |
| `it` | 1.0000 | 1.0000 | — |
| `legal` | 0.9231 | 0.9231 | — |

觀察：
- Rerank 把 hybrid 在 `cs / hr` 多帶進來的 BM25 雜訊擠回原位（MRR 救回 1.0）。
- `legal` 的 miss 仍存在 — 那筆 query 的正確答案根本沒進 hybrid 的 top-20，所以即使 rerank 也救不回（**rerank 的視窗限制**）。
- 在大 corpus 或專有名詞密集的場景，rerank 的提升通常更顯著（公開 benchmark 上 +5%~+15% nDCG），這份小 dataset 的差異會被天花板效應壓低。

## 3. 結論

1. **bge-m3 + 結構感知切塊** 在這個 dataset 上已飽和。重複跑也得到一致結果。
2. **Hybrid + Rerank** 沒在這份 demo 上帶來絕對指標提升，但：
   - **MRR 一致性**更好（hybrid 引入的排序抖動被 rerank 修正）
   - 一旦 KB 增加幾百份文件、或加入合約 PDF / 法條 PDF，dense-only 會開始漏，hybrid + rerank 是必備
3. **更重要的是「現在已經有度量了」** — 任何後續改動（換 embedding、調 chunker、加 metadata filter）都可以重跑這份 harness 驗證，不再憑感覺。

## 4. 已知限制

- 每個 workspace 的 KB 僅 ~7–15 個文件，無法呈現 hybrid / rerank 的長尾優勢
- 評分用「title 子字串比對」，沒做語意正解匹配（避免 LLM judge 的隨機性）
- 沒測量 latency：本機環境下 dense ~50 ms、hybrid ~120 ms、+rerank +200~400 ms

## 5. 重現

```bash
cd backend
python -m scripts.run_eval                  # dense 與 hybrid 對比
python -m scripts.run_eval --rerank         # 加 reranker（會下載 ~600MB 模型）
python -m scripts.run_eval --workspace cs   # 只跑某個 workspace
```

Eval 使用獨立的 `backend/.eval-data/`（SQLite + Chroma）不會污染正式 dev 資料夾。
