from __future__ import annotations
from datetime import datetime,timedelta, UTC
from sqlalchemy import ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from typing import List

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    filename: Mapped[str] = mapped_column(nullable=False)
    file_url: Mapped[str] = mapped_column(unique=True, nullable=False)
    raw_content: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=lambda: datetime.now(UTC))

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    results_created: Mapped[List["Result"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    user: Mapped["User"] = relationship(back_populates="docs_created")