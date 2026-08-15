import os
os.environ["DATABASE_URL"] = "sqlite:///./test_portfolio.db"
os.environ["GITHUB_WEBHOOK_SECRET"] = "test-secret"
import pytest
from app.core.database import Base, engine, SessionLocal

@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
@pytest.fixture
def db():
    session=SessionLocal()
    yield session
    session.close()
