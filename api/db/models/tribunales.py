from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class TribunalCatalogo(Base):
    """Catalogo de cortes + tribunales, pre-cargado a mano (ver
    scripts/poblar_catalogo_tribunales.py): el sitio del PJUD no expone esta lista
    completa por ningun endpoint publico, hay que recorrer el combo de tribunales
    corte por corte con un navegador real. Se guarda una vez y se sirve desde aca en
    vez de consultar el sitio en cada request."""

    __tablename__ = "tribunales_catalogo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    competencia: Mapped[str] = mapped_column(String(20), nullable=False)
    corte_id: Mapped[int] = mapped_column(Integer, nullable=False)
    corte_nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    tribunal_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tribunal_nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("competencia", "corte_id", "tribunal_id", name="uq_tribunales_catalogo_clave"),
    )
