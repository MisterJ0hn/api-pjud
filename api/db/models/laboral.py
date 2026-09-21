"""Modelos de la competencia Laboral. Tablas propias (no se reusan las de civil/familia):
aunque la forma de Movimientos es practicamente identica a la de Familia (folio/etapa/
estado/tramite/descripcion_tramite/fecha_tramite + georeferencia), Laboral agrega
secciones propias (Liquidacion, Escritos Pendientes) y campos propios en Litigantes
(estado, defensor) y Diligencias (doc_ida/doc_vta, RIT/RUC/Referencia) que no tiene
Familia. Laboral es SIEMPRE cuaderno unico (ver Solicitud Laboral.md: consultar_movimientos_laboral
no recibe "cuadeno"), asi que -- igual que Familia -- no hay tabla `cuadernos`: las
secciones cuelgan directo de `causas_laboral`.

A diferencia de Familia (siempre privada), Laboral admite sincronizacion PUBLICA
(Consulta Unificada) o PRIVADA (con rut/clave/metodo_login, "Mis Causas"), igual que
Civil -- ver `api/laboral/router.py`.
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


class CausaLaboral(Base):
    __tablename__ = "causas_laboral"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    corte: Mapped[int] = mapped_column(Integer, nullable=False)
    tribunal: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo: Mapped[str] = mapped_column(String(4), nullable=False)
    rol: Mapped[int] = mapped_column(Integer, nullable=False)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    # RIT tal cual la muestra PJUD ("O-200-2025").
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
    # Celda "Trámites" de la cabecera: en los ejemplos vistos siempre es un icono
    # deshabilitado (cursor:no-drop) sin texto -- se guarda igual tal cual lo entregue
    # PJUD por si en otra causa trae contenido.
    tramites: Mapped[str | None] = mapped_column(String(300), nullable=True)

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
        UniqueConstraint("corte", "tribunal", "tipo", "rol", "anio", name="uq_causas_laboral_clave_natural"),
        CheckConstraint(f"estado_sync IN {ESTADOS_SYNC}", name="ck_causas_laboral_estado_sync"),
    )


class DocumentoLaboral(Base):
    """Registro idempotente de un archivo descargado de una causa Laboral. Espejo de
    `DocumentoFamilia` (sin cuaderno_id: Laboral es cuaderno unico)."""

    __tablename__ = "documentos_laboral"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    causa_laboral_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_laboral.id", ondelete="CASCADE"), nullable=False, index=True
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
        UniqueConstraint("causa_laboral_id", "clave_logica", name="uq_documentos_laboral_causa_clave"),
    )


class TextoDemandaLaboral(Base):
    """Filas del popup "Texto Demanda" (`modalTextoDemandaLaboral`) de la cabecera: tabla
    Doc. Demanda / Doc. / Fecha / Referencia. `doc_demanda` = 0/1 segun el icono de la
    primera columna (fa-minus/fa-check -- ver Solicitud Laboral.md)."""

    __tablename__ = "textos_demanda_laboral"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_laboral_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_laboral.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_laboral.id"), nullable=True)
    doc_demanda: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "causa_laboral_id", "referencia", "fecha", name="uq_textos_demanda_laboral_ref_fecha"
        ),
    )


class AudioLaboral(Base):
    """Filas del popup "Listado de Archivos de Audios de Audiencia"
    (`modalListadoAudioLaboral`) de la cabecera. CONFIRMADO en vivo (2026-09-18, causa
    O-692-2019): la celda que el header del popup muestra no trae "Fecha" como fecha
    corta -- ahi viene el nombre de archivo del audio (largo, p. ej.
    "1940222756-K-1352 -220317-00-01 - INDIVIDUALIZACIÓN (O-692-2019)(S2).mp3"), asi que
    `fecha` se ensancho a 300 y el worker (`worker/sync_laboral.py`) ahora detecta el
    nombre de archivo/fecha por heuristica de contenido en vez de por nombre de columna
    asumido."""

    __tablename__ = "audios_laboral"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_laboral_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_laboral.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_laboral.id"), nullable=True)
    numero: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fecha: Mapped[str | None] = mapped_column(String(300), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("causa_laboral_id", "orden", name="uq_audios_laboral_causa_orden"),
    )


class MovimientoLaboral(Base):
    """Pestana "Movimientos" (hace de Historia). Misma forma que `MovimientoHistoriaFamilia`
    (folio/etapa/estado/tramite/descripcion_tramite/fecha_tramite + Georref.)."""

    __tablename__ = "movimientos_laboral"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_laboral_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_laboral.id", ondelete="CASCADE"), nullable=False, index=True
    )
    folio_texto: Mapped[str] = mapped_column(String(12), nullable=False)
    folio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    etapa: Mapped[str | None] = mapped_column(String(300), nullable=True)
    estado: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tramite: Mapped[str | None] = mapped_column(String(300), nullable=True)
    descripcion_tramite: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    fecha_tramite: Mapped[str | None] = mapped_column(String(60), nullable=True)
    hash_contenido: Mapped[str] = mapped_column(String(64), nullable=False)
    ocurrencia: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Popup "Georref." (pestana Mapas): un solo punto por movimiento.
    geo_latitud: Mapped[str | None] = mapped_column(String(30), nullable=True)
    geo_longitud: Mapped[str | None] = mapped_column(String(30), nullable=True)
    geo_corrector: Mapped[str | None] = mapped_column(String(30), nullable=True)

    docs: Mapped[list["MovimientoLaboralDoc"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan", order_by="MovimientoLaboralDoc.orden"
    )
    anexos: Mapped[list["MovimientoLaboralAnexo"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan", order_by="MovimientoLaboralAnexo.orden"
    )
    geo_imagenes: Mapped[list["MovimientoLaboralGeoImagen"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan", order_by="MovimientoLaboralGeoImagen.orden"
    )

    __table_args__ = (
        Index(
            "uq_movimientos_laboral_causa_folio",
            "causa_laboral_id",
            "folio",
            "ocurrencia",
            unique=True,
            postgresql_where=text("folio_texto NOT LIKE '[%'"),
        ),
    )


class MovimientoLaboralDoc(Base):
    __tablename__ = "movimientos_laboral_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("movimientos_laboral.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_laboral.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)

    movimiento: Mapped["MovimientoLaboral"] = relationship(back_populates="docs")

    __table_args__ = (
        UniqueConstraint("movimiento_id", "orden", name="uq_movimientos_laboral_doc_mov_orden"),
    )


class MovimientoLaboralAnexo(Base):
    """Anexos del folio: carpeta-popup `modalAnexoEscritoLaboral` ("Anexo escrito")."""

    __tablename__ = "movimientos_laboral_anexos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("movimientos_laboral.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_laboral.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)

    movimiento: Mapped["MovimientoLaboral"] = relationship(back_populates="anexos")

    __table_args__ = (
        UniqueConstraint("movimiento_id", "orden", name="uq_movimientos_laboral_anexo_mov_orden"),
    )


class MovimientoLaboralGeoImagen(Base):
    __tablename__ = "movimientos_laboral_geo_imagenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("movimientos_laboral.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_laboral.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)

    movimiento: Mapped["MovimientoLaboral"] = relationship(back_populates="geo_imagenes")

    __table_args__ = (
        UniqueConstraint("movimiento_id", "orden", name="uq_movimientos_laboral_geo_img_mov_orden"),
    )


class LitiganteLaboral(Base):
    """A diferencia de Familia, Laboral trae columnas "Est." (icono 0/1) y "Abog.
    Defensor" (Si/No) ademas de Sujeto/Rut/Persona/Nombre o Razon Social."""

    __tablename__ = "litigantes_laboral"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_laboral_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_laboral.id", ondelete="CASCADE"), nullable=False, index=True
    )
    estado: Mapped[int | None] = mapped_column(Integer, nullable=True)
    defensor: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sujeto: Mapped[str | None] = mapped_column(String(60), nullable=True)
    rut: Mapped[str | None] = mapped_column(String(15), nullable=True)
    persona: Mapped[str | None] = mapped_column(String(10), nullable=True)
    razon_social: Mapped[str | None] = mapped_column(String(500), nullable=True)


