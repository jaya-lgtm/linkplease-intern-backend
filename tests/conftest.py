import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["WEBHOOK_SIGNATURE_REQUIRED"] = "false"
os.environ["PSEUDOGRAM_API_KEY"] = "test-secret-key"
os.environ["TESTING"] = "true"

from app.database import Base, get_db
from app.main import app

engine = create_engine("sqlite:///./test.db", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("./test.db"):
        try:
            os.remove("./test.db")
        except Exception:
            pass
    if os.path.exists("./test.db-wal"):
        try:
            os.remove("./test.db-wal")
        except Exception:
            pass
    if os.path.exists("./test.db-shm"):
        try:
            os.remove("./test.db-shm")
        except Exception:
            pass

@pytest.fixture(scope="function")
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

@pytest.fixture(scope="function", autouse=True)
def mock_pseudogram_client():
    with patch("app.clients.pseudogram.PseudoGramClient.send_dm", new_callable=AsyncMock) as mock_send, \
         patch("app.clients.pseudogram.PseudoGramClient.get_dm_status", new_callable=AsyncMock) as mock_status:
        yield mock_send, mock_status
