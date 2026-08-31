from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base


class MovimientoHistoria(Base):
    __tablename__ = "movimientos_historia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cuaderno_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cuadernos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Folio tal cual lo muestra PJUD: normalmente un entero ("33"), pero los movimientos
    # de un exhorto vienen numerados aparte y entre corchetes ("[6E]", "[2E]"),
    # intercalados por fecha en la misma tabla Historia. Un mismo "[NE]" puede repetirse
    # cuando la causa tiene mas de un exhorto (cada uno reinicia su numeracion).
    folio_texto: Mapped[str] = mapped_column(String(12), nullable=False)
    # Parte numerica del folio (33, o 6 para "[6E]"); solo para ordenar. Nullable por si
    # aparece un formato de folio que no sepamos parsear.
    folio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    etapa: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tramite: Mapped[str | None] = mapped_column(String(300), nullable=True)
    descripcion_tramite: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    fecha_tramite: Mapped[str | None] = mapped_column(String(60), nullable=True)
    foja: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hash_contenido: Mapped[str] = mapped_column(String(64), nullable=False)

    anexos: Mapped[list["MovimientoHistoriaAnexo"]] = relationship(
        back_populates="movimiento", cascade="all, delete-orphan"
    )
    docs: Mapped[list["MovimientoHistoriaDoc"]] = relationship(
        back_populates="movimiento",
        cascade="all, delete-orphan",
        order_by="MovimientoHistoriaDoc.orden",
    )

    __table_args__ = (
        # Folios normales: siguen teniendo clave natural (cuaderno, folio) -> una fila por
        # folio, se hace UPDATE cuando cambia el contenido. Indice parcial: excluye los
        # "[NE]" de exhorto (que si pueden repetirse dentro del cuaderno).
        Index(
            "uq_historia_cuaderno_folio",
            "cuaderno_id",
            "folio",
            unique=True,
            postgresql_where=text("folio_texto NOT LIKE '[%'"),
        ),
        # Filas de exhorto ("[NE]"): sin clave estable en el HTML (un mismo "[6E]" puede
        # venir de dos exhortos distintos), asi que se identifican por contenido -- append
        # -only, igual que escritos_resolver / notificaciones.
        UniqueConstraint(
            "cuaderno_id",
            "folio_texto",
            "hash_contenido",
            name="uq_historia_cuaderno_foliotexto_hash",
        ),
    )


class MovimientoHistoriaDoc(Base):
    __tablename__ = "movimientos_historia_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("movimientos_historia.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)

    movimiento: Mapped["MovimientoHistoria"] = relationship(back_populates="docs")

    __table_args__ = (UniqueConstraint("movimiento_id", "orden", name="uq_historia_doc_movimiento_orden"),)


class MovimientoHistoriaAnexo(Base):
    __tablename__ = "movimientos_historia_anexos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movimiento_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("movimientos_historia.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)

    movimiento: Mapped["MovimientoHistoria"] = relationship(back_populates="anexos")

    __table_args__ = (UniqueConstraint("movimiento_id", "orden", name="uq_historia_anexo_movimiento_orden"),)


class Litigante(Base):
    __tablename__ = "litigantes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cuaderno_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cuadernos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participante: Mapped[str | None] = mapped_column(String(60), nullable=True)
    rut: Mapped[str | None] = mapped_column(String(15), nullable=True)
    persona: Mapped[str | None] = mapped_column(String(10), nullable=True)
    razon_social: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (UniqueConstraint("cuaderno_id", "participante", "rut", name="uq_litigantes_cuaderno_part_rut"),)


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cuaderno_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cuadernos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rol: Mapped[str | None] = mapped_column(String(30), nullable=True)
    estado_notificacion: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tipo_notificacion: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_tramite: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tipo_part: Mapped[str | None] = mapped_column(String(60), nullable=True)
    nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tramite: Mapped[str | None] = mapped_column(String(300), nullable=True)
    observacion_fallida: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (UniqueConstraint("cuaderno_id", "contenido_hash", name="uq_notificaciones_cuaderno_hash"),)


class EscritoResolver(Base):
    __tablename__ = "escritos_resolver"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cuaderno_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cuadernos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos.id"), nullable=True)
    fecha_ingreso: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tipo_escrito: Mapped[str | None] = mapped_column(String(300), nullable=True)
    solicitante: Mapped[str | None] = mapped_column(String(300), nullable=True)
    contenido_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (UniqueConstraint("cuaderno_id", "contenido_hash", name="uq_escritos_cuaderno_hash"),)


class Exhorto(Base):
    __tablename__ = "exhortos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cuaderno_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cuadernos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rol_origen: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tipo_exhorto: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_ordena_exhorto: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_ingreso_exhorto: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tribunal_destino: Mapped[str | None] = mapped_column(String(300), nullable=True)
    estado_exhorto: Mapped[str | None] = mapped_column(String(60), nullable=True)

    roles_destino: Mapped[list["ExhortoRolDestino"]] = relationship(
        back_populates="exhorto", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("cuaderno_id", "rol_origen", "tipo_exhorto", name="uq_exhortos_cuaderno_rol_tipo"),
    )


class ExhortoRolDestino(Base):
    __tablename__ = "exhortos_rol_destino"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exhorto_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("exhortos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nombre: Mapped[str] = mapped_column(String(30), nullable=False)

    exhorto: Mapped["Exhorto"] = relationship(back_populates="roles_destino")
    items: Mapped[list["ExhortoRolDestinoItem"]] = relationship(
        back_populates="rol_destino", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("exhorto_id", "nombre", name="uq_exhorto_rol_destino_nombre"),)


class ExhortoRolDestinoItem(Base):
    __tablename__ = "exhortos_rol_destino_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rol_destino_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("exhortos_rol_destino.id", ondelete="CASCADE"), nullable=False, index=True
    )
    documento_id = mapped_column(UUID(as_uuid=True), ForeignKey("documentos.id"), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha: Mapped[str | None] = mapped_column(String(60), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tramite: Mapped[str | None] = mapped_column(String(300), nullable=True)

    rol_destino: Mapped["ExhortoRolDestino"] = relationship(back_populates="items")

    __table_args__ = (UniqueConstraint("rol_destino_id", "orden", name="uq_exhorto_item_rol_destino_orden"),)
