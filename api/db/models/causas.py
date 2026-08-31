import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base

ESTADOS_SYNC = ("Pendiente", "Sincronizando", "Completo", "Error")


class Causa(Base):
    __tablename__ = "causas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    competencia: Mapped[str] = mapped_column(String(20), nullable=False)
    corte: Mapped[int] = mapped_column(Integer, nullable=False)
    tribunal: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo: Mapped[str] = mapped_column(String(4), nullable=False)
    rol: Mapped[int] = mapped_column(Integer, nullable=False)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    rol_formateado: Mapped[str] = mapped_column(String(40), nullable=False)

    caratula: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fecha_ingreso: Mapped[str | None] = mapped_column(String(20), nullable=True)
    est_adm: Mapped[str | None] = mapped_column(String(200), nullable=True)
    proceso: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ubicacion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    estado_proceso: Mapped[str | None] = mapped_column(String(200), nullable=True)
    etapa: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tribunal_nombre: Mapped[str | None] = mapped_column(String(200), nullable=True)

    estado_sync: Mapped[str] = mapped_column(String(15), nullable=False, default="Pendiente")
    sync_detalle: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sync_iniciado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_ultima_sincronizacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    cuadernos: Mapped[list["Cuaderno"]] = relationship(back_populates="causa", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("competencia", "corte", "tribunal", "tipo", "rol", "anio", name="uq_causas_clave_natural"),
        CheckConstraint(f"estado_sync IN {ESTADOS_SYNC}", name="ck_causas_estado_sync"),
    )


class Cuaderno(Base):
    __tablename__ = "cuadernos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    nombre: Mapped[str] = mapped_column(String(300), nullable=False)

    causa: Mapped["Causa"] = relationship(back_populates="cuadernos")

    __table_args__ = (UniqueConstraint("causa_id", "numero", name="uq_cuadernos_causa_numero"),)
