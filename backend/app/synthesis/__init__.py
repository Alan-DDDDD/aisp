"""Phase 6 — Self-Extending Agent / Tool Synthesis。

子模組：
  schemas       Pydantic 型別（Step / Decision / ToolSpec / ...）
  tool_retriever 工具 embedding + 檢索
  planner       Planner LLM（query → steps）
  judge         Judge LLM（gray-zone 決策）
  review        HumanReviewInterface（M3 補 Telegram impl）
  gap_detector  Phase A 入口：detect_gaps()
"""