class MateriaLaboral(Base):
    __tablename__ = "materias_laboral"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_laboral_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_laboral.id", ondelete="CASCADE"), nullable=False, index=True
    )
    codigo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    glosa_materia: Mapped[str | None] = mapped_column(String(500), nullable=True)
    estado: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_termino: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("causa_laboral_id", "contenido_hash", name="uq_materias_laboral_causa_hash"),
    )


class NotificacionLaboral(Base):
    __tablename__ = "notificaciones_laboral"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_laboral_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_laboral.id", ondelete="CASCADE"), nullable=False, index=True
    )
    estado_notificacion: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_tramite: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tipo_parte: Mapped[str | None] = mapped_column(String(60), nullable=True)
    nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tramite: Mapped[str | None] = mapped_column(String(300), nullable=True)
    observacion_fallida: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("causa_laboral_id", "contenido_hash", name="uq_notificaciones_laboral_causa_hash"),
    )


class DiligenciaLaboral(Base):
    """A diferencia de Familia: dos documentos por fila (Doc. Ida / Doc. Vta., no
    Solicitud/Respuesta) y columnas propias RIT/RUC/Referencia."""

    __tablename__ = "diligencias_laboral"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_laboral_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_laboral.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_ida_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_laboral.id"), nullable=True)
    doc_vta_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_laboral.id"), nullable=True)
    estado_diligencia: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ruc: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tipo_diligencia: Mapped[str | None] = mapped_column(String(200), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fecha_tramite: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("causa_laboral_id", "contenido_hash", name="uq_diligencias_laboral_causa_hash"),
    )


