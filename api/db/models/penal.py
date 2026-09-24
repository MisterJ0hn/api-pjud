"""Modelos de la competencia Penal. Tablas propias (prefijo `*_penal`), espejo de
Cobranza (Historia causa-wide que junta todos los cuadernos, sin `cuaderno` en
consultar_movimientos_penal) con diferencias propias de Penal (ver Solicitud Penal.md):

- `tipo` es el NOMBRE del tipo de causa ("Ordinaria", "Exhorto", "Administrativa",
  "Extradición", "Militar"), no una letra -- por eso String(20) y no String(4).
- `rol` de la causa (string "A-1-2025") es el RIT/ROL tal cual lo muestra PJUD.
- Notificaciones traen Georreferencia (mapa + imagenes) igual que los movimientos de
  Familia/Laboral.
- Seccion "Relaciones" (nombre/materia/estado_causa/fecha_cambio_estado).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base

ESTADOS_SYNC = ("Pendiente", "Sincronizando", "Completo", "Error")


class CausaPenal(Base):
    __tablename__ = "causas_penal"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    corte: Mapped[int] = mapped_column(Integer, nullable=False)
    tribunal: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    rol: Mapped[int] = mapped_column(Integer, nullable=False)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    # ROL/RIT tal cual lo muestra PJUD (p. ej. "O-200-2025"); antes del primer sync es
    # un valor provisorio armado desde tipo/rol/anio.
    rit: Mapped[str] = mapped_column(String(40), nullable=False)

    caratula: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fecha_ingreso: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ruc: Mapped[str | None] = mapped_column(String(60), nullable=True)
    estado_adm: Mapped[str | None] = mapped_column(String(200), nullable=True)
    procedimiento: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ubicacion: Mapped[str | None] = mapped_column(String(200), nullable=True)
    proceso: Mapped[str | None] = mapped_column(String(300), nullable=True)
    forma_inicio: Mapped[str | None] = mapped_column(String(200), nullable=True)
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

    __table_args__ = (
        UniqueConstraint("corte", "tribunal", "tipo", "rol", "anio", name="uq_causas_penal_clave_natural"),
        CheckConstraint(f"estado_sync IN {ESTADOS_SYNC}", name="ck_causas_penal_estado_sync"),
    )


class DocumentoPenal(Base):
    """Registro idempotente de un archivo descargado de una causa Penal."""

    __tablename__ = "documentos_penal"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    causa_penal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_penal.id", ondelete="CASCADE"), nullable=False, index=True
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

    __table_args__ = (
        UniqueConstraint("causa_penal_id", "clave_logica", name="uq_documentos_penal_causa_clave"),
    )


class CuadernoPenal(Base):
    """Lista informativa de cuadernos (nombre/estado/etapa). No particiona Historia:
    consultar_movimientos_penal no recibe "cuaderno" (Solicitud Penal.md)."""

    __tablename__ = "cuadernos_penal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_penal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_penal.id", ondelete="CASCADE"), nullable=False, index=True
    )
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    nombre: Mapped[str] = mapped_column(String(300), nullable=False)
    estado_proceso: Mapped[str | None] = mapped_column(String(200), nullable=True)
    etapa: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (UniqueConstraint("causa_penal_id", "numero", name="uq_cuadernos_penal_causa_numero"),)


class HistoriaPenal(Base):
    """Pestana "Historia". `descripcion_tramite` puede traer un documento adjunto
    (ver `descripcion_tramite_doc_id`, mismo caso que Cobranza)."""

    __tablename__ = "historia_penal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_penal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_penal.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Ver comentario equivalente en `HistoriaCobranza`: la Historia de todos los cuadernos
    # se junta en esta tabla; `cuaderno_numero` evita colisiones de folio entre cuadernos.
    cuaderno_numero: Mapped[int | None] = mapped_column(Integer, nullable=True)
    folio_texto: Mapped[str] = mapped_column(String(12), nullable=False)
    folio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tramite: Mapped[str | None] = mapped_column(String(300), nullable=True)
    descripcion_tramite: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    descripcion_tramite_doc_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_penal.id"), nullable=True)
    descripcion_tramite_doc_color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fecha_firma: Mapped[str | None] = mapped_column(String(60), nullable=True)
    estado: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fecha_tramite: Mapped[str | None] = mapped_column(String(60), nullable=True)
    hash_contenido: Mapped[str] = mapped_column(String(64), nullable=False)
    ocurrencia: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    docs: Mapped[list["HistoriaPenalDoc"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan", order_by="HistoriaPenalDoc.orden"
    )
    anexos: Mapped[list["HistoriaPenalAnexo"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan", order_by="HistoriaPenalAnexo.orden"
    )

    __table_args__ = (
        Index(
            "uq_historia_penal_causa_folio",
            "causa_penal_id",
            "cuaderno_numero",
            "folio",
            "ocurrencia",
            unique=True,
            postgresql_where=text("folio_texto NOT LIKE '[%'"),
        ),
    )


class HistoriaPenalDoc(Base):
    __tablename__ = "historia_penal_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("historia_penal.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_penal.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)

    movimiento: Mapped["HistoriaPenal"] = relationship(back_populates="docs")

    __table_args__ = (UniqueConstraint("movimiento_id", "orden", name="uq_historia_penal_doc_mov_orden"),)


class HistoriaPenalAnexo(Base):
    __tablename__ = "historia_penal_anexos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("historia_penal.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_penal.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)

    movimiento: Mapped["HistoriaPenal"] = relationship(back_populates="anexos")

    __table_args__ = (UniqueConstraint("movimiento_id", "orden", name="uq_historia_penal_anexo_mov_orden"),)


class LitigantePenal(Base):
    __tablename__ = "litigantes_penal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_penal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_penal.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participantes: Mapped[str | None] = mapped_column(String(100), nullable=True)
    persona: Mapped[str | None] = mapped_column(String(10), nullable=True)
    razon_social: Mapped[str | None] = mapped_column(String(500), nullable=True)


class NotificacionPenal(Base):
    """Notificaciones con Georreferencia (popup, pestanas Mapas/Imagenes) por fila."""

    __tablename__ = "notificaciones_penal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_penal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_penal.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo_notificacion: Mapped[str | None] = mapped_column(String(60), nullable=True)
    estado_notificacion: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_notificacion: Mapped[str | None] = mapped_column(String(60), nullable=True)
    nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Columna "Estampado": documento (form POST) cuando existe; icono fa-ban si no.
    estampado_doc_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_penal.id"), nullable=True)
    geo_latitud: Mapped[str | None] = mapped_column(String(30), nullable=True)
    geo_longitud: Mapped[str | None] = mapped_column(String(30), nullable=True)
    geo_corrector: Mapped[str | None] = mapped_column(String(30), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    geo_imagenes: Mapped[list["NotificacionPenalGeoImagen"]] = relationship(
        back_populates="notificacion", cascade="all, delete-orphan", order_by="NotificacionPenalGeoImagen.orden"
    )

    __table_args__ = (
        UniqueConstraint("causa_penal_id", "contenido_hash", name="uq_notificaciones_penal_causa_hash"),
    )


class NotificacionPenalGeoImagen(Base):
    __tablename__ = "notificaciones_penal_geo_imagenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notificacion_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("notificaciones_penal.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_penal.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)

    notificacion: Mapped["NotificacionPenal"] = relationship(back_populates="geo_imagenes")

    __table_args__ = (UniqueConstraint("notificacion_id", "orden", name="uq_notif_penal_geo_img_orden"),)


class RelacionPenal(Base):
    __tablename__ = "relaciones_penal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_penal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_penal.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)
    materia: Mapped[str | None] = mapped_column(String(500), nullable=True)
    estado_causa: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fecha_cambio_estado: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("causa_penal_id", "contenido_hash", name="uq_relaciones_penal_causa_hash"),
    )
