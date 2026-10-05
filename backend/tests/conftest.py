import os
import tempfile

# 在导入 app 之前指向独立的 sqlite 文件库，避免触碰 Postgres。
_DB_PATH = os.path.join(tempfile.mkdtemp(prefix="hallspan_test_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    # 不以上下文管理器运行：跳过 lifespan（不 seed、不连外部库），数据由测试自备
    return TestClient(app)
