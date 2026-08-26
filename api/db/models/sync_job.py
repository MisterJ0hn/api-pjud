import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base

ESTADOS_JOB = ("pendiente", "en_progreso", "completo", "error")


class SyncJob(Base):
    """Cola de trabajos de sincronizacion, respaldada en Postgres. Reemplaza a un broker
    externo (Celery/Redis): solo puede haber una sesion de Playwright activa a la vez, asi
    que no hay paralelismo real que ganar con un broker distribuido."""

    __tablename__ = "sync_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    estado: Mapped[str] = mapped_column(String(15), nullable=False, default="pendiente")
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_mensaje: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    encolado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    iniciado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalizado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (CheckConstraint(f"estado IN {ESTADOS_JOB}", name="ck_sync_job_estado"),)
