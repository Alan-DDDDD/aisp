"""Workflow loader 測試 — 用 tmp_path 模擬 workspaces dir。"""

import textwrap
from pathlib import Path

import pytest

from app.workflow import loader as workflow_loader


@pytest.fixture
def workspaces_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.workspaces_dir", str(tmp_path))
    workflow_loader.clear_cache()
    return tmp_path


def _write_workflow(workspaces_dir: Path, ws_id: str, content: str) -> None:
    ws_dir = workspaces_dir / ws_id
    ws_dir.mkdir(parents=True, exist_ok=True)
    (ws_dir / "workflow.yaml").write_text(content, encoding="utf-8")


def test_load_single_workflow(workspaces_tmp):
    _write_workflow(
        workspaces_tmp,
        "cs",
        textwrap.dedent("""
        id: cs_v1
        workspace: cs
        steps:
          - id: router
            agent: router
            input:
              message: $event.message
        emit:
          draft: $router.intent
        """).strip(),
    )
    wf = workflow_loader.load("cs")
    assert wf.id == "cs_v1"
    assert wf.workspace == "cs"
    assert len(wf.steps) == 1
    assert workflow_loader.get("cs") is wf  # 快取


def test_preload_all(workspaces_tmp):
    for ws_id in ["cs", "hr"]:
        _write_workflow(
            workspaces_tmp,
            ws_id,
            textwrap.dedent(f"""
            id: {ws_id}_v1
            workspace: {ws_id}
            steps:
              - id: router
                agent: router
                input:
                  message: $event.message
            """).strip(),
        )
    loaded = workflow_loader.preload_all()
    assert set(loaded.keys()) == {"cs", "hr"}


def test_missing_workflow_raises(workspaces_tmp):
    with pytest.raises(FileNotFoundError):
        workflow_loader.load("nope")
