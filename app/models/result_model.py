from __future__ import annotations
from datetime import datetime,timedelta, UTC
from sqlalchemy import ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

from sqlalchemy.dialects.postgresql import JSONB

class Result(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    summary: Mapped[str] = mapped_column(nullable=False)
    key_entities: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    category: Mapped[str] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=lambda: datetime.now(UTC))

    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)

    document: Mapped["Document"] = relationship(back_populates="results_created")