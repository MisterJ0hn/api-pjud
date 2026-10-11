import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class AccesoVerificado(Base):
    """Cache de verificaciones exitosas de acceso a una causa privada (aparece en Mis Causas
    del abogado). `huella` es un HMAC de rut+clave+metodo_login: no se guardan credenciales y
    una clave distinta no reutiliza la verificacion."""

    __tablename__ = "acceso_verificado"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    competencia: Mapped[str] = mapped_column(String(20), nullable=False)
    causa_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    huella: Mapped[str] = mapped_column(String(64), nullable=False)
    verificado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("competencia", "causa_id", "huella", name="uq_acceso_verificado"),)
