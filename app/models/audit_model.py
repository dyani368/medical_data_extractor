from datetime import datetime, UTC
from sqlalchemy import ForeignKey, DateTime, JSON, Float, String, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class AgentAuditLog(Base):
    __tablename__ = "agent_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String, index=True, nullable=False) # e.g., "tool_execution", "agent_invocation"
    tool_name: Mapped[str] = mapped_column(String, nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON, nullable=True)
    outputs: Mapped[dict] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(String, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    user: Mapped["User"] = relationship()
    conversation: Mapped["Conversation"] = relationship()
