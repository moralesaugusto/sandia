from collections.abc import Iterator

from fastapi import Request
from sqlmodel import Session, SQLModel, create_engine, text

from .config import Settings


def create_db_engine(settings: Settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{settings.db_path}")
    SQLModel.metadata.create_all(engine)
    _ensure_user_theme_column(engine)
    return engine


def _ensure_user_theme_column(engine) -> None:
    # create_all() only creates missing tables, never adds columns to an
    # existing one - a pre-existing sandia.db from before "theme" was added
    # to User needs this one-off, idempotent backfill.
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(user)"))}
        if "theme" not in columns:
            conn.execute(text("ALTER TABLE user ADD COLUMN theme TEXT NOT NULL DEFAULT 'dark'"))
            conn.commit()


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session
