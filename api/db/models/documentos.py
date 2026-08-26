import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base


class Documento(Base):
    """Registro idempotente de un archivo descargado. `clave_logica` es unica dentro de la
    causa (y del cuaderno cuando aplica) y es lo que permite reconocer "ya lo tengo" en un
    resync sin volver a llamar a PJUD (ver disenio de sincronizacion incremental)."""

    __tablename__ = "documentos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    causa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cuaderno_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cuadernos.id", ondelete="CASCADE"), nullable=True, index=True
    )

    categoria: Mapped[str] = mapped_column(String(40), nullable=False)
    clave_logica: Mapped[str] = mapped_column(String(160), nullable=False)
    nombre_archivo: Mapped[str] = mapped_column(String(160), nullable=False)
    ruta_archivo: Mapped[str] = mapped_column(String(1000), nullable=False)
    hash_contenido_fila_padre: Mapped[str | None] = mapped_column(String(64), nullable=True)
    referencia_origen: Mapped[str | None] = mapped_column(String(300), nullable=True)

    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("causa_id", "clave_logica", name="uq_documentos_causa_clave_logica"),)
