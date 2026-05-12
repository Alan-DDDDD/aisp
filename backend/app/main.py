import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.chat import router as chat_router
from app.config import settings
from app.db.database import init_db
from app.workflow.bootstrap import register_default_agents
from app.ws.hub import router as ws_router

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("Starting AISP backend (mode=%s, llm=%s)", settings.mode, settings.llm_provider)
    await init_db()
    register_default_agents()
    from app.workflow import loader as workflow_loader
    from app.workflow.seeder import seed_on_boot

    await seed_on_boot()
    from app.workflow import workspace_registry

    workspace_registry.load_all()
    loaded = workflow_loader.preload_all()
    log.info("Preloaded %d workflows: %s", len(loaded), list(loaded.keys()))
    yield
    log.info("Shutdown.")


app = FastAPI(
    title="AISP — Enterprise AI Agent Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "mode": settings.mode,
        "llm_provider": settings.llm_provider,
        "version": "0.1.0",
    }
