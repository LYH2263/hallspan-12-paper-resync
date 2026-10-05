import os

# 必须在导入 app.* 之前：database 模块导入时即按 DATABASE_URL 建引擎
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as dbmod
import app.main as mainmod
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    # database.get_db 走 dbmod.SessionLocal；main.lifespan 用的是导入时绑定的名字，两处都要换
    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "SessionLocal", Session)
    monkeypatch.setattr(mainmod, "engine", engine)
    monkeypatch.setattr(mainmod, "SessionLocal", Session)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session(client):
    s = dbmod.SessionLocal()
    try:
        yield s
    finally:
        s.close()
