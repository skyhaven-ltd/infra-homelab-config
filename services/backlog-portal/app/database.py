from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    get_settings().database_url,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("drafts")}
    additions = {
        "remote_external_id": "VARCHAR(256) NOT NULL DEFAULT ''",
        "remote_project_item_id": "VARCHAR(256) NOT NULL DEFAULT ''",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(
                    text(f"ALTER TABLE drafts ADD COLUMN {name} {definition}")
                )


def get_session():
    with SessionLocal() as session:
        yield session
