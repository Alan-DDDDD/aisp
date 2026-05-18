import asyncio
from datetime import UTC, datetime

import yaml
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.models import (
    AgentTrace,
    ChatMessage,
    ChatRoom,
    Chunk,
    Document,
    KnowledgeBase,
    Ticket,
    Workspace,
)
from app.km.ingest import ensure_kb, upsert_document
from app.km.pdf_loader import PdfExtractError, extract_text_from_pdf
from app.schemas.knowledge import (
    ChunkOut,
    DocumentIngest,
    DocumentOut,
    KnowledgeBaseOut,
)
from app.workflow import loader as workflow_loader

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/workspaces/{workspace_id}/workflow", response_class=PlainTextResponse)
async def get_workflow_yaml(workspace_id: str) -> str:
    """回傳該 workspace 的 workflow.yaml 純文字內容（給 admin UI 顯示）。"""
    try:
        wf = workflow_loader.get(workspace_id)
    except FileNotFoundError:
        raise HTTPException(404, f"workflow not found for workspace: {workspace_id}")
    # 用 yaml.safe_dump 輸出 — 跟原檔差不多但欄位順序固定
    return yaml.safe_dump(wf.model_dump(exclude_none=True), sort_keys=False, allow_unicode=True)


@router.post("/workspaces/{workspace_id}/workflow/reload")
async def reload_workflow(workspace_id: str) -> dict:
    try:
        wf = workflow_loader.load(workspace_id)
    except FileNotFoundError:
        raise HTTPException(404, f"workflow.yaml not found for workspace: {workspace_id}")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"failed to reload workflow: {e}")
    return {"workspace_id": workspace_id, "workflow_id": wf.id, "step_count": len(wf.steps)}


