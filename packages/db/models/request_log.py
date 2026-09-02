"""Request log — append-only log of every chat completion."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.models.base import Base, SoftDeleteMixin, UUIDMixin


class RequestLog(Base, UUIDMixin, SoftDeleteMixin):
    __tablename__ = "requests_log"
    __table_args__ = (
        Index("ix_requests_log_ws_created", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # indexed for the budget sum i do per key in execute_chat
    api_key_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    model_requested: Mapped[str] = mapped_column(String(100), nullable=False)
    model_resolved: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    routing_strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    fallback_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_microcents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status_code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_streaming: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
