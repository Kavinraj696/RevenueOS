import sys
import os
from pathlib import Path

# Add backend to sys.path
backend_path = Path(__file__).resolve().parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.db.base import Base
from app.api.deps import get_db
from app.main import app
from app.synthetic.generator import SyntheticDataGenerator

import json
from decimal import Decimal
from sqlalchemy.pool import StaticPool

def custom_json_serializer(obj):
    return json.dumps(obj, default=lambda o: str(o) if isinstance(o, Decimal) else str(o))

TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        json_serializer=custom_json_serializer,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def db_session(test_engine):
    """Provides a transactional database session for each test function."""
    Session = sessionmaker(bind=test_engine)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()

@pytest.fixture(scope="function")
def client(test_engine):
    """FastAPI TestClient with overridden get_db dependency."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

@pytest.fixture(scope="session")
def seeded_db(test_engine):
    """Pre-seeds a full dataset across all 5 scenarios for query tests."""
    Session = sessionmaker(bind=test_engine)
    session = Session()
    generator = SyntheticDataGenerator(seed=42)
    generator.generate_all(session)
    session.close()
    return test_engine
