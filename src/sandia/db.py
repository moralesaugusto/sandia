from collections.abc import Iterator

from fastapi import Request
from sqlmodel import Session, SQLModel, create_engine, text

from .config import Settings


def create_db_engine(settings: Settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{settings.db_path}")
    SQLModel.metadata.create_all(engine)
    _ensure_added_columns(engine)
    return engine


# Columns added to a table after it was first created, with their DDL.
_ADDED_COLUMNS = {
    "user": {
        "theme": "TEXT NOT NULL DEFAULT 'dark'",
        "language": "TEXT NOT NULL DEFAULT 'en'",
    },
    "aisettings": {
        "connect_timeout": "INTEGER NOT NULL DEFAULT 10",
        "reply_timeout": "INTEGER NOT NULL DEFAULT 300",
        "system_prompt": "TEXT NOT NULL DEFAULT ''",
    },
}


def _ensure_added_columns(engine) -> None:
    # create_all() only creates missing tables, never adds columns to an
    # existing one - a pre-existing sandia.db from before these columns were
    # added needs this one-off, idempotent backfill.
    with engine.connect() as conn:
        for table, added in _ADDED_COLUMNS.items():
            columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for name, ddl in added.items():
                if name not in columns:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        conn.commit()


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session
