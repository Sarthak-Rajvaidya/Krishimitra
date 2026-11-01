import os
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="ks_test_")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{TMP}/test.db", "EMBEDDING_BACKEND": "hash", "DEMO_PASSWORD": "Demo-Pass-12345",
    "UPLOAD_DIR": f"{TMP}/uploads", "KNOWLEDGE_DIR": f"{TMP}/knowledge", "MODEL_ARTIFACT_DIR": f"{TMP}/no_model",
    "SECRET_KEY": "test-secret-key-for-pytest-only-0123456789", "APP_ENV": "test",
    "RATE_LIMIT_MULTIPLIER": "1000", "OTP_DEV_ECHO": "true", "DATA_ENCRYPTION_KEY": "", "RAG_MIN_SCORE": "0.12",  # hash embedder is lexical; real embedders use ~0.25
     "GROQ_API_KEY": "", "MISTRAL_API_KEY": "", "GEMINI_API_KEY": "",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PASSWORD = "Demo-Pass-12345"


@pytest.fixture(scope="session", autouse=True)
def seeded():
    from app.db.base import Base
    from app.db.session import SessionLocal, engine
    from app import seed
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed.seed_base(db)
        seed.seed_demo(db)
    yield


@pytest.fixture(autouse=True)
def _memory_vector_store():
    from app.ai.rag.embeddings import HashEmbedder, set_embedder
    from app.ai.rag.store import MemoryStore, set_store
    set_embedder(HashEmbedder(384))
    set_store(MemoryStore())
    yield


@pytest.fixture(scope="session")
def app():
    from app.main import app as a
    return a


@pytest.fixture
def db():
    from app.db.session import SessionLocal
    with SessionLocal() as s:
        yield s


@pytest.fixture
def login(app):
    def _login(email: str) -> TestClient:
        c = TestClient(app)
        r = c.post("/api/v1/auth/login", json={"identifier": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        c.cookies.clear()
        return c
    return _login


@pytest.fixture
def anon(app):
    return TestClient(app)
