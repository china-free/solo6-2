import time
import json
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .database import engine, Base, SessionLocal
from .routers import users, instruments, reservations, usage, anomalies, stats, audit_logs
from .audit import AuditLogger
from .models import AuditAction

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    description="Laboratory instrument reservation and usage audit system with conflict detection, check-in/out tracking, and anomaly detection.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_timing_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    process_time = (time.time() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{process_time:.2f}"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    db = SessionLocal()
    try:
        AuditLogger(db).log(
            entity_type="http_error",
            entity_id=0,
            action=AuditAction.STATUS_CHANGE,
            change_reason=f"{type(exc).__name__}: {str(exc)}",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_type": type(exc).__name__},
    )


app.include_router(users.router, prefix="/api/v1")
app.include_router(instruments.router, prefix="/api/v1")
app.include_router(reservations.router, prefix="/api/v1")
app.include_router(usage.router, prefix="/api/v1")
app.include_router(anomalies.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(audit_logs.router, prefix="/api/v1")


@app.get("/")
def root():
    return {
        "name": settings.APP_NAME,
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat() + "Z"}
