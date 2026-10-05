from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.seed import seed_if_empty


def _ensure_schema() -> None:
    """create_all 不会给已存在的表补列；对升级而来的旧库幂等补齐 is_active。"""
    insp = inspect(engine)
    if "seat_plans" not in insp.get_table_names():
        return
    if "is_active" not in {c["name"] for c in insp.get_columns("seat_plans")}:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE seat_plans ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT FALSE"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_schema()
    if settings.seed_on_empty:
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    yield


app = FastAPI(title="HallSpan", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
