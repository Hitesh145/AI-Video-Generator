from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from accounts.models import AuthSession, User, Video
from papers.models import Paper
from rag.db_models import Base


def make_session_factory() -> sessionmaker:
    """In-memory SQLite with only the account tables (the RAG tables need PostgreSQL types)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[User.__table__, AuthSession.__table__, Video.__table__, Paper.__table__])
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
