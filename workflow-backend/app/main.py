from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncpg

from db import apply_schema, close_db, get_connection
from app.api.routes_pipelines import router as pipelines_router
from app.api.routes_runs import router as runs_router
from app.api.routes_resume import router as resume_router
from app.api.routes_blocks import router as blocks_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await apply_schema()
    yield
    await close_db()


app = FastAPI(title="Workflow Automation Engine", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pipelines_router, prefix="/pipelines",
                   tags=["pipelines"])
app.include_router(runs_router, prefix="/runs", tags=["runs"])
app.include_router(resume_router, prefix="/resume", tags=["resume"])
app.include_router(blocks_router, prefix="/blocks", tags=["blocks"])


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400, content={"detail": str(exc)}
    )


@app.exception_handler(KeyError)
async def key_error_handler(request: Request, exc: KeyError):
    return JSONResponse(
        status_code=404, content={"detail": str(exc)}
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError):
    return JSONResponse(
        status_code=500, content={"detail": str(exc)}
    )


@app.exception_handler(asyncpg.ForeignKeyViolationError)
async def fk_error_handler(
    request: Request, exc: asyncpg.ForeignKeyViolationError
):
    return JSONResponse(
        status_code=409, content={"detail": str(exc)}
    )


@app.get("/health")
async def health_check():
    checks: dict[str, str] = {}
    try:
        conn = await get_connection()
        try:
            await conn.fetchval("SELECT 1")
            checks["postgres"] = "ok"
        finally:
            await conn.close()
    except Exception as e:
        checks["postgres"] = f"error: {e}"
    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks
    }
