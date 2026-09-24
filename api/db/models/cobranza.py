"""Modelos de la competencia Cobranza. Tablas propias (no se reusan las de civil/
familia/laboral). Segun Solicitud Cobranza.md: el tribunal de Cobranza es distinto al
de Laboral/Civil (se resuelve via /catalogo/tribunales?competencia=cobranza) y la causa
puede tener VARIOS cuadernos (ej. "1 - principal", "2 - Apremio Ejecutivo Obligación de
Dar") -- igual que Civil -- pero, a diferencia de Civil, consultar_movimientos_cobranza
NO recibe "cuadeno": la Historia/Litigantes/Notificaciones/Diligencias/Liquidacion
cuelgan directo de la causa (flat), igual que Laboral/Familia. `cuadernos` en el detalle
de causa es solo informativo (nombre/estado/etapa por cuaderno), como en Civil.

Nota: estos modelos siguen literalmente el contrato de Solicitud Cobranza.md; a
diferencia de civil/familia/laboral no hay HTML de PJUD confirmado en vivo todavia
(ver ejemplos/causa cobranza/*.html, no explorados aun), asi que nombres/anchos de
columna pueden necesitar ajuste cuando se implemente el worker de sincronizacion.
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


class CausaCobranza(Base):
    __tablename__ = "causas_cobranza"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    corte: Mapped[int] = mapped_column(Integer, nullable=False)
    tribunal: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo: Mapped[str] = mapped_column(String(4), nullable=False)
    rol: Mapped[int] = mapped_column(Integer, nullable=False)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    rit: Mapped[str] = mapped_column(String(40), nullable=False)

    caratula: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fecha_ingreso: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ruc: Mapped[str | None] = mapped_column(String(60), nullable=True)
    proceso: Mapped[str | None] = mapped_column(String(300), nullable=True)
    forma_inicio: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # No esta en Solicitud Cobranza.md pero SI esta en la cabecera real de PJUD
    # (confirmado en vivo, ejemplos/causa cobranza/*.html: "Est. Adm.: Archivada" /
    # "Sin archivar") -- igual que civil/laboral, que si lo exponen.
    est_adm: Mapped[str | None] = mapped_column(String(200), nullable=True)
    estado_proceso: Mapped[str | None] = mapped_column(String(200), nullable=True)
    etapa: Mapped[str | None] = mapped_column(String(300), nullable=True)
    juez_asignado: Mapped[str | None] = mapped_column(String(300), nullable=True)
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
        UniqueConstraint("corte", "tribunal", "tipo", "rol", "anio", name="uq_causas_cobranza_clave_natural"),
        CheckConstraint(f"estado_sync IN {ESTADOS_SYNC}", name="ck_causas_cobranza_estado_sync"),
    )


class DocumentoCobranza(Base):
    """Registro idempotente de un archivo descargado de una causa Cobranza. Espejo de
    `DocumentoLaboral`."""

    __tablename__ = "documentos_cobranza"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    causa_cobranza_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_cobranza.id", ondelete="CASCADE"), nullable=False, index=True
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
        UniqueConstraint("causa_cobranza_id", "clave_logica", name="uq_documentos_cobranza_causa_clave"),
    )


class CuadernoCobranza(Base):
    """Lista informativa de cuadernos de la causa (nombre/estado/etapa) -- igual que
    `Cuaderno` (civil), pero sin ser la clave de particion de Historia/Litigantes/etc:
    consultar_movimientos_cobranza no recibe "cuadeno" (ver Solicitud Cobranza.md)."""

    __tablename__ = "cuadernos_cobranza"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_cobranza_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_cobranza.id", ondelete="CASCADE"), nullable=False, index=True
    )
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    nombre: Mapped[str] = mapped_column(String(300), nullable=False)
    estado_proceso: Mapped[str | None] = mapped_column(String(200), nullable=True)
    etapa: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (UniqueConstraint("causa_cobranza_id", "numero", name="uq_cuadernos_cobranza_causa_numero"),)


class AnexoCausaCobranza(Base):
    """Popup "Anexo de la Causa" de la cabecera -- espejo de `AnexoCausa` (civil)."""

    __tablename__ = "anexos_causa_cobranza"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_cobranza_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_cobranza.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_cobranza.id"), nullable=True)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)
    target: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("causa_cobranza_id", "referencia", "fecha", name="uq_anexos_causa_cobranza_ref_fecha"),
    )


class InformacionReceptorCobranza(Base):
    """Espejo de `InformacionReceptor` (civil): una fila por cuaderno con datos de
    retiro/estado de la diligencia del receptor."""

    __tablename__ = "informacion_receptor_cobranza"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_cobranza_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_cobranza.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cuaderno_nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)
    datos_retiro: Mapped[str | None] = mapped_column(String(300), nullable=True)
    fecha_retiro: Mapped[str | None] = mapped_column(String(60), nullable=True)
    estado: Mapped[str | None] = mapped_column(String(60), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "causa_cobranza_id", "cuaderno_nombre", "fecha_retiro", name="uq_info_receptor_cobranza_causa_cuad_fecha"
        ),
    )


class HistoriaCobranza(Base):
    """Pestana "Historia". Misma forma general que `MovimientoLaboral`/`MovimientoHistoria`
    (folio/etapa/tramite/descripcion_tramite/fecha_tramite + Georref.), con 2 campos
    propios de Cobranza: `estado_firma` (columna "Firmado"/etc.) y la posibilidad de que
    `descripcion_tramite` traiga un documento adjunto (ver `descripcion_tramite_doc_id`
    -- Solicitud Cobranza.md muestra un ejemplo donde ese campo es un objeto
    {descripcion, doc} en vez de un string plano)."""

    __tablename__ = "historia_cobranza"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_cobranza_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_cobranza.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # La causa puede tener varios cuadernos (confirmado: selector "Historia Causa
    # Cuaderno" en la cabecera del modal, ej. "1 - principal" / "2 - Apremio Ejecutivo
    # Obligación de Dar") pero consultar_movimientos_cobranza no recibe "cuadeno"
    # (Solicitud Cobranza.md): la Historia de todos los cuadernos se junta en esta misma
    # tabla. `cuaderno_numero` evita que dos cuadernos con el mismo folio colisionen en
    # el indice unico de abajo -- NULL cuando la causa tiene un solo cuaderno.
    cuaderno_numero: Mapped[int | None] = mapped_column(Integer, nullable=True)
    folio_texto: Mapped[str] = mapped_column(String(12), nullable=False)
    folio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    etapa: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tramite: Mapped[str | None] = mapped_column(String(300), nullable=True)
    descripcion_tramite: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    descripcion_tramite_doc_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_cobranza.id"), nullable=True)
    descripcion_tramite_doc_color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    estado_firma: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_tramite: Mapped[str | None] = mapped_column(String(60), nullable=True)
    hash_contenido: Mapped[str] = mapped_column(String(64), nullable=False)
    ocurrencia: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    geo_latitud: Mapped[str | None] = mapped_column(String(30), nullable=True)
    geo_longitud: Mapped[str | None] = mapped_column(String(30), nullable=True)
    geo_corrector: Mapped[str | None] = mapped_column(String(30), nullable=True)

    docs: Mapped[list["HistoriaCobranzaDoc"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan", order_by="HistoriaCobranzaDoc.orden"
    )
    anexos: Mapped[list["HistoriaCobranzaAnexo"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan", order_by="HistoriaCobranzaAnexo.orden"
    )
    geo_imagenes: Mapped[list["HistoriaCobranzaGeoImagen"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan", order_by="HistoriaCobranzaGeoImagen.orden"
    )

    __table_args__ = (
        Index(
            "uq_historia_cobranza_causa_folio",
            "causa_cobranza_id",
            "cuaderno_numero",
            "folio",
            "ocurrencia",
            unique=True,
            postgresql_where=text("folio_texto NOT LIKE '[%'"),
        ),
    )


class HistoriaCobranzaDoc(Base):
    __tablename__ = "historia_cobranza_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("historia_cobranza.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_cobranza.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)

    movimiento: Mapped["HistoriaCobranza"] = relationship(back_populates="docs")

    __table_args__ = (UniqueConstraint("movimiento_id", "orden", name="uq_historia_cobranza_doc_mov_orden"),)


class HistoriaCobranzaAnexo(Base):
    __tablename__ = "historia_cobranza_anexos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("historia_cobranza.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_cobranza.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)

    movimiento: Mapped["HistoriaCobranza"] = relationship(back_populates="anexos")

    __table_args__ = (UniqueConstraint("movimiento_id", "orden", name="uq_historia_cobranza_anexo_mov_orden"),)


class HistoriaCobranzaGeoImagen(Base):
    __tablename__ = "historia_cobranza_geo_imagenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("historia_cobranza.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_cobranza.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)

    movimiento: Mapped["HistoriaCobranza"] = relationship(back_populates="geo_imagenes")

    __table_args__ = (UniqueConstraint("movimiento_id", "orden", name="uq_historia_cobranza_geo_img_mov_orden"),)


class LitiganteCobranza(Base):
    __tablename__ = "litigantes_cobranza"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_cobranza_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_cobranza.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sujeto: Mapped[str | None] = mapped_column(String(60), nullable=True)
    rut: Mapped[str | None] = mapped_column(String(15), nullable=True)
    persona: Mapped[str | None] = mapped_column(String(10), nullable=True)
    razon_social: Mapped[str | None] = mapped_column(String(500), nullable=True)


class NotificacionCobranza(Base):
    __tablename__ = "notificaciones_cobranza"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_cobranza_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_cobranza.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo_notificacion: Mapped[str | None] = mapped_column(String(60), nullable=True)
    estado_notificacion: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_notificacion: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_tramite: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tramite: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tipo_part: Mapped[str | None] = mapped_column(String(60), nullable=True)
    nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("causa_cobranza_id", "contenido_hash", name="uq_notificaciones_cobranza_causa_hash"),
    )


class DiligenciaCobranza(Base):
    """A diferencia de Laboral: columnas propias `destinatario`/`responsable` en vez de
    `referencia`."""

    __tablename__ = "diligencias_cobranza"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_cobranza_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_cobranza.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_ida_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_cobranza.id"), nullable=True)
    doc_vta_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_cobranza.id"), nullable=True)
    estado_diligencia: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ruc: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tipo_diligencia: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fecha_tramite: Mapped[str | None] = mapped_column(String(60), nullable=True)
    destinatario: Mapped[str | None] = mapped_column(String(300), nullable=True)
    responsable: Mapped[str | None] = mapped_column(String(300), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("causa_cobranza_id", "contenido_hash", name="uq_diligencias_cobranza_causa_hash"),
    )


class LiquidacionCobranza(Base):
    """A diferencia de Laboral: columnas propias `fecha_liquidacion`/`cuaderno`/`estado`
    en vez de `rut`/`nombre`. `liquidacion` es un documento descargable (form GET
    docLiquidacionCobranza.php), no texto plano -- confirmado en vivo
    (ejemplos/causa cobranza/diligencias.html, causa C-10-2025)."""

    __tablename__ = "liquidaciones_cobranza"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_cobranza_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_cobranza.id", ondelete="CASCADE"), nullable=False, index=True
    )
    liquidacion_doc_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_cobranza.id"), nullable=True)
    fecha_liquidacion: Mapped[str | None] = mapped_column(String(60), nullable=True)
    cuaderno: Mapped[str | None] = mapped_column(String(300), nullable=True)
    estado: Mapped[str | None] = mapped_column(String(60), nullable=True)
    monto_liquido: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("causa_cobranza_id", "contenido_hash", name="uq_liquidaciones_cobranza_causa_hash"),
    )


class DocumentoLaboralCobranza(Base):
    """Popup "Detalle Documentos Laboral" (`modalDocumentoLabCobranza`, cabecera -> campo
    "Documentos Laboral"): lista Doc./Fecha/Referencia, descarga por POST
    (docLaboralCobranza.php) -- confirmado en vivo (causa C-10-2025). Misma forma que
    `AnexoCausaCobranza`; tabla propia porque cuelga de un campo de cabecera distinto."""

    __tablename__ = "documentos_laboral_cobranza"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_cobranza_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_cobranza.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_cobranza.id"), nullable=True)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "causa_cobranza_id", "referencia", "fecha", name="uq_documentos_laboral_cobranza_ref_fecha"
        ),
    )
