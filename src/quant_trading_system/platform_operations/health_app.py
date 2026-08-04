import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text

app = FastAPI(title="Quant Trading System Operations", version="1.0.0")


@app.get("/health/live")
def live():
    return {"status": "UP"}


@app.get("/health/ready")
def ready():
    database_url = os.environ.get("QTS_DATABASE_URL")
    if not database_url:
        return JSONResponse(status_code=503, content={"status": "NOT_READY", "checks": {"database": False}, "reason": "database configuration missing"})
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "NOT_READY", "checks": {"database": False}, "reason": "database unavailable"})
    return {"status": "READY", "checks": {"database": True}}
