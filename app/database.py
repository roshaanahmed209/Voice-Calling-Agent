"""SQLAlchemy engine and session management."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.is_sqlite else {}

if settings.is_sqlite:
    # data/ is gitignored, so on a fresh clone or a fresh container it does not
    # exist. SQLite will not create a missing parent directory — it fails every
    # write with "attempt to write a readonly database", which surfaces to the
    # caller as a failed registration. Create it up front.
    db_path = settings.normalized_database_url.split("///", 1)[-1]
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.normalized_database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they do not exist.

    Trade-off: for a 3-hour build this beats wiring up Alembic. A real
    deployment would use migrations so that schema changes are reviewable.
    """
    from app import models  # noqa: F401  (registers the mappers)

    Base.metadata.create_all(bind=engine)
    _add_missing_call_columns()


def _add_missing_call_columns() -> None:
    """SQLite create_all will not add columns to an existing table."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "call_transcripts" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("call_transcripts")}
    statements = []
    if "direction" not in existing:
        statements.append(
            "ALTER TABLE call_transcripts ADD COLUMN direction VARCHAR(20) DEFAULT 'inbound'"
        )
    if "status" not in existing:
        statements.append(
            "ALTER TABLE call_transcripts ADD COLUMN status VARCHAR(20) DEFAULT 'ended'"
        )
    if "customer_name" not in existing:
        statements.append(
            "ALTER TABLE call_transcripts ADD COLUMN customer_name VARCHAR(120)"
        )
    if not statements:
        return
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
