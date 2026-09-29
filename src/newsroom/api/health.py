from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from newsroom.core.db import DbSession

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@router.get("/readyz", response_model=None)
async def readyz(db: DbSession) -> dict[str, str] | JSONResponse:
    """Readiness: the database answers."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "unavailable", "database": "down"}, status_code=503)
    return {"status": "ok", "database": "ok"}
