from datetime import datetime

from pydantic import BaseModel


class WorkspaceOut(BaseModel):
    id: str
    display_name: str
    description: str
    default_kb: str
    status: str
    color: str
    icon: str
    created_at: datetime
    kb_count: int = 0
    doc_count: int = 0
