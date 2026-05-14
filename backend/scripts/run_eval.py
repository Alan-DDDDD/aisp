"""跑 retrieval 評估並輸出 markdown 報告。

用法：
    python -m scripts.run_eval                  # 全部 workspace、跑 dense 與 hybrid
    python -m scripts.run_eval --mode hybrid    # 只跑 hybrid
    python -m scripts.run_eval --workspace cs   # 只跑 cs workspace
    python -m scripts.run_eval --rerank         # 再加 reranker 一輪

預設讀 eval/goldens/*.yaml，輸出 markdown 到 stdout。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml
# 讓 `python -m scripts.run_eval` 從 backend/ 跑時找得到 app
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
sys.path.insert(0, str(_BACKEND_DIR))

from app.config import settings  # noqa: E402

# 把相對路徑改成絕對：workspaces 在 repo root；eval 用獨立的 sqlite / chroma 目錄，
# 避免與正式 dev 環境的 data/ 互相污染
settings.workspaces_dir = str(_REPO_ROOT / "workspaces")
settings.sqlite_path = str(_BACKEND_DIR / ".eval-data" / "eval.db")
settings.chroma_persist_dir = str(_BACKEND_DIR / ".eval-data" / "chroma")
from app.db.database import SessionLocal, init_db  # noqa: E402
from app.km import bm25_index, eval as eval_mod, reranker  # noqa: E402
from app.tools import registry as tool_registry  # noqa: E402
from app.tools.kb_search import KBSearchTool  # noqa: E402
from app.workflow.seeder import seed_on_boot  # noqa: E402


def load_goldens(workspace_filter: str | None) -> list[dict]:
    root = Path(__file__).resolve().parents[1] / "eval" / "goldens"
    out = []
    for p in sorted(root.glob("*.yaml")):
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if workspace_filter and data.get("workspace_id") != workspace_filter:
            continue
        out.append(data)
    return out


def format_aggregate(label: str, agg: dict[str, float]) -> str:
    keys = sorted(agg.keys())
    cells = " | ".join(f"{agg[k]:.4f}" for k in keys)
    header = " | ".join(keys)
    return f"**{label}**\n\n| {header} |\n| {' | '.join('---' for _ in keys)} |\n| {cells} |\n"


async def run_one_mode(session, golden: dict, mode: str, top_k: int) -> dict:
    return await eval_mod.evaluate(
        session,
        workspace_id=golden["workspace_id"],
        kb_name=golden["kb_name"],
        queries=golden["queries"],
        top_k=top_k,
        mode=mode,
    )


async def main(modes: list[str], workspace_filter: str | None, top_k: int, use_rerank: bool):
    await init_db()
    # 註冊 tools（seed_on_boot 內部會經由 ingest 用到）並 seed
    try:
        tool_registry.register(KBSearchTool())
    except Exception:
        pass  # 已註冊就略過
    await seed_on_boot()

    goldens = load_goldens(workspace_filter)
    if not goldens:
        print("# 沒有對應的 golden set", flush=True)
        return

    if use_rerank and not (settings.rerank_model or "").strip():
        # 若用者打 --rerank 但 env 沒設，臨時開啟標準模型
        import os
        os.environ["RERANK_MODEL"] = "BAAI/bge-reranker-v2-m3"
        # reload settings 的簡單做法：直接設值
        settings.rerank_model = "BAAI/bge-reranker-v2-m3"
        print(f"# 自動啟用 rerank_model={settings.rerank_model}", flush=True)

    out_lines = []
    out_lines.append("# Retrieval Evaluation Report\n")
    out_lines.append(f"top_k = {top_k}; embedding = `{settings.embedding_model}`\n")
    if use_rerank:
        out_lines.append(f"reranker = `{settings.rerank_model}` (top_n={settings.rerank_top_n})\n")

    for golden in goldens:
        ws = golden["workspace_id"]
        out_lines.append(f"\n## workspace = `{ws}`  ({golden.get('description', '')})\n")
        out_lines.append(f"queries: {len(golden['queries'])}\n")

        for mode in modes:
            bm25_index.reset()
            reranker.reset()
            async with SessionLocal() as session:
                report = await run_one_mode(session, golden, mode, top_k)
            label = f"mode = `{mode}`" + ("  +rerank" if use_rerank else "")
            out_lines.append(format_aggregate(label, report.aggregate))
            # per-query miss 列表（沒命中的 query），幫助診斷
            misses = [
                q.query for q in report.per_query if q.metrics.get(f"hit_rate@{top_k}", 0) == 0
            ]
            if misses:
                out_lines.append(
                    "Misses（top_k 內未命中）:\n"
                    + "\n".join(f"- `{m}`" for m in misses)
                    + "\n"
                )

    print("\n".join(out_lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        nargs="*",
        default=["dense", "hybrid"],
        help="預設跑 dense + hybrid 兩個模式比對",
    )
    parser.add_argument("--workspace", default=None, help="只跑指定 workspace")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="同時啟用 reranker；若 env 未設則自動套用 BAAI/bge-reranker-v2-m3",
    )
    args = parser.parse_args()
    asyncio.run(
        main(
            modes=args.mode,
            workspace_filter=args.workspace,
            top_k=args.top_k,
            use_rerank=args.rerank,
        )
    )
