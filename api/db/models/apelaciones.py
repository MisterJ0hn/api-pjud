"""Modelos de la competencia Corte de Apelaciones (recursos). Tablas propias
(`*_apelaciones`). Ver "solicitud Corte Apelaciones.md".

Una causa de Apelaciones es un RECURSO (apelacion, proteccion, amparo, ...) presentado ante
una Corte contra una causa de primera instancia ("expediente de origen"). La clave natural es
(corte, libro, rol, anio): el mismo rol/anio existe en varios libros de una misma Corte
("Civil", "Proteccion", "Amparo", "Contencioso Administrativo", ...), confirmado en vivo.
`libro` es "" mientras no se conoce (request sin libro y una sola coincidencia en PJUD).
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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base

ESTADOS_SYNC = ("Pendiente", "Sincronizando", "Completo", "Error")


class CausaApelaciones(Base):
    __tablename__ = "causas_apelaciones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Value del select `#conCorte` (90 = C.A. de Santiago, ver api/apelaciones/cortes.py).
    corte: Mapped[int] = mapped_column(Integer, nullable=False)
    libro: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    rol: Mapped[int] = mapped_column(Integer, nullable=False)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)

    # Cabecera pestana "Recurso".
    libro_texto: Mapped[str | None] = mapped_column(String(120), nullable=True)  # "Civil - 23414 - 2026"
    fecha: Mapped[str | None] = mapped_column(String(20), nullable=True)
    estado_recurso: Mapped[str | None] = mapped_column(String(100), nullable=True)
    estado_procesal: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ubicacion: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recurso: Mapped[str | None] = mapped_column(String(300), nullable=True)
    corte_nombre: Mapped[str | None] = mapped_column(String(120), nullable=True)
    certificado_envio_color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ebook_color: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Pestana "Expediente Primera Instancia" (causa de origen).
    origen_rol: Mapped[str | None] = mapped_column(String(60), nullable=True)  # "C - 711 - 2026"
    origen_tribunal: Mapped[str | None] = mapped_column(String(200), nullable=True)
    origen_caratulado: Mapped[str | None] = mapped_column(String(500), nullable=True)
    origen_materia: Mapped[str | None] = mapped_column(String(300), nullable=True)
    origen_ruc: Mapped[str | None] = mapped_column(String(60), nullable=True)
    origen_fecha_ingreso: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Relacion con la causa origen YA existente en nuestro sistema (best effort, resuelta
    # por el worker; sin FK porque puede ser de cualquier competencia).
    causa_origen_competencia: Mapped[str | None] = mapped_column(String(20), nullable=True)
    causa_origen_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    visibilidad: Mapped[str | None] = mapped_column(String(10), nullable=True)
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
        UniqueConstraint("corte", "libro", "rol", "anio", name="uq_causas_apelaciones_clave_natural"),
        CheckConstraint(f"estado_sync IN {ESTADOS_SYNC}", name="ck_causas_apelaciones_estado_sync"),
    )

    @property
    def rit(self) -> str:
        """Etiqueta para logs (el worker la usa igual que `rol_formateado` en civil)."""
        return self.libro_texto or f"{self.libro or '?'}-{self.rol}-{self.anio}"


class DocumentoApelaciones(Base):
    """Registro idempotente de un archivo descargado de una causa de Apelaciones."""

    __tablename__ = "documentos_apelaciones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    causa_apelaciones_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_apelaciones.id", ondelete="CASCADE"), nullable=False, index=True
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
        UniqueConstraint("causa_apelaciones_id", "clave_logica", name="uq_documentos_apelaciones_causa_clave"),
    )


def _causa_fk():
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_apelaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )


class MovimientoApelaciones(Base):
    """Pestana "Movimientos". Folio unico por causa (no hay cuadernos); `ocurrencia`
    desambigua folios repetidos."""

    __tablename__ = "movimientos_apelaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_apelaciones_id: Mapped[uuid.UUID] = _causa_fk()
    folio: Mapped[int] = mapped_column(Integer, nullable=False)
    ocurrencia: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tramite: Mapped[str | None] = mapped_column(String(300), nullable=True)
    descripcion: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    sala: Mapped[str | None] = mapped_column(String(100), nullable=True)
    estado: Mapped[str | None] = mapped_column(String(100), nullable=True)
    geo_latitud: Mapped[str | None] = mapped_column(String(30), nullable=True)
    geo_longitud: Mapped[str | None] = mapped_column(String(30), nullable=True)
    geo_corrector: Mapped[str | None] = mapped_column(String(30), nullable=True)
    hash_contenido: Mapped[str] = mapped_column(String(64), nullable=False)

    docs: Mapped[list["MovimientoApelacionesDoc"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan", order_by="MovimientoApelacionesDoc.orden"
    )
    anexos: Mapped[list["MovimientoApelacionesAnexo"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan", order_by="MovimientoApelacionesAnexo.orden"
    )
    geo_imagenes: Mapped[list["MovimientoApelacionesGeoImagen"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan", order_by="MovimientoApelacionesGeoImagen.orden"
    )

    __table_args__ = (
        Index("uq_movimientos_apelaciones_causa_folio", "causa_apelaciones_id", "folio", "ocurrencia", unique=True),
    )


class MovimientoApelacionesDoc(Base):
    __tablename__ = "movimientos_apelaciones_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("movimientos_apelaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_apelaciones.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)

    movimiento: Mapped["MovimientoApelaciones"] = relationship(back_populates="docs")

    __table_args__ = (UniqueConstraint("movimiento_id", "orden", name="uq_mov_apelaciones_doc_orden"),)


class MovimientoApelacionesAnexo(Base):
    __tablename__ = "movimientos_apelaciones_anexos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("movimientos_apelaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_apelaciones.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)

    movimiento: Mapped["MovimientoApelaciones"] = relationship(back_populates="anexos")

    __table_args__ = (UniqueConstraint("movimiento_id", "orden", name="uq_mov_apelaciones_anexo_orden"),)


class MovimientoApelacionesGeoImagen(Base):
    __tablename__ = "movimientos_apelaciones_geo_imagenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("movimientos_apelaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_apelaciones.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)

    movimiento: Mapped["MovimientoApelaciones"] = relationship(back_populates="geo_imagenes")

    __table_args__ = (UniqueConstraint("movimiento_id", "orden", name="uq_mov_apelaciones_geo_img_orden"),)


class LitiganteApelaciones(Base):
    """Pestana "Litigantes" (nombre en la API: `liquidantes`, ver Solicitud)."""

    __tablename__ = "litigantes_apelaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_apelaciones_id: Mapped[uuid.UUID] = _causa_fk()
    sujeto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rut: Mapped[str | None] = mapped_column(String(20), nullable=True)
    persona: Mapped[str | None] = mapped_column(String(10), nullable=True)
    razon_social: Mapped[str | None] = mapped_column(String(500), nullable=True)


class TextoApelaciones(Base):
    """Popup "Texto" de la cabecera (`modalAnexoRecursoApelaciones`): documentos del
    recurso. `target_id` = atributo `target` del form `formAnexRecurso`."""

    __tablename__ = "textos_apelaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_apelaciones_id: Mapped[uuid.UUID] = _causa_fk()
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doc_principal_icono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    doc_principal_color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_apelaciones.id"), nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (UniqueConstraint("causa_apelaciones_id", "orden", name="uq_textos_apelaciones_orden"),)


class AnexoCausaApelaciones(Base):
    """Popup "Anexo" de la cabecera (`modalAnexoEscritoApelaciones`)."""

    __tablename__ = "anexos_causa_apelaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_apelaciones_id: Mapped[uuid.UUID] = _causa_fk()
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_apelaciones.id"), nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    codigo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tipo_documento: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cantidad: Mapped[str | None] = mapped_column(String(20), nullable=True)
    observacion_documento: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (UniqueConstraint("causa_apelaciones_id", "orden", name="uq_anexos_causa_apelaciones_orden"),)


class RegistroApelaciones(Base):
    """Filas de las pestanas "Exhortos" e "Incompetencia", cuyas columnas no se han podido
    validar (no hay ejemplos con datos): se guardan crudas como JSON, `tipo` = 'exhorto' |
    'incompetencia'."""

    __tablename__ = "registros_apelaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_apelaciones_id: Mapped[uuid.UUID] = _causa_fk()
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    datos = mapped_column(JSONB, nullable=False)

    __table_args__ = (UniqueConstraint("causa_apelaciones_id", "tipo", "orden", name="uq_registros_apelaciones_orden"),)