class LiquidacionLaboral(Base):
    """Pestana "Liquidación": Liquidación/Rut/Nombre/Monto Líquido. La primera columna
    no se vio con datos en los ejemplos disponibles (ejemplos/causa cobranza/liquidacion.html
    trae la tabla vacia) -- se guarda como texto plano hasta confirmar si es un icono de
    estado o un documento descargable."""

    __tablename__ = "liquidaciones_laboral"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_laboral_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_laboral.id", ondelete="CASCADE"), nullable=False, index=True
    )
    liquidacion: Mapped[str | None] = mapped_column(String(300), nullable=True)
    rut: Mapped[str | None] = mapped_column(String(15), nullable=True)
    nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)
    monto_liquido: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("causa_laboral_id", "contenido_hash", name="uq_liquidaciones_laboral_causa_hash"),
    )


class EscritoPendienteLaboral(Base):
    """Pestana "Escritos Pendientes": listado transiente (PJUD saca la fila una vez
    resuelta, igual que "Escritos por Resolver" de Civil) -- se sincroniza con
    delete-si-desaparecio, no reemplazo completo. `anexo_id` es un solo documento
    (columna "Anexo" del contrato es un string, no una lista) aunque el popup
    `modalAnexoEscritoPend` pueda traer varias filas: se guarda solo la primera."""

    __tablename__ = "escritos_pendientes_laboral"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    causa_laboral_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("causas_laboral.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_laboral.id"), nullable=True)
    anexo_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos_laboral.id"), nullable=True)
    fecha_ing: Mapped[str | None] = mapped_column(String(60), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)
    solicitante: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tipo_ingreso: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "causa_laboral_id", "contenido_hash", name="uq_escritos_pendientes_laboral_causa_hash"
        ),
    )
