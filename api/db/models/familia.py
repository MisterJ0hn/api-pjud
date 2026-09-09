"""Modelos de la competencia Familia. Tablas propias (no se reusan las de civil): la
cabecera y las secciones del modal de detalle de Familia difieren lo suficiente
(RIT/RUC/Forma Inicio, secciones Materias/Plazos/Diligencias, sin Escritos por Resolver
ni Exhortos) como para que compartir tablas obligara a un monton de columnas nullable y
ramas por competencia. Familia es SIEMPRE cuaderno unico, asi que aca no hay tabla
`cuadernos`: las secciones cuelgan directo de `causas_familia`.
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


class CausaFamilia(Base):
    __tablename__ = "causas_familia"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    corte: Mapped[int] = mapped_column(Integer, nullable=False)
    tribunal: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo: Mapped[str] = mapped_column(String(4), nullable=False)
    rol: Mapped[int] = mapped_column(Integer, nullable=False)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    # RIT tal cual la muestra PJUD ("F-1234-2026"). Nombre `rit` en vez de `rol_formateado`
    # para alinear con el contrato de Familia (`consultar_familia` devuelve `rit`).
    rit: Mapped[str] = mapped_column(String(40), nullable=False)

    caratula: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ruc: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_ingreso: Mapped[str | None] = mapped_column(String(20), nullable=True)
    proceso: Mapped[str | None] = mapped_column(String(300), nullable=True)
    forma_inicio: Mapped[str | None] = mapped_column(String(200), nullable=True)
    est_adm: Mapped[str | None] = mapped_column(String(200), nullable=True)
    etapa: Mapped[str | None] = mapped_column(String(300), nullable=True)
    estado_proceso: Mapped[str | None] = mapped_column(String(200), nullable=True)
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
        UniqueConstraint("corte", "tribunal", "tipo", "rol", "anio", name="uq_causas_familia_clave_natural"),
        CheckConstraint(f"estado_sync IN {ESTADOS_SYNC}", name="ck_causas_familia_estado_sync"),
    )


class DocumentoFamilia(Base):
    """Registro idempotente de un archivo descargado de una causa de Familia. Espejo de
    `Documento` pero sin `cuaderno_id` (Familia es cuaderno unico). `clave_logica` es
    unica dentro de la causa y es lo que permite el "ya lo tengo" en un resync."""

    __tablename__ = "documentos_familia"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    causa_familia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_familia.id", ondelete="CASCADE"), nullable=False, index=True
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
        UniqueConstraint("causa_familia_id", "clave_logica", name="uq_documentos_familia_causa_clave"),
    )


class AnexoCausaFamilia(Base):
    """Filas del sub-modal "Anexos de la causa" de la cabecera (Doc./Fecha/Referencia)."""

    __tablename__ = "anexos_causa_familia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_familia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_familia.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_familia.id"), nullable=True)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        UniqueConstraint("causa_familia_id", "referencia", "fecha", name="uq_anexos_causa_familia_ref_fecha"),
    )


class MovimientoHistoriaFamilia(Base):
    __tablename__ = "movimientos_historia_familia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_familia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_familia.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Folio tal cual lo muestra PJUD: normalmente un entero ("33"). Se mantiene el manejo
    # de folios de exhorto ("[6E]") por robustez aunque Familia no suele traerlos.
    folio_texto: Mapped[str] = mapped_column(String(12), nullable=False)
    folio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    etapa: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # En Familia la columna es "Estado" (donde civil trae "Foja").
    estado: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tramite: Mapped[str | None] = mapped_column(String(300), nullable=True)
    descripcion_tramite: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    fecha_tramite: Mapped[str | None] = mapped_column(String(60), nullable=True)
    hash_contenido: Mapped[str] = mapped_column(String(64), nullable=False)
    ocurrencia: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    docs: Mapped[list["MovimientoHistoriaFamiliaDoc"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan", order_by="MovimientoHistoriaFamiliaDoc.orden"
    )
    anexos: Mapped[list["MovimientoHistoriaFamiliaAnexo"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan", order_by="MovimientoHistoriaFamiliaAnexo.orden"
    )

    __table_args__ = (
        # Folios normales: clave natural (causa, folio, ocurrencia). Indice parcial que
        # excluye los "[NE]" de exhorto (que se reemplazan enteros cada sync).
        Index(
            "uq_historia_familia_causa_folio",
            "causa_familia_id",
            "folio",
            "ocurrencia",
            unique=True,
            postgresql_where=text("folio_texto NOT LIKE '[%'"),
        ),
    )


class MovimientoHistoriaFamiliaDoc(Base):
    __tablename__ = "movimientos_historia_familia_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("movimientos_historia_familia.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_familia.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)

    movimiento: Mapped["MovimientoHistoriaFamilia"] = relationship(back_populates="docs")

    __table_args__ = (
        UniqueConstraint("movimiento_id", "orden", name="uq_historia_familia_doc_mov_orden"),
    )


class MovimientoHistoriaFamiliaAnexo(Base):
    __tablename__ = "movimientos_historia_familia_anexos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("movimientos_historia_familia.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_familia.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    folio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    nombre_documento: Mapped[str | None] = mapped_column(String(300), nullable=True)
    observacion: Mapped[str | None] = mapped_column(String(500), nullable=True)

    movimiento: Mapped["MovimientoHistoriaFamilia"] = relationship(back_populates="anexos")

    __table_args__ = (
        UniqueConstraint("movimiento_id", "orden", name="uq_historia_familia_anexo_mov_orden"),
    )


class LitiganteFamilia(Base):
    __tablename__ = "litigantes_familia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_familia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_familia.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sujeto: Mapped[str | None] = mapped_column(String(60), nullable=True)
    rut: Mapped[str | None] = mapped_column(String(15), nullable=True)
    persona: Mapped[str | None] = mapped_column(String(10), nullable=True)
    razon_social: Mapped[str | None] = mapped_column(String(500), nullable=True)


class MateriaFamilia(Base):
    __tablename__ = "materias_familia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_familia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_familia.id", ondelete="CASCADE"), nullable=False, index=True
    )
    codigo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    glosa: Mapped[str | None] = mapped_column(String(500), nullable=True)
    estado: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_termino: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("causa_familia_id", "contenido_hash", name="uq_materias_familia_causa_hash"),
    )


class PlazoFamilia(Base):
    __tablename__ = "plazos_familia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_familia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_familia.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo_plazo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ambito_afectado: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fecha_inicio: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_termino: Mapped[str | None] = mapped_column(String(60), nullable=True)
    duracion: Mapped[str | None] = mapped_column(String(60), nullable=True)
    estado: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tramite: Mapped[str | None] = mapped_column(String(300), nullable=True)
    fecha_suspension: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_reactivacion: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("causa_familia_id", "contenido_hash", name="uq_plazos_familia_causa_hash"),
    )


class NotificacionFamilia(Base):
    __tablename__ = "notificaciones_familia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_familia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_familia.id", ondelete="CASCADE"), nullable=False, index=True
    )
    estado_fecha_notif: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tipo_notif: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ente_notif: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ruc: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_tramite: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tipo_parte: Mapped[str | None] = mapped_column(String(60), nullable=True)
    nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tramite: Mapped[str | None] = mapped_column(String(300), nullable=True)
    certificacion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("causa_familia_id", "contenido_hash", name="uq_notificaciones_familia_causa_hash"),
    )


class DiligenciaFamilia(Base):
    __tablename__ = "diligencias_familia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_familia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_familia.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_solicitud_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_familia.id"), nullable=True)
    doc_respuesta_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_familia.id"), nullable=True)
    estado_diligencia: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tipo_diligencia: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fecha_tramite: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("causa_familia_id", "contenido_hash", name="uq_diligencias_familia_causa_hash"),
    )
