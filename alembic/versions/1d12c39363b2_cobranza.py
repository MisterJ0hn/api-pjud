"""competencia cobranza: tablas propias + sync_job.causa_cobranza_id

Revision ID: 1d12c39363b2
Revises: f3b6d8a1c4e7
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1d12c39363b2"
down_revision: Union[str, None] = "f3b6d8a1c4e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "causas_cobranza",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("corte", sa.Integer(), nullable=False),
        sa.Column("tribunal", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=4), nullable=False),
        sa.Column("rol", sa.Integer(), nullable=False),
        sa.Column("anio", sa.Integer(), nullable=False),
        sa.Column("rit", sa.String(length=40), nullable=False),
        sa.Column("caratula", sa.String(length=500), nullable=True),
        sa.Column("fecha_ingreso", sa.String(length=20), nullable=True),
        sa.Column("ruc", sa.String(length=60), nullable=True),
        sa.Column("proceso", sa.String(length=300), nullable=True),
        sa.Column("forma_inicio", sa.String(length=200), nullable=True),
        sa.Column("est_adm", sa.String(length=200), nullable=True),
        sa.Column("estado_proceso", sa.String(length=200), nullable=True),
        sa.Column("etapa", sa.String(length=300), nullable=True),
        sa.Column("juez_asignado", sa.String(length=300), nullable=True),
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
            name="ck_causas_cobranza_estado_sync",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("corte", "tribunal", "tipo", "rol", "anio", name="uq_causas_cobranza_clave_natural"),
    )

    op.create_table(
        "documentos_cobranza",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("causa_cobranza_id", sa.UUID(), nullable=False),
        sa.Column("categoria", sa.String(length=40), nullable=False),
        sa.Column("clave_logica", sa.String(length=160), nullable=False),
        sa.Column("nombre_archivo", sa.String(length=160), nullable=False),
        sa.Column("ruta_archivo", sa.String(length=1000), nullable=False),
        sa.Column("hash_contenido_fila_padre", sa.String(length=64), nullable=True),
        sa.Column("referencia_origen", sa.String(length=300), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["causa_cobranza_id"], ["causas_cobranza.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_cobranza_id", "clave_logica", name="uq_documentos_cobranza_causa_clave"),
    )
    op.create_index(
        op.f("ix_documentos_cobranza_causa_cobranza_id"), "documentos_cobranza", ["causa_cobranza_id"], unique=False
    )

    op.create_table(
        "cuadernos_cobranza",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_cobranza_id", sa.UUID(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=300), nullable=False),
        sa.Column("estado_proceso", sa.String(length=200), nullable=True),
        sa.Column("etapa", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(["causa_cobranza_id"], ["causas_cobranza.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_cobranza_id", "numero", name="uq_cuadernos_cobranza_causa_numero"),
    )
    op.create_index(
        op.f("ix_cuadernos_cobranza_causa_cobranza_id"), "cuadernos_cobranza", ["causa_cobranza_id"], unique=False
    )

    op.create_table(
        "anexos_causa_cobranza",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_cobranza_id", sa.UUID(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("fecha", sa.String(length=60), nullable=True),
        sa.Column("referencia", sa.String(length=300), nullable=True),
        sa.Column("target", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["causa_cobranza_id"], ["causas_cobranza.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_cobranza.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_cobranza_id", "referencia", "fecha", name="uq_anexos_causa_cobranza_ref_fecha"),
    )
    op.create_index(
        op.f("ix_anexos_causa_cobranza_causa_cobranza_id"), "anexos_causa_cobranza", ["causa_cobranza_id"], unique=False
    )

    op.create_table(
        "informacion_receptor_cobranza",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_cobranza_id", sa.UUID(), nullable=False),
        sa.Column("cuaderno_nombre", sa.String(length=300), nullable=True),
        sa.Column("datos_retiro", sa.String(length=300), nullable=True),
        sa.Column("fecha_retiro", sa.String(length=60), nullable=True),
        sa.Column("estado", sa.String(length=60), nullable=True),
        sa.ForeignKeyConstraint(["causa_cobranza_id"], ["causas_cobranza.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "causa_cobranza_id", "cuaderno_nombre", "fecha_retiro", name="uq_info_receptor_cobranza_causa_cuad_fecha"
        ),
    )
    op.create_index(
        op.f("ix_informacion_receptor_cobranza_causa_cobranza_id"),
        "informacion_receptor_cobranza",
        ["causa_cobranza_id"],
        unique=False,
    )

    op.create_table(
        "historia_cobranza",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_cobranza_id", sa.UUID(), nullable=False),
        sa.Column("cuaderno_numero", sa.Integer(), nullable=True),
        sa.Column("folio_texto", sa.String(length=12), nullable=False),
        sa.Column("folio", sa.Integer(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("etapa", sa.String(length=300), nullable=True),
        sa.Column("tramite", sa.String(length=300), nullable=True),
        sa.Column("descripcion_tramite", sa.String(length=1000), nullable=True),
        sa.Column("descripcion_tramite_doc_id", sa.UUID(), nullable=True),
        sa.Column("estado_firma", sa.String(length=60), nullable=True),
        sa.Column("fecha_tramite", sa.String(length=60), nullable=True),
        sa.Column("hash_contenido", sa.String(length=64), nullable=False),
        sa.Column("ocurrencia", sa.Integer(), nullable=False),
        sa.Column("geo_latitud", sa.String(length=30), nullable=True),
        sa.Column("geo_longitud", sa.String(length=30), nullable=True),
        sa.Column("geo_corrector", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(["causa_cobranza_id"], ["causas_cobranza.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["descripcion_tramite_doc_id"], ["documentos_cobranza.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_historia_cobranza_causa_cobranza_id"), "historia_cobranza", ["causa_cobranza_id"], unique=False
    )
    op.create_index(
        "uq_historia_cobranza_causa_folio",
        "historia_cobranza",
        ["causa_cobranza_id", "cuaderno_numero", "folio", "ocurrencia"],
        unique=True,
        postgresql_where=sa.text("folio_texto NOT LIKE '[%'"),
    )

    op.create_table(
        "historia_cobranza_docs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movimiento_id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_cobranza.id"]),
        sa.ForeignKeyConstraint(["movimiento_id"], ["historia_cobranza.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movimiento_id", "orden", name="uq_historia_cobranza_doc_mov_orden"),
    )
    op.create_index(
        op.f("ix_historia_cobranza_docs_movimiento_id"), "historia_cobranza_docs", ["movimiento_id"], unique=False
    )

    op.create_table(
        "historia_cobranza_anexos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movimiento_id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.String(length=60), nullable=True),
        sa.Column("referencia", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_cobranza.id"]),
        sa.ForeignKeyConstraint(["movimiento_id"], ["historia_cobranza.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movimiento_id", "orden", name="uq_historia_cobranza_anexo_mov_orden"),
    )
    op.create_index(
        op.f("ix_historia_cobranza_anexos_movimiento_id"),
        "historia_cobranza_anexos",
        ["movimiento_id"],
        unique=False,
    )

    op.create_table(
        "historia_cobranza_geo_imagenes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movimiento_id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_cobranza.id"]),
        sa.ForeignKeyConstraint(["movimiento_id"], ["historia_cobranza.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movimiento_id", "orden", name="uq_historia_cobranza_geo_img_mov_orden"),
    )
    op.create_index(
        op.f("ix_historia_cobranza_geo_imagenes_movimiento_id"),
        "historia_cobranza_geo_imagenes",
        ["movimiento_id"],
        unique=False,
    )

    op.create_table(
        "litigantes_cobranza",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_cobranza_id", sa.UUID(), nullable=False),
        sa.Column("sujeto", sa.String(length=60), nullable=True),
        sa.Column("rut", sa.String(length=15), nullable=True),
        sa.Column("persona", sa.String(length=10), nullable=True),
        sa.Column("razon_social", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["causa_cobranza_id"], ["causas_cobranza.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_litigantes_cobranza_causa_cobranza_id"), "litigantes_cobranza", ["causa_cobranza_id"], unique=False
    )

    op.create_table(
        "notificaciones_cobranza",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_cobranza_id", sa.UUID(), nullable=False),
        sa.Column("tipo_notificacion", sa.String(length=60), nullable=True),
        sa.Column("estado_notificacion", sa.String(length=60), nullable=True),
        sa.Column("fecha_notificacion", sa.String(length=60), nullable=True),
        sa.Column("fecha_tramite", sa.String(length=60), nullable=True),
        sa.Column("tramite", sa.String(length=300), nullable=True),
        sa.Column("tipo_part", sa.String(length=60), nullable=True),
        sa.Column("nombre", sa.String(length=300), nullable=True),
        sa.Column("contenido_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["causa_cobranza_id"], ["causas_cobranza.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_cobranza_id", "contenido_hash", name="uq_notificaciones_cobranza_causa_hash"),
    )
    op.create_index(
        op.f("ix_notificaciones_cobranza_causa_cobranza_id"),
        "notificaciones_cobranza",
        ["causa_cobranza_id"],
        unique=False,
    )

    op.create_table(
        "diligencias_cobranza",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_cobranza_id", sa.UUID(), nullable=False),
        sa.Column("doc_ida_id", sa.UUID(), nullable=True),
        sa.Column("doc_vta_id", sa.UUID(), nullable=True),
        sa.Column("estado_diligencia", sa.String(length=120), nullable=True),
        sa.Column("rit", sa.String(length=30), nullable=True),
        sa.Column("ruc", sa.String(length=60), nullable=True),
        sa.Column("tipo_diligencia", sa.String(length=200), nullable=True),
        sa.Column("fecha_tramite", sa.String(length=60), nullable=True),
        sa.Column("destinatario", sa.String(length=300), nullable=True),
        sa.Column("responsable", sa.String(length=300), nullable=True),
        sa.Column("contenido_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["causa_cobranza_id"], ["causas_cobranza.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doc_ida_id"], ["documentos_cobranza.id"]),
        sa.ForeignKeyConstraint(["doc_vta_id"], ["documentos_cobranza.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_cobranza_id", "contenido_hash", name="uq_diligencias_cobranza_causa_hash"),
    )
    op.create_index(
        op.f("ix_diligencias_cobranza_causa_cobranza_id"),
        "diligencias_cobranza",
        ["causa_cobranza_id"],
        unique=False,
    )

    op.create_table(
        "liquidaciones_cobranza",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_cobranza_id", sa.UUID(), nullable=False),
        sa.Column("liquidacion_doc_id", sa.UUID(), nullable=True),
        sa.Column("fecha_liquidacion", sa.String(length=60), nullable=True),
        sa.Column("cuaderno", sa.String(length=300), nullable=True),
        sa.Column("estado", sa.String(length=60), nullable=True),
        sa.Column("monto_liquido", sa.String(length=60), nullable=True),
        sa.Column("contenido_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["causa_cobranza_id"], ["causas_cobranza.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["liquidacion_doc_id"], ["documentos_cobranza.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_cobranza_id", "contenido_hash", name="uq_liquidaciones_cobranza_causa_hash"),
    )
    op.create_index(
        op.f("ix_liquidaciones_cobranza_causa_cobranza_id"),
        "liquidaciones_cobranza",
        ["causa_cobranza_id"],
        unique=False,
    )

    op.create_table(
        "documentos_laboral_cobranza",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_cobranza_id", sa.UUID(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("fecha", sa.String(length=60), nullable=True),
        sa.Column("referencia", sa.String(length=300), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["causa_cobranza_id"], ["causas_cobranza.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_cobranza.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "causa_cobranza_id", "referencia", "fecha", name="uq_documentos_laboral_cobranza_ref_fecha"
        ),
    )
    op.create_index(
        op.f("ix_documentos_laboral_cobranza_causa_cobranza_id"),
        "documentos_laboral_cobranza",
        ["causa_cobranza_id"],
        unique=False,
    )

    # --- sync_job: soportar jobs de cobranza -------------------------------------
    op.add_column("sync_job", sa.Column("causa_cobranza_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_sync_job_causa_cobranza_id"), "sync_job", ["causa_cobranza_id"], unique=False)
    op.create_foreign_key(
        "fk_sync_job_causa_cobranza_id",
        "sync_job",
        "causas_cobranza",
        ["causa_cobranza_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("ck_sync_job_una_causa", "sync_job", type_="check")
    op.create_check_constraint(
        "ck_sync_job_una_causa",
        "sync_job",
        "(CASE WHEN causa_id IS NOT NULL THEN 1 ELSE 0 END) "
        "+ (CASE WHEN causa_familia_id IS NOT NULL THEN 1 ELSE 0 END) "
        "+ (CASE WHEN causa_laboral_id IS NOT NULL THEN 1 ELSE 0 END) "
        "+ (CASE WHEN causa_cobranza_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sync_job_una_causa", "sync_job", type_="check")
    op.create_check_constraint(
        "ck_sync_job_una_causa",
        "sync_job",
        "(CASE WHEN causa_id IS NOT NULL THEN 1 ELSE 0 END) "
        "+ (CASE WHEN causa_familia_id IS NOT NULL THEN 1 ELSE 0 END) "
        "+ (CASE WHEN causa_laboral_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )
    op.drop_constraint("fk_sync_job_causa_cobranza_id", "sync_job", type_="foreignkey")
    op.drop_index(op.f("ix_sync_job_causa_cobranza_id"), table_name="sync_job")
    op.drop_column("sync_job", "causa_cobranza_id")

    op.drop_index(
        op.f("ix_documentos_laboral_cobranza_causa_cobranza_id"), table_name="documentos_laboral_cobranza"
    )
    op.drop_table("documentos_laboral_cobranza")
    op.drop_index(op.f("ix_liquidaciones_cobranza_causa_cobranza_id"), table_name="liquidaciones_cobranza")
    op.drop_table("liquidaciones_cobranza")
    op.drop_index(op.f("ix_diligencias_cobranza_causa_cobranza_id"), table_name="diligencias_cobranza")
    op.drop_table("diligencias_cobranza")
    op.drop_index(op.f("ix_notificaciones_cobranza_causa_cobranza_id"), table_name="notificaciones_cobranza")
    op.drop_table("notificaciones_cobranza")
    op.drop_index(op.f("ix_litigantes_cobranza_causa_cobranza_id"), table_name="litigantes_cobranza")
    op.drop_table("litigantes_cobranza")
    op.drop_index(
        op.f("ix_historia_cobranza_geo_imagenes_movimiento_id"), table_name="historia_cobranza_geo_imagenes"
    )
    op.drop_table("historia_cobranza_geo_imagenes")
    op.drop_index(op.f("ix_historia_cobranza_anexos_movimiento_id"), table_name="historia_cobranza_anexos")
    op.drop_table("historia_cobranza_anexos")
    op.drop_index(op.f("ix_historia_cobranza_docs_movimiento_id"), table_name="historia_cobranza_docs")
    op.drop_table("historia_cobranza_docs")
    op.drop_index("uq_historia_cobranza_causa_folio", table_name="historia_cobranza")
    op.drop_index(op.f("ix_historia_cobranza_causa_cobranza_id"), table_name="historia_cobranza")
    op.drop_table("historia_cobranza")
    op.drop_index(
        op.f("ix_informacion_receptor_cobranza_causa_cobranza_id"), table_name="informacion_receptor_cobranza"
    )
    op.drop_table("informacion_receptor_cobranza")
    op.drop_index(op.f("ix_anexos_causa_cobranza_causa_cobranza_id"), table_name="anexos_causa_cobranza")
    op.drop_table("anexos_causa_cobranza")
    op.drop_index(op.f("ix_cuadernos_cobranza_causa_cobranza_id"), table_name="cuadernos_cobranza")
    op.drop_table("cuadernos_cobranza")
    op.drop_index(op.f("ix_documentos_cobranza_causa_cobranza_id"), table_name="documentos_cobranza")
    op.drop_table("documentos_cobranza")
    op.drop_table("causas_cobranza")
