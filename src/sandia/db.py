from collections.abc import Iterator

from fastapi import Request
from sqlmodel import Session, SQLModel, create_engine, text

from .config import Settings


def create_db_engine(settings: Settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{settings.db_path}")
    SQLModel.metadata.create_all(engine)
    _ensure_user_columns(engine)
    return engine


# Columns added to User after its table was first created, with their DDL.
_ADDED_USER_COLUMNS = {
    "theme": "TEXT NOT NULL DEFAULT 'dark'",
    "language": "TEXT NOT NULL DEFAULT 'en'",
}


def _ensure_user_columns(engine) -> None:
    # create_all() only creates missing tables, never adds columns to an
    # existing one - a pre-existing sandia.db from before these columns were
    # added to User needs this one-off, idempotent backfill.
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(user)"))}
        for name, ddl in _ADDED_USER_COLUMNS.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE user ADD COLUMN {name} {ddl}"))
        conn.commit()


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session
