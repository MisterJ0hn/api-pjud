import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class _UsuarioPermitidoMixin:
    """Usuarios (por RUT normalizado 'cuerpo-DV') que ven la causa privada en su "Mis Causas".
    Los altas/bajas las hace el worker al sincronizar (ver api/common/acceso.py)."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rut: Mapped[str] = mapped_column(String(12), nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _causa_fk(tabla: str):
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{tabla}.id", ondelete="CASCADE"), nullable=False, index=True
    )


class UsuarioCivilPermitido(_UsuarioPermitidoMixin, Base):
    __tablename__ = "usuario_civil_permitido"
    causa_id: Mapped[uuid.UUID] = _causa_fk("causas")
    __table_args__ = (UniqueConstraint("causa_id", "rut", name="uq_usuario_civil_permitido"),)


class UsuarioFamiliaPermitido(_UsuarioPermitidoMixin, Base):
    __tablename__ = "usuario_familia_permitido"
    causa_id: Mapped[uuid.UUID] = _causa_fk("causas_familia")
    __table_args__ = (UniqueConstraint("causa_id", "rut", name="uq_usuario_familia_permitido"),)


class UsuarioLaboralPermitido(_UsuarioPermitidoMixin, Base):
    __tablename__ = "usuario_laboral_permitido"
    causa_id: Mapped[uuid.UUID] = _causa_fk("causas_laboral")
    __table_args__ = (UniqueConstraint("causa_id", "rut", name="uq_usuario_laboral_permitido"),)


class UsuarioCobranzaPermitido(_UsuarioPermitidoMixin, Base):
    __tablename__ = "usuario_cobranza_permitido"
    causa_id: Mapped[uuid.UUID] = _causa_fk("causas_cobranza")
    __table_args__ = (UniqueConstraint("causa_id", "rut", name="uq_usuario_cobranza_permitido"),)


class UsuarioPenalPermitido(_UsuarioPermitidoMixin, Base):
    __tablename__ = "usuario_penal_permitido"
    causa_id: Mapped[uuid.UUID] = _causa_fk("causas_penal")
    __table_args__ = (UniqueConstraint("causa_id", "rut", name="uq_usuario_penal_permitido"),)
