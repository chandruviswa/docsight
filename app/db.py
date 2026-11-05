import os
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./docsight.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    method: Mapped[str] = mapped_column(String(10))
    page_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), index=True)
    fields: Mapped[dict] = mapped_column(JSON)
    line_items: Mapped[list] = mapped_column(JSON)
    issues: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def as_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "method": self.method,
            "page_count": self.page_count,
            "status": self.status,
            "fields": self.fields,
            "line_items": self.line_items,
            "issues": self.issues,
            # SQLite drops the timezone on the way back, PostgreSQL doesn't.
            "created_at": self.created_at.replace(tzinfo=timezone.utc).isoformat(),
        }


def init_db():
    Base.metadata.create_all(engine)


def get_session():
    with SessionLocal() as session:
        yield session
