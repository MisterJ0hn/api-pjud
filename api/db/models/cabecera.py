import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class AnexoCausa(Base):
    __tablename__ = "anexos_causa"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos.id"), nullable=True)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (UniqueConstraint("causa_id", "referencia", "fecha", name="uq_anexos_causa_ref_fecha"),)


class InformacionReceptor(Base):
    __tablename__ = "informacion_receptor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cuaderno_nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)
    datos_retiro: Mapped[str | None] = mapped_column(String(300), nullable=True)
    fecha_retiro: Mapped[str | None] = mapped_column(String(60), nullable=True)
    estado: Mapped[str | None] = mapped_column(String(60), nullable=True)

    __table_args__ = (
        UniqueConstraint("causa_id", "cuaderno_nombre", "fecha_retiro", name="uq_info_receptor_causa_cuad_fecha"),
    )
