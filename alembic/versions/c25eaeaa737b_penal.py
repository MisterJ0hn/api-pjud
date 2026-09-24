"""competencia penal: tablas propias + sync_job.causa_penal_id

Revision ID: c25eaeaa737b
Revises: 8b4d102efd0c
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c25eaeaa737b"
down_revision: Union[str, None] = "8b4d102efd0c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CK_UNA_CAUSA = (
    "(CASE WHEN causa_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN causa_familia_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN causa_laboral_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN causa_cobranza_id IS NOT NULL THEN 1 ELSE 0 END)"
)


def upgrade() -> None:
    op.create_table(
        "causas_penal",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("corte", sa.Integer(), nullable=False),
        sa.Column("tribunal", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("rol", sa.Integer(), nullable=False),
        sa.Column("anio", sa.Integer(), nullable=False),
        sa.Column("rit", sa.String(length=40), nullable=False),
        sa.Column("caratula", sa.String(length=500), nullable=True),
        sa.Column("fecha_ingreso", sa.String(length=20), nullable=True),
        sa.Column("ruc", sa.String(length=60), nullable=True),
        sa.Column("estado_adm", sa.String(length=200), nullable=True),
        sa.Column("procedimiento", sa.String(length=200), nullable=True),
        sa.Column("proceso", sa.String(length=300), nullable=True),
        sa.Column("forma_inicio", sa.String(length=200), nullable=True),
        sa.Column("estado_proceso", sa.String(length=200), nullable=True),
        sa.Column("etapa", sa.String(length=300), nullable=True),
        sa.Column("tribunal_nombre", sa.String(length=200), nullable=True),
        sa.Column("estado_sync", sa.String(length=15), nullable=False),
        sa.Column("sync_detalle", sa.String(length=300), nullable=True),
        sa.Column("sync_iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_ultima_sincronizacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_error", sa.String(length=2000), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "estado_sync IN ('Pendiente', 'Sincronizando', 'Completo', 'Error')",
            name="ck_causas_penal_estado_sync",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("corte", "tribunal", "tipo", "rol", "anio", name="uq_causas_penal_clave_natural"),
    )

    op.create_table(
        "documentos_penal",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("causa_penal_id", sa.UUID(), nullable=False),
        sa.Column("categoria", sa.String(length=40), nullable=False),
        sa.Column("clave_logica", sa.String(length=160), nullable=False),
        sa.Column("nombre_archivo", sa.String(length=160), nullable=False),
        sa.Column("ruta_archivo", sa.String(length=1000), nullable=False),
        sa.Column("hash_contenido_fila_padre", sa.String(length=64), nullable=True),
        sa.Column("referencia_origen", sa.String(length=300), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["causa_penal_id"], ["causas_penal.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_penal_id", "clave_logica", name="uq_documentos_penal_causa_clave"),
    )
    op.create_index(op.f("ix_documentos_penal_causa_penal_id"), "documentos_penal", ["causa_penal_id"])

    op.create_table(
        "cuadernos_penal",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_penal_id", sa.UUID(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=300), nullable=False),
        sa.Column("estado_proceso", sa.String(length=200), nullable=True),
        sa.Column("etapa", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(["causa_penal_id"], ["causas_penal.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_penal_id", "numero", name="uq_cuadernos_penal_causa_numero"),
    )
    op.create_index(op.f("ix_cuadernos_penal_causa_penal_id"), "cuadernos_penal", ["causa_penal_id"])

    op.create_table(
        "historia_penal",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_penal_id", sa.UUID(), nullable=False),
        sa.Column("cuaderno_numero", sa.Integer(), nullable=True),
        sa.Column("folio_texto", sa.String(length=12), nullable=False),
        sa.Column("folio", sa.Integer(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("etapa", sa.String(length=300), nullable=True),
        sa.Column("tramite", sa.String(length=300), nullable=True),
        sa.Column("descripcion_tramite", sa.String(length=1000), nullable=True),
        sa.Column("descripcion_tramite_doc_id", sa.UUID(), nullable=True),
        sa.Column("descripcion_tramite_doc_color", sa.String(length=32), nullable=True),
        sa.Column("estado_firma", sa.String(length=60), nullable=True),
        sa.Column("estado", sa.String(length=100), nullable=True),
        sa.Column("fecha_tramite", sa.String(length=60), nullable=True),
        sa.Column("hash_contenido", sa.String(length=64), nullable=False),
        sa.Column("ocurrencia", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["causa_penal_id"], ["causas_penal.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["descripcion_tramite_doc_id"], ["documentos_penal.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_historia_penal_causa_penal_id"), "historia_penal", ["causa_penal_id"])
    op.create_index(
        "uq_historia_penal_causa_folio",
        "historia_penal",
        ["causa_penal_id", "cuaderno_numero", "folio", "ocurrencia"],
        unique=True,
        postgresql_where=sa.text("folio_texto NOT LIKE '[%'"),
    )

    op.create_table(
        "historia_penal_docs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movimiento_id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["movimiento_id"], ["historia_penal.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_penal.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movimiento_id", "orden", name="uq_historia_penal_doc_mov_orden"),
    )
    op.create_index(op.f("ix_historia_penal_docs_movimiento_id"), "historia_penal_docs", ["movimiento_id"])

    op.create_table(
        "historia_penal_anexos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movimiento_id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("fecha", sa.String(length=60), nullable=True),
        sa.Column("referencia", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(["movimiento_id"], ["historia_penal.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_penal.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movimiento_id", "orden", name="uq_historia_penal_anexo_mov_orden"),
    )
    op.create_index(op.f("ix_historia_penal_anexos_movimiento_id"), "historia_penal_anexos", ["movimiento_id"])

    op.create_table(
        "litigantes_penal",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_penal_id", sa.UUID(), nullable=False),
        sa.Column("participantes", sa.String(length=100), nullable=True),
        sa.Column("rut", sa.String(length=15), nullable=True),
        sa.Column("persona", sa.String(length=10), nullable=True),
        sa.Column("razon_social", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["causa_penal_id"], ["causas_penal.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_litigantes_penal_causa_penal_id"), "litigantes_penal", ["causa_penal_id"])

    op.create_table(
        "notificaciones_penal",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_penal_id", sa.UUID(), nullable=False),
        sa.Column("tipo_notificacion", sa.String(length=60), nullable=True),
        sa.Column("estado_notificacion", sa.String(length=60), nullable=True),
        sa.Column("fecha_notificacion", sa.String(length=60), nullable=True),
        sa.Column("nombre", sa.String(length=300), nullable=True),
        sa.Column("estampado", sa.String(length=300), nullable=True),
        sa.Column("geo_latitud", sa.String(length=30), nullable=True),
        sa.Column("geo_longitud", sa.String(length=30), nullable=True),
        sa.Column("geo_corrector", sa.String(length=30), nullable=True),
        sa.Column("contenido_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["causa_penal_id"], ["causas_penal.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_penal_id", "contenido_hash", name="uq_notificaciones_penal_causa_hash"),
    )
    op.create_index(op.f("ix_notificaciones_penal_causa_penal_id"), "notificaciones_penal", ["causa_penal_id"])

    op.create_table(
        "notificaciones_penal_geo_imagenes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("notificacion_id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["notificacion_id"], ["notificaciones_penal.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_penal.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notificacion_id", "orden", name="uq_notif_penal_geo_img_orden"),
    )
    op.create_index(
        op.f("ix_notificaciones_penal_geo_imagenes_notificacion_id"),
        "notificaciones_penal_geo_imagenes",
        ["notificacion_id"],
    )

    op.create_table(
        "relaciones_penal",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_penal_id", sa.UUID(), nullable=False),
        sa.Column("nombre", sa.String(length=300), nullable=True),
        sa.Column("materia", sa.String(length=500), nullable=True),
        sa.Column("estado_causa", sa.String(length=100), nullable=True),
        sa.Column("fecha_cambio_estado", sa.String(length=60), nullable=True),
        sa.Column("contenido_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["causa_penal_id"], ["causas_penal.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_penal_id", "contenido_hash", name="uq_relaciones_penal_causa_hash"),
    )
    op.create_index(op.f("ix_relaciones_penal_causa_penal_id"), "relaciones_penal", ["causa_penal_id"])

    op.add_column("sync_job", sa.Column("causa_penal_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_sync_job_causa_penal_id"), "sync_job", ["causa_penal_id"])
    op.create_foreign_key(
        "fk_sync_job_causa_penal_id", "sync_job", "causas_penal", ["causa_penal_id"], ["id"], ondelete="CASCADE"
    )
    op.drop_constraint("ck_sync_job_una_causa", "sync_job", type_="check")
    op.create_check_constraint(
        "ck_sync_job_una_causa",
        "sync_job",
        CK_UNA_CAUSA + " + (CASE WHEN causa_penal_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sync_job_una_causa", "sync_job", type_="check")
    op.create_check_constraint("ck_sync_job_una_causa", "sync_job", CK_UNA_CAUSA + " = 1")
    op.drop_constraint("fk_sync_job_causa_penal_id", "sync_job", type_="foreignkey")
    op.drop_index(op.f("ix_sync_job_causa_penal_id"), table_name="sync_job")
    op.drop_column("sync_job", "causa_penal_id")

    for tabla in (
        "relaciones_penal",
        "notificaciones_penal_geo_imagenes",
        "notificaciones_penal",
        "litigantes_penal",
        "historia_penal_anexos",
        "historia_penal_docs",
        "historia_penal",
        "cuadernos_penal",
        "documentos_penal",
        "causas_penal",
    ):
        op.drop_table(tabla)
