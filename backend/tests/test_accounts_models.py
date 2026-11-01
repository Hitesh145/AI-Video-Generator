from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from accounts_helpers import make_session_factory
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from accounts.models import AuthSession, User, Video


def test_email_must_be_unique():
    factory = make_session_factory()
    with factory.begin() as session:
        session.add(User(user_id=str(uuid4()), email="a@x.com", password_hash="h"))
    with pytest.raises(IntegrityError):
        with factory.begin() as session:
            session.add(User(user_id=str(uuid4()), email="a@x.com", password_hash="h"))


def test_session_and_video_rows_reference_their_user():
    factory = make_session_factory()
    user_id = str(uuid4())
    with factory.begin() as session:
        session.add(User(user_id=user_id, email="a@x.com", password_hash="h"))
        session.add(AuthSession(session_id=str(uuid4()), user_id=user_id, token_hash="t" * 64,
                                expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
        session.add(Video(video_id=str(uuid4()), user_id=user_id, run_dir="binary-search-ab12", title="Binary Search"))
    with factory() as session:
        video = session.scalars(select(Video)).one()
        assert (video.kind, video.user_id) == ("topic", user_id)


def test_run_dir_is_unique_per_video():
    factory = make_session_factory()
    user_id = str(uuid4())
    with factory.begin() as session:
        session.add(User(user_id=user_id, email="a@x.com", password_hash="h"))
        session.add(Video(video_id=str(uuid4()), user_id=user_id, run_dir="same-run", title="One"))
    with pytest.raises(IntegrityError):
        with factory.begin() as session:
            session.add(Video(video_id=str(uuid4()), user_id=user_id, run_dir="same-run", title="Two"))


def test_importing_only_the_rag_models_still_registers_the_users_table():
    # Alembic and the repository import rag.db_models alone; RAGDocument.user_id points at users.
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "import rag.db_models as m; print('users' in m.Base.metadata.tables)"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "True"
