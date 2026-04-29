import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.routes.deployments import router as deployments_router
from app.api.routes.imports import router as imports_router
from app.api.routes.drift import router as drift_router
from app.api.routes.rollback import router as rollback_router
from app.api.routes.deployment_hcl import router as deployment_hcl_router
from app.api.routes.metadata import router as metadata_router
from app.api.routes.migration import router as migration_router
from app.api.routes.terraform import router as terraform_router
from app.api.routes.versions import router as versions_router
from app.api.routes.ws import router as ws_router
from app.config import settings
from app.scheduler import start_scheduler, stop_scheduler
from app.database import Base, engine

# Ensure all models are imported so Base.metadata sees them before create_all.
from app import models  # noqa: F401

logger = logging.getLogger(__name__)


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}


def _enforce_auth_disabled_guardrail() -> None:
    """Refuse to start if AUTH_DISABLED is on a production-looking host.

    Allowed only when TF_ENV=dev AND DASHBOARD_HOSTNAME is localhost.
    """
    if not settings.auth_disabled:
        return
    if settings.tf_env != "dev" or settings.dashboard_hostname not in _LOCAL_HOSTS:
        raise RuntimeError(
            "AUTH_DISABLED=true refused: requires TF_ENV=dev AND "
            f"DASHBOARD_HOSTNAME in {_LOCAL_HOSTS}. "
            f"Got TF_ENV={settings.tf_env!r} "
            f"DASHBOARD_HOSTNAME={settings.dashboard_hostname!r}."
        )
    logger.warning(
        "AUTH_DISABLED=true active (dev mode on %s). All requests run as anonymous admin.",
        settings.dashboard_hostname,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _enforce_auth_disabled_guardrail()
    logger.info("Application starting up — running Base.metadata.create_all()")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("create_all completed")
    except Exception as exc:
        logger.error("create_all failed at startup: %s", exc)

    try:
        start_scheduler()
    except Exception:
        logger.exception("Failed to start scheduler")

    yield

    try:
        stop_scheduler()
    except Exception:
        logger.exception("Failed to stop scheduler")
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
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

app.include_router(terraform_router, prefix="/api/v1")
app.include_router(metadata_router, prefix="/api/v1")
app.include_router(migration_router, prefix="/api/v1")
app.include_router(imports_router, prefix="/api/v1")
app.include_router(deployments_router, prefix="/api/v1")
app.include_router(versions_router, prefix="/api/v1")
app.include_router(drift_router, prefix="/api/v1")
app.include_router(rollback_router, prefix="/api/v1")
app.include_router(deployment_hcl_router, prefix="/api/v1")
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
