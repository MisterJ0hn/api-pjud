"""competencia corte de apelaciones: tablas propias + sync_job.causa_apelaciones_id

Revision ID: ed1178454556
Revises: d428f11eb9a8
Create Date: 2026-10-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "ed1178454556"
down_revision: Union[str, None] = "d428f11eb9a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CK_UNA_CAUSA_ANTES = (
    "(CASE WHEN causa_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN causa_familia_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN causa_laboral_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN causa_cobranza_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN causa_penal_id IS NOT NULL THEN 1 ELSE 0 END) = 1"
)
CK_UNA_CAUSA = CK_UNA_CAUSA_ANTES[: -len(" = 1")] + " + (CASE WHEN causa_apelaciones_id IS NOT NULL THEN 1 ELSE 0 END) = 1"

FK_CAUSA = "causas_apelaciones.id"


def _causa_col() -> sa.Column:
    return sa.Column("causa_apelaciones_id", sa.UUID(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "causas_apelaciones",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("corte", sa.Integer(), nullable=False),
        sa.Column("libro", sa.String(length=80), nullable=False),
        sa.Column("rol", sa.Integer(), nullable=False),
        sa.Column("anio", sa.Integer(), nullable=False),
        sa.Column("libro_texto", sa.String(length=120), nullable=True),
        sa.Column("fecha", sa.String(length=20), nullable=True),
        sa.Column("estado_recurso", sa.String(length=100), nullable=True),
        sa.Column("estado_procesal", sa.String(length=200), nullable=True),
        sa.Column("ubicacion", sa.String(length=200), nullable=True),
        sa.Column("recurso", sa.String(length=300), nullable=True),
        sa.Column("corte_nombre", sa.String(length=120), nullable=True),
        sa.Column("certificado_envio_color", sa.String(length=32), nullable=True),
        sa.Column("ebook_color", sa.String(length=32), nullable=True),
        sa.Column("origen_rol", sa.String(length=60), nullable=True),
        sa.Column("origen_tribunal", sa.String(length=200), nullable=True),
        sa.Column("origen_caratulado", sa.String(length=500), nullable=True),
        sa.Column("origen_materia", sa.String(length=300), nullable=True),
        sa.Column("origen_ruc", sa.String(length=60), nullable=True),
        sa.Column("origen_fecha_ingreso", sa.String(length=20), nullable=True),
        sa.Column("causa_origen_competencia", sa.String(length=20), nullable=True),
        sa.Column("causa_origen_id", sa.UUID(), nullable=True),
        sa.Column("visibilidad", sa.String(length=10), nullable=True),
        sa.Column("estado_sync", sa.String(length=15), nullable=False),
        sa.Column("sync_detalle", sa.String(length=300), nullable=True),
        sa.Column("sync_iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_ultima_sincronizacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_error", sa.String(length=2000), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "estado_sync IN ('Pendiente', 'Sincronizando', 'Completo', 'Error')",
            name="ck_causas_apelaciones_estado_sync",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("corte", "libro", "rol", "anio", name="uq_causas_apelaciones_clave_natural"),
    )
    op.create_index(op.f("ix_causas_apelaciones_causa_origen_id"), "causas_apelaciones", ["causa_origen_id"])

    op.create_table(
        "documentos_apelaciones",
        sa.Column("id", sa.UUID(), nullable=False),
        _causa_col(),
        sa.Column("categoria", sa.String(length=40), nullable=False),
        sa.Column("clave_logica", sa.String(length=160), nullable=False),
        sa.Column("nombre_archivo", sa.String(length=160), nullable=False),
        sa.Column("ruta_archivo", sa.String(length=1000), nullable=False),
        sa.Column("hash_contenido_fila_padre", sa.String(length=64), nullable=True),
        sa.Column("referencia_origen", sa.String(length=300), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["causa_apelaciones_id"], [FK_CAUSA], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_apelaciones_id", "clave_logica", name="uq_documentos_apelaciones_causa_clave"),
    )
    op.create_index(
        op.f("ix_documentos_apelaciones_causa_apelaciones_id"), "documentos_apelaciones", ["causa_apelaciones_id"]
    )

    op.create_table(
        "movimientos_apelaciones",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _causa_col(),
        sa.Column("folio", sa.Integer(), nullable=False),
        sa.Column("ocurrencia", sa.Integer(), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("tramite", sa.String(length=300), nullable=True),
        sa.Column("descripcion", sa.String(length=1000), nullable=True),
        sa.Column("fecha", sa.String(length=60), nullable=True),
        sa.Column("sala", sa.String(length=100), nullable=True),
        sa.Column("estado", sa.String(length=100), nullable=True),
        sa.Column("geo_latitud", sa.String(length=30), nullable=True),
        sa.Column("geo_longitud", sa.String(length=30), nullable=True),
        sa.Column("geo_corrector", sa.String(length=30), nullable=True),
        sa.Column("hash_contenido", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["causa_apelaciones_id"], [FK_CAUSA], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_movimientos_apelaciones_causa_apelaciones_id"), "movimientos_apelaciones", ["causa_apelaciones_id"]
    )
    op.create_index(
        "uq_movimientos_apelaciones_causa_folio",
        "movimientos_apelaciones",
        ["causa_apelaciones_id", "folio", "ocurrencia"],
        unique=True,
    )

    for tabla, extra, uq in (
        ("movimientos_apelaciones_docs", [], "uq_mov_apelaciones_doc_orden"),
        (
            "movimientos_apelaciones_anexos",
            [sa.Column("fecha", sa.String(length=60), nullable=True), sa.Column("referencia", sa.String(length=300), nullable=True)],
            "uq_mov_apelaciones_anexo_orden",
        ),
        ("movimientos_apelaciones_geo_imagenes", [], "uq_mov_apelaciones_geo_img_orden"),
    ):
        cols = [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("movimiento_id", sa.Integer(), nullable=False),
            sa.Column("documento_id", sa.UUID(), nullable=True),
            sa.Column("orden", sa.Integer(), nullable=False),
        ]
        if tabla != "movimientos_apelaciones_geo_imagenes":
            cols.append(sa.Column("color", sa.String(length=32), nullable=True))
        op.create_table(
            tabla,
            *cols,
            *extra,
            sa.ForeignKeyConstraint(["movimiento_id"], ["movimientos_apelaciones.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["documento_id"], ["documentos_apelaciones.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("movimiento_id", "orden", name=uq),
        )
        op.create_index(op.f(f"ix_{tabla}_movimiento_id"), tabla, ["movimiento_id"])

    op.create_table(
        "litigantes_apelaciones",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _causa_col(),
        sa.Column("sujeto", sa.String(length=100), nullable=True),
        sa.Column("rut", sa.String(length=20), nullable=True),
        sa.Column("persona", sa.String(length=10), nullable=True),
        sa.Column("razon_social", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["causa_apelaciones_id"], [FK_CAUSA], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_litigantes_apelaciones_causa_apelaciones_id"), "litigantes_apelaciones", ["causa_apelaciones_id"]
    )

    op.create_table(
        "textos_apelaciones",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _causa_col(),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("doc_principal_icono", sa.String(length=40), nullable=True),
        sa.Column("doc_principal_color", sa.String(length=32), nullable=True),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("fecha", sa.String(length=60), nullable=True),
        sa.Column("referencia", sa.String(length=300), nullable=True),
        sa.Column("contenido_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["causa_apelaciones_id"], [FK_CAUSA], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_apelaciones.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_apelaciones_id", "orden", name="uq_textos_apelaciones_orden"),
    )
    op.create_index(op.f("ix_textos_apelaciones_causa_apelaciones_id"), "textos_apelaciones", ["causa_apelaciones_id"])

    op.create_table(
        "anexos_causa_apelaciones",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _causa_col(),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("codigo", sa.String(length=20), nullable=True),
        sa.Column("tipo_documento", sa.String(length=300), nullable=True),
        sa.Column("cantidad", sa.String(length=20), nullable=True),
        sa.Column("observacion_documento", sa.String(length=1000), nullable=True),
        sa.Column("contenido_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["causa_apelaciones_id"], [FK_CAUSA], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_apelaciones.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_apelaciones_id", "orden", name="uq_anexos_causa_apelaciones_orden"),
    )
    op.create_index(
        op.f("ix_anexos_causa_apelaciones_causa_apelaciones_id"), "anexos_causa_apelaciones", ["causa_apelaciones_id"]
    )

    op.create_table(
        "registros_apelaciones",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _causa_col(),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("datos", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["causa_apelaciones_id"], [FK_CAUSA], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_apelaciones_id", "tipo", "orden", name="uq_registros_apelaciones_orden"),
    )
    op.create_index(
        op.f("ix_registros_apelaciones_causa_apelaciones_id"), "registros_apelaciones", ["causa_apelaciones_id"]
    )

    op.create_table(
        "usuario_apelaciones_permitido",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_id", sa.UUID(), nullable=False),
        sa.Column("rut", sa.String(length=12), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["causa_id"], [FK_CAUSA], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_id", "rut", name="uq_usuario_apelaciones_permitido"),
    )
    op.create_index("ix_usuario_apelaciones_permitido_causa_id", "usuario_apelaciones_permitido", ["causa_id"])

    # sync_job: una columna mas en el XOR de causas.
    op.add_column("sync_job", sa.Column("causa_apelaciones_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_sync_job_causa_apelaciones_id", "sync_job", "causas_apelaciones", ["causa_apelaciones_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_sync_job_causa_apelaciones_id"), "sync_job", ["causa_apelaciones_id"])
    op.drop_constraint("ck_sync_job_una_causa", "sync_job", type_="check")
    op.create_check_constraint("ck_sync_job_una_causa", "sync_job", CK_UNA_CAUSA)


def downgrade() -> None:
    op.execute("DELETE FROM sync_job WHERE causa_apelaciones_id IS NOT NULL")
    op.drop_constraint("ck_sync_job_una_causa", "sync_job", type_="check")
    op.create_check_constraint("ck_sync_job_una_causa", "sync_job", CK_UNA_CAUSA_ANTES)
    op.drop_index(op.f("ix_sync_job_causa_apelaciones_id"), table_name="sync_job")
    op.drop_constraint("fk_sync_job_causa_apelaciones_id", "sync_job", type_="foreignkey")
    op.drop_column("sync_job", "causa_apelaciones_id")

    op.drop_table("usuario_apelaciones_permitido")
    op.drop_table("registros_apelaciones")
    op.drop_table("anexos_causa_apelaciones")
    op.drop_table("textos_apelaciones")
    op.drop_table("litigantes_apelaciones")
    op.drop_table("movimientos_apelaciones_geo_imagenes")
    op.drop_table("movimientos_apelaciones_anexos")
    op.drop_table("movimientos_apelaciones_docs")
    op.drop_table("movimientos_apelaciones")
    op.drop_table("documentos_apelaciones")
    op.drop_table("causas_apelaciones")
