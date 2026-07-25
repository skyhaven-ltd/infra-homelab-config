from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_dir(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return
    db_path = Path(database_url.removeprefix(prefix))
    db_path.parent.mkdir(parents=True, exist_ok=True)


settings = get_settings()
_ensure_sqlite_dir(settings.database_url)

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # create_all does not add columns to an existing SQLite database. Keep this
    # small migration here until the service warrants a dedicated migration tool.
    if engine.dialect.name == "sqlite":
        columns = {
            column["name"] for column in inspect(engine).get_columns("questions")
        }
        if "choices_json" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE questions ADD COLUMN choices_json TEXT NOT NULL "
                        "DEFAULT '[]'"
                    )
                )


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
