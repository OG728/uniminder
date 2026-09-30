from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base


def _ensure_sqlite_parent(url: str) -> None:
    if url.startswith("sqlite:///"):
        raw = url.removeprefix("sqlite:///")
        if raw != ":memory:" and not raw.startswith("//"):
            Path(raw).parent.mkdir(parents=True, exist_ok=True)


def create_engine_from_settings():
    settings = get_settings()
    _ensure_sqlite_parent(settings.database_url)
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    eng = create_engine(settings.database_url, connect_args=connect_args)

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # noqa: ARG001
        if settings.database_url.startswith("sqlite"):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return eng


engine = create_engine_from_settings()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _ensure_assignment_submission_columns() -> None:
    """Add submission columns on databases created before Canvas completion tracking."""
    if engine.dialect.name != "sqlite":
        return
    insp = inspect(engine)
    if "assignments" not in insp.get_table_names():
        return
    cols = {col["name"] for col in insp.get_columns("assignments")}
    statements: list[str] = []
    if "submission_state" not in cols:
        statements.append("ALTER TABLE assignments ADD COLUMN submission_state VARCHAR(32)")
    if "submitted_at" not in cols:
        statements.append("ALTER TABLE assignments ADD COLUMN submitted_at DATETIME")
    if "canvas_completed" not in cols:
        statements.append(
            "ALTER TABLE assignments ADD COLUMN canvas_completed BOOLEAN NOT NULL DEFAULT 0"
        )
    if not statements:
        return
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_assignment_submission_columns()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
