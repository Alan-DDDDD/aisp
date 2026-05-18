# Demo GIF 錄製指南

> 我不能幫你錄。但我列出**該錄什麼、怎麼錄、放哪裡**，你照單操作 30 分鐘可完成 4 條 demo gif。

---

## 工具

**Windows 推薦**：[ScreenToGif](https://www.screentogif.com/)（免費，能裁切 / 加速 / 標註）

備案：[LICEcap](https://www.cockos.com/licecap/)、[ShareX](https://getsharex.com/)（含螢幕錄影）

**檔案大小目標**：每條 gif **< 5 MB**（GitHub 預覽流暢）。長度 **10-25 秒**。FPS 12-15 即可（gif 不是 video）。

---

## 4 條 demo gif（依優先級排）

### Demo 1：USE 既有工具（最容易示範）

**檔名**：`docs/gifs/demo-1-tool-use.gif`
**目的**：證明 chat 能呼叫合成過的工具回真實計算結果。

**腳本**：
```
1. 前端 / (chat 頁) 在 cs workspace
2. 輸入: 現在攝氏 32 度是華氏幾度?
3. AI 回覆: 攝氏 32 度等於華氏 89.6 度
4. 點 「點擊查看 Trace →」
5. 滑到 tool_agent step，展開 Output
6. 高亮顯示: tool_called: "celsius_to_fahrenheit", tool_result: {"fahrenheit": 89.6}
```

**時長**：~20s（包含 5-10s 等 LLM）

**錄製重點**：
- 起點先讓畫面停 1-2 秒看到 chat 空白介面
- AI 回覆顯示時不要切走
- trace 滑下去時可以稍微停留
- 結尾停 1 秒在 tool_called 那行

---

### Demo 2：完整 HITL 合成 → Approve loop（最有 wow factor）

**檔名**：`docs/gifs/demo-2-hitl-approve.gif`
**目的**：show 「沒工具 → 自動寫工具 → 審核 → 上線」整個閉環。

> **準備**：先 reject 掉 `celsius_to_fahrenheit` 或用一個還沒對應工具的轉換題（例如 inch → cm）。

**腳本（split 成 2 個 gif 避免太長）**：

**Part A：觸發合成 → 看到 Telegram / Dashboard 出現待審**
```
1. chat 輸入: 把 100 公分換成英吋
2. AI 回覆「目前知識庫中沒有相關資訊...」（合成中）
3. 切到 /admin/synthesis → Tasks tab
4. 重新整理 → 看到新 task state=AWAITING_APPROVAL
5. 點該 task，右側 detail panel 展開
6. 展開 Source code → 看 LLM 寫的 BaseTool 程式碼
```

**Part B：Approve → 工具上線 → 再問同樣問題**
```
1. 接續 Part A 的畫面
2. 點 ✅ Approve 按鈕
3. state 變 REGISTERED
4. 切到 Generated Tools tab → 看到新工具列入
5. 切回 chat
6. 重新輸入: 把 100 公分換成英吋
7. 這次 AI 回真實計算結果（39.37 英吋之類）
8. 點 trace 看 tool_agent step → tool_called: cm_to_inch
```

**時長**：Part A ~25s、Part B ~20s（兩個分開錄）

**錄製重點**：
- Part A 結尾停留在 Source code 展開的畫面，顯示 LLM 寫對的 code（有 PR-feel）
- Part B Approve 按鈕被點時可以加 highlight 效果
- 最終 chat 顯示真實計算結果停留 2 秒

---

### Demo 3：反幻覺 hard guard 守住（technical depth）

**檔名**：`docs/gifs/demo-3-no-hallucination.gif`
**目的**：展示沒依據時系統不會編答案。

**腳本**：
```
1. chat 輸入「100 平方公尺換成坪」（沒對應工具，且 Groq daily quota 已滿，
   或臨時改 .env 把 GROQ_API_KEY 改錯讓所有 LLM call 失敗）
2. AI 一字不差回: 目前知識庫中沒有相關資訊，建議改詢問人工客服或對應部門。
3. 點 trace
4. 滑到 tool_agent step → skipped_reason: synthesis_exception / synthesis_failed
5. 滑到 composer step
6. 高亮: model: null, latency_ms < 10ms（證明 LLM 根本沒被呼叫）
```

**時長**：~15s

**錄製重點**：
- 反差關鍵：trace 顯示 LLM 沒被叫到 → 證明 hallucination 不可能發生
- composer 的 `latency_ms` 數字要清楚（建議用游標 hover）

---

### Demo 4：YAML 改一行立刻新增 step（platform 組合能力）

**檔名**：`docs/gifs/demo-4-workflow-yaml.gif`
**目的**：show 「不動 Python，改 YAML 就改部門行為」。

**腳本**：
```
1. 編輯器打開 workspaces/cs/workflow.yaml
2. 高亮現有 6 step
3. 假裝刪掉 tone step（或 reorder）
4. 切到瀏覽器 /admin/workspaces/cs
5. 看 workflow YAML 區塊還是舊內容
6. 切回編輯器存檔
7. 切到瀏覽器 → POST /api/admin/workspaces/cs/workflow/reload（或從 UI 按 reload）
8. 重新整理頁面 → workflow 視覺化少了 tone step
9. 切到 chat 問一句 → trace 確認 tone 沒跑
```

**時長**：~25s

**錄製重點**：
- 編輯器跟瀏覽器並排或快速切換
- 「改 YAML → reload → 行為變」這個動作鏈是關鍵 wow

---

## 放哪裡

### Option A：repo `docs/gifs/`

```
mkdir docs/gifs
mv ~/recordings/demo-*.gif docs/gifs/
```

README 用相對路徑引用：
```markdown
![Tool USE](docs/gifs/demo-1-tool-use.gif)
```

### Option B：HF Space（避免 git LFS）

如果 gif 大於 5 MB，丟到 HF Space repo 的 `docs/` 目錄（HF 支援大檔案 LFS）。

### Option C：YouTube / Loom 短片連結

更長更完整的 demo（2-3 分鐘）可以錄一個 Loom 影片，README 放縮圖 + 連結，不放進 repo。

---

## README 引用建議

把 demo gif 放在 README 開頭（live demo 連結下方），讓首次訪客 10 秒內看到專案在動：

```markdown
# AISP — Enterprise AI Agent Platform

> Multi-Department Agentic Workspace.

🔗 **Live demo**: ...
💻 **Source**: ...

## See it in action

| Tool calling 既有工具 | HITL 完整合成 loop | 反幻覺 hard guard |
|---|---|---|
| ![](docs/gifs/demo-1-tool-use.gif) | ![](docs/gifs/demo-2-hitl-approve.gif) | ![](docs/gifs/demo-3-no-hallucination.gif) |
```

---

## ScreenToGif 操作要點（如果你選這個）

1. 開啟 ScreenToGif → 選 **Recorder**
2. 拉框框框住要錄的區域（瀏覽器 + 編輯器並排會比較好說故事）
3. 設定 FPS 15、開始錄
4. 錄完進 editor：
   - **Skip frames**: 移除 LLM 等待的長停頓（30s → 3s 縮時）
   - **Crop**: 裁掉 taskbar
   - **Loop**: 設 infinite
   - **Save As → GIF**: 用 medium quality 控制大小
5. 檔案 > 5 MB 的話用 [ezgif.com](https://ezgif.com/optimize) 二次壓縮

---

## 錄製前 checklist

- [ ] 後端跑得起來、Groq quota 有剩
- [ ] 前端 cs workspace 對話 history 清空（或建新 room）
- [ ] 瀏覽器分頁只留 frontend 跟 admin
- [ ] dev tool 關掉（除非要 show trace JSON）
- [ ] 螢幕字級放大到看得清楚 (Ctrl + 幾下)
- [ ] 中文輸入法切到能輸入「攝氏」「公分」這種字
- [ ] DEMO 1 跑通過一次知道 Groq 約多久回（合理 latency 心裡有底）

---

## 替代方案：靜態 screenshot 序列

如果不錄 gif，4 張高品質 screenshot 也夠：

1. Chat 介面 + AI 回覆 + trace 面板展開
2. Synthesis Dashboard Tasks tab，點開一筆看 Source code
3. Approve 按下後 state 變 REGISTERED 的瞬間
4. 同樣問題第二次問 → tool_called 命中新工具

PNG 比 gif 對 GitHub 更友善（zoom-in 看得清楚）；只是少了「動」的 wow。
