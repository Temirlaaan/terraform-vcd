import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.routes.metadata import router as metadata_router
from app.api.routes.migration import router as migration_router
from app.api.routes.terraform import router as terraform_router
from app.api.routes.ws import router as ws_router
from app.config import settings
from app.database import engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting up")
    yield
    logger.info("Application shutting down")


app = FastAPI(
    title="Terraform VCD Dashboard",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(terraform_router, prefix="/api/v1")
app.include_router(metadata_router, prefix="/api/v1")
app.include_router(migration_router, prefix="/api/v1")
app.include_router(ws_router)


@app.get("/health")
async def health():
    """Health check that verifies database and Redis connectivity."""
    checks: dict = {}

    # Check PostgreSQL
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.error("Health check: database unreachable: %s", exc)
        checks["database"] = "unavailable"

    # Check Redis
    try:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis.ping()
            checks["redis"] = "ok"
        finally:
            await redis.aclose()
    except Exception as exc:
        logger.error("Health check: redis unreachable: %s", exc)
        checks["redis"] = "unavailable"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if all_ok else "degraded", "checks": checks},
    )