@router.get("/traces")
async def list_traces(
    workspace_id: str | None = None,
    limit: int = 30,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """列出最近的 traces，optionally filter by workspace_id（透過 room 關聯）。"""
    stmt = select(AgentTrace).order_by(AgentTrace.created_at.desc()).limit(min(limit, 100))
    if workspace_id:
        stmt = stmt.join(ChatRoom, ChatRoom.id == AgentTrace.room_id).where(
            ChatRoom.workspace_id == workspace_id
        )
    traces = (await session.execute(stmt)).scalars().all()
    if not traces:
        return []

    # 帶出 room 的 workspace_id 與該 trace 的 AI 訊息（content 預覽）
    room_ids = list({t.room_id for t in traces})
    rooms_map: dict[str, str] = {}
    if room_ids:
        room_rows = (
            await session.execute(select(ChatRoom).where(ChatRoom.id.in_(room_ids)))
        ).scalars().all()
        rooms_map = {r.id: r.workspace_id for r in room_rows}

    msg_ids = [t.message_id for t in traces]
    msgs_map: dict[str, str] = {}
    if msg_ids:
        msg_rows = (
            await session.execute(select(ChatMessage).where(ChatMessage.id.in_(msg_ids)))
        ).scalars().all()
        msgs_map = {m.id: m.content for m in msg_rows}

    return [
        {
            "id": t.id,
            "workflow_id": t.workflow_id,
            "room_id": t.room_id,
            "workspace_id": rooms_map.get(t.room_id, ""),
            "step_count": len(t.steps or []),
            "total_latency_ms": t.total_latency_ms,
            "created_at": t.created_at.isoformat(),
            "preview": (msgs_map.get(t.message_id) or "")[:120],
        }
        for t in traces
    ]


@router.get("/workspaces/{workspace_id}/rooms")
async def list_workspace_rooms(
    workspace_id: str,
    limit: int = 30,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """workspace 下的最近 rooms — 給 admin 點進去看 trace。"""
    stmt = (
        select(ChatRoom)
        .where(ChatRoom.workspace_id == workspace_id)
        .order_by(ChatRoom.created_at.desc())
        .limit(min(limit, 100))
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "workspace_id": r.workspace_id,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/workspaces/{workspace_id}")
async def get_workspace_detail(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    ws = await session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(404, "workspace not found")

    kb_stmt = (
        select(KnowledgeBase, func.count(Document.id))
        .outerjoin(Document, Document.kb_id == KnowledgeBase.id)
        .where(KnowledgeBase.workspace_id == workspace_id)
        .group_by(KnowledgeBase.id)
    )
    kb_rows = (await session.execute(kb_stmt)).all()
    has_wf = workspace_id in workflow_loader.cached_workspace_ids()

    return {
        "id": ws.id,
        "display_name": ws.display_name,
        "description": ws.description,
        "default_kb": ws.default_kb,
        "color": ws.color,
        "icon": ws.icon,
        "status": ws.status,
        "created_at": ws.created_at.isoformat(),
        "has_workflow": has_wf,
        "kbs": [
            {
                "id": kb.id,
                "name": kb.name,
                "collection_name": kb.collection_name,
                "embedding_model": kb.embedding_model,
                "doc_count": int(doc_count or 0),
            }
            for kb, doc_count in kb_rows
        ],
    }


@router.get("/tickets")
async def list_tickets(
    workspace_id: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    stmt = select(Ticket).order_by(Ticket.created_at.desc()).limit(50)
    if workspace_id:
        stmt = stmt.where(Ticket.workspace_id == workspace_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": t.id,
            "room_id": t.room_id,
            "workspace_id": t.workspace_id,
            "summary": t.summary,
            "rationale": t.rationale,
            "status": t.status,
            "created_at": t.created_at.isoformat(),
        }
        for t in rows
    ]


@router.get("/workspaces/{workspace_id}/kbs", response_model=list[KnowledgeBaseOut])
async def list_kbs(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[KnowledgeBaseOut]:
    stmt = (
        select(
            KnowledgeBase,
            func.count(Document.id).label("doc_count"),
        )
        .outerjoin(Document, Document.kb_id == KnowledgeBase.id)
        .where(KnowledgeBase.workspace_id == workspace_id)
        .group_by(KnowledgeBase.id)
        .order_by(KnowledgeBase.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        KnowledgeBaseOut(
            id=kb.id,
            workspace_id=kb.workspace_id,
            name=kb.name,
            embedding_model=kb.embedding_model,
            version=kb.version,
            created_at=kb.created_at,
            collection_name=kb.collection_name,
            doc_count=int(doc_count or 0),
        )
        for kb, doc_count in rows
    ]


@router.get("/kbs/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    kb_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[DocumentOut]:
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "kb not found")
    stmt = (
        select(
            Document,
            func.count(Chunk.id).label("chunk_count"),
        )
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .where(Document.kb_id == kb_id)
        .group_by(Document.id)
        .order_by(Document.updated_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        DocumentOut(
            id=d.id,
            kb_id=d.kb_id,
            source_type=d.source_type,
            title=d.title,
            metadata=d.doc_metadata or {},
            version=d.version,
            status=d.status,
            updated_at=d.updated_at,
            chunk_count=int(chunk_count or 0),
        )
        for d, chunk_count in rows
    ]


@router.get("/documents/{doc_id}/chunks", response_model=list[ChunkOut])
async def list_chunks(
    doc_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[ChunkOut]:
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "document not found")
    stmt = select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.chunk_index)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        ChunkOut(id=c.id, document_id=c.document_id, chunk_index=c.chunk_index, text=c.text)
        for c in rows
    ]


@router.post("/workspaces/{workspace_id}/kbs/{kb_name}/documents", response_model=DocumentOut)
async def ingest_document(
    workspace_id: str,
    kb_name: str,
    body: DocumentIngest,
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    kb = await ensure_kb(session, workspace_id=workspace_id, name=kb_name)
    doc = await upsert_document(
        session,
        kb=kb,
        title=body.title,
        content=body.content,
        source_type=body.source_type,
        metadata=body.metadata,
    )
    await session.commit()
    chunk_stmt = select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)
    chunk_count = int((await session.execute(chunk_stmt)).scalar() or 0)
    return DocumentOut(
        id=doc.id,
        kb_id=doc.kb_id,
        source_type=doc.source_type,
        title=doc.title,
        metadata=doc.doc_metadata or {},
        version=doc.version,
        status=doc.status,
        updated_at=datetime.now(UTC),
        chunk_count=chunk_count,
    )


@router.post("/kbs/{kb_id}/documents", response_model=DocumentOut)
async def ingest_document_by_kb_id(
    kb_id: str,
    body: DocumentIngest,
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "kb not found")
    doc = await upsert_document(
        session,
        kb=kb,
        title=body.title,
        content=body.content,
        source_type=body.source_type,
        metadata=body.metadata,
    )
    await session.commit()
    chunk_stmt = select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)
    chunk_count = int((await session.execute(chunk_stmt)).scalar() or 0)
    return DocumentOut(
        id=doc.id,
        kb_id=doc.kb_id,
        source_type=doc.source_type,
        title=doc.title,
        metadata=doc.doc_metadata or {},
        version=doc.version,
        status=doc.status,
        updated_at=datetime.now(UTC),
        chunk_count=chunk_count,
    )


@router.post("/kbs/{kb_id}/documents/upload", response_model=DocumentOut)
async def upload_pdf_to_kb(
    kb_id: str,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    category: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    """上傳 PDF，抽取文字後 upsert 為文件。

    - title 預設用檔名（去掉 .pdf）
    - source_type 固定 "pdf"
    - category 進入 metadata.category
    - 檔案大小上限 20 MB
    - 純圖片 PDF（無可抽文字）會回 400
    """
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "kb not found")

    filename = file.filename or "uploaded.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "僅支援 PDF 檔案")

    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"檔案過大（{len(data) // 1024 // 1024} MB），上限 {_MAX_UPLOAD_BYTES // 1024 // 1024} MB",
        )

    # pypdf 是同步、CPU-bound，丟到 threadpool 避免擋住 event loop
    try:
        content = await asyncio.to_thread(extract_text_from_pdf, data)
    except PdfExtractError as e:
        raise HTTPException(400, str(e))

    final_title = (title or filename).strip()
    if final_title.lower().endswith(".pdf"):
        final_title = final_title[:-4]
    metadata: dict = {"original_filename": filename, "byte_size": len(data)}
    if category and category.strip():
        metadata["category"] = category.strip()

    doc = await upsert_document(
        session,
        kb=kb,
        title=final_title,
        content=content,
        source_type="pdf",
        metadata=metadata,
    )
    await session.commit()
    chunk_stmt = select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)
    chunk_count = int((await session.execute(chunk_stmt)).scalar() or 0)
    return DocumentOut(
        id=doc.id,
        kb_id=doc.kb_id,
        source_type=doc.source_type,
        title=doc.title,
        metadata=doc.doc_metadata or {},
        version=doc.version,
        status=doc.status,
        updated_at=datetime.now(UTC),
        chunk_count=chunk_count,
    )
