"""competencia laboral: tablas propias + sync_job.causa_laboral_id

Revision ID: e5d780a90703
Revises: 1c624705e320
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5d780a90703"
down_revision: Union[str, None] = "1c624705e320"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "causas_laboral",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("corte", sa.Integer(), nullable=False),
        sa.Column("tribunal", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=4), nullable=False),
        sa.Column("rol", sa.Integer(), nullable=False),
        sa.Column("anio", sa.Integer(), nullable=False),
        sa.Column("rit", sa.String(length=40), nullable=False),
        sa.Column("caratula", sa.String(length=500), nullable=True),
        sa.Column("ruc", sa.String(length=60), nullable=True),
        sa.Column("fecha_ingreso", sa.String(length=20), nullable=True),
        sa.Column("proceso", sa.String(length=300), nullable=True),
        sa.Column("forma_inicio", sa.String(length=200), nullable=True),
        sa.Column("est_adm", sa.String(length=200), nullable=True),
        sa.Column("etapa", sa.String(length=300), nullable=True),
        sa.Column("estado_proceso", sa.String(length=200), nullable=True),
        sa.Column("tribunal_nombre", sa.String(length=200), nullable=True),
        sa.Column("tramites", sa.String(length=300), nullable=True),
        sa.Column("estado_sync", sa.String(length=15), nullable=False),
        sa.Column("sync_detalle", sa.String(length=300), nullable=True),
        sa.Column("sync_iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_ultima_sincronizacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_error", sa.String(length=2000), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "estado_sync IN ('Pendiente', 'Sincronizando', 'Completo', 'Error')",
            name="ck_causas_laboral_estado_sync",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("corte", "tribunal", "tipo", "rol", "anio", name="uq_causas_laboral_clave_natural"),
    )

    op.create_table(
        "documentos_laboral",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("causa_laboral_id", sa.UUID(), nullable=False),
        sa.Column("categoria", sa.String(length=40), nullable=False),
        sa.Column("clave_logica", sa.String(length=160), nullable=False),
        sa.Column("nombre_archivo", sa.String(length=160), nullable=False),
        sa.Column("ruta_archivo", sa.String(length=1000), nullable=False),
        sa.Column("hash_contenido_fila_padre", sa.String(length=64), nullable=True),
        sa.Column("referencia_origen", sa.String(length=300), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["causa_laboral_id"], ["causas_laboral.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_laboral_id", "clave_logica", name="uq_documentos_laboral_causa_clave"),
    )
    op.create_index(
        op.f("ix_documentos_laboral_causa_laboral_id"), "documentos_laboral", ["causa_laboral_id"], unique=False
    )

    op.create_table(
        "textos_demanda_laboral",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_laboral_id", sa.UUID(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("doc_demanda", sa.Integer(), nullable=True),
        sa.Column("fecha", sa.String(length=60), nullable=True),
        sa.Column("referencia", sa.String(length=300), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["causa_laboral_id"], ["causas_laboral.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_laboral.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "causa_laboral_id", "referencia", "fecha", name="uq_textos_demanda_laboral_ref_fecha"
        ),
    )
    op.create_index(
        op.f("ix_textos_demanda_laboral_causa_laboral_id"),
        "textos_demanda_laboral",
        ["causa_laboral_id"],
        unique=False,
    )

    op.create_table(
        "audios_laboral",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_laboral_id", sa.UUID(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("numero", sa.Integer(), nullable=True),
        sa.Column("fecha", sa.String(length=60), nullable=True),
        sa.Column("referencia", sa.String(length=300), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["causa_laboral_id"], ["causas_laboral.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_laboral.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_laboral_id", "orden", name="uq_audios_laboral_causa_orden"),
    )
    op.create_index(
        op.f("ix_audios_laboral_causa_laboral_id"), "audios_laboral", ["causa_laboral_id"], unique=False
    )

    op.create_table(
        "movimientos_laboral",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_laboral_id", sa.UUID(), nullable=False),
        sa.Column("folio_texto", sa.String(length=12), nullable=False),
        sa.Column("folio", sa.Integer(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("etapa", sa.String(length=300), nullable=True),
        sa.Column("estado", sa.String(length=200), nullable=True),
        sa.Column("tramite", sa.String(length=300), nullable=True),
        sa.Column("descripcion_tramite", sa.String(length=1000), nullable=True),
        sa.Column("fecha_tramite", sa.String(length=60), nullable=True),
        sa.Column("hash_contenido", sa.String(length=64), nullable=False),
        sa.Column("ocurrencia", sa.Integer(), nullable=False),
        sa.Column("geo_latitud", sa.String(length=30), nullable=True),
        sa.Column("geo_longitud", sa.String(length=30), nullable=True),
        sa.Column("geo_corrector", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(["causa_laboral_id"], ["causas_laboral.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_movimientos_laboral_causa_laboral_id"),
        "movimientos_laboral",
        ["causa_laboral_id"],
        unique=False,
    )
    op.create_index(
        "uq_movimientos_laboral_causa_folio",
        "movimientos_laboral",
        ["causa_laboral_id", "folio", "ocurrencia"],
        unique=True,
        postgresql_where=sa.text("folio_texto NOT LIKE '[%'"),
    )

    op.create_table(
        "movimientos_laboral_docs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movimiento_id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_laboral.id"]),
        sa.ForeignKeyConstraint(["movimiento_id"], ["movimientos_laboral.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movimiento_id", "orden", name="uq_movimientos_laboral_doc_mov_orden"),
    )
    op.create_index(
        op.f("ix_movimientos_laboral_docs_movimiento_id"),
        "movimientos_laboral_docs",
        ["movimiento_id"],
        unique=False,
    )

    op.create_table(
        "movimientos_laboral_anexos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movimiento_id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("folio", sa.Integer(), nullable=True),
        sa.Column("fecha", sa.String(length=60), nullable=True),
        sa.Column("nombre_documento", sa.String(length=300), nullable=True),
        sa.Column("observacion", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_laboral.id"]),
        sa.ForeignKeyConstraint(["movimiento_id"], ["movimientos_laboral.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movimiento_id", "orden", name="uq_movimientos_laboral_anexo_mov_orden"),
    )
    op.create_index(
        op.f("ix_movimientos_laboral_anexos_movimiento_id"),
        "movimientos_laboral_anexos",
        ["movimiento_id"],
        unique=False,
    )

    op.create_table(
        "movimientos_laboral_geo_imagenes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movimiento_id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_laboral.id"]),
        sa.ForeignKeyConstraint(["movimiento_id"], ["movimientos_laboral.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movimiento_id", "orden", name="uq_movimientos_laboral_geo_img_mov_orden"),
    )
    op.create_index(
        op.f("ix_movimientos_laboral_geo_imagenes_movimiento_id"),
        "movimientos_laboral_geo_imagenes",
        ["movimiento_id"],
        unique=False,
    )

    op.create_table(
        "litigantes_laboral",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_laboral_id", sa.UUID(), nullable=False),
        sa.Column("estado", sa.Integer(), nullable=True),
        sa.Column("defensor", sa.String(length=10), nullable=True),
        sa.Column("sujeto", sa.String(length=60), nullable=True),
        sa.Column("rut", sa.String(length=15), nullable=True),
        sa.Column("persona", sa.String(length=10), nullable=True),
        sa.Column("razon_social", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["causa_laboral_id"], ["causas_laboral.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_litigantes_laboral_causa_laboral_id"), "litigantes_laboral", ["causa_laboral_id"], unique=False
    )

    op.create_table(
        "materias_laboral",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_laboral_id", sa.UUID(), nullable=False),
        sa.Column("codigo", sa.String(length=30), nullable=True),
        sa.Column("glosa_materia", sa.String(length=500), nullable=True),
        sa.Column("estado", sa.String(length=60), nullable=True),
        sa.Column("fecha_termino", sa.String(length=60), nullable=True),
        sa.Column("contenido_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["causa_laboral_id"], ["causas_laboral.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_laboral_id", "contenido_hash", name="uq_materias_laboral_causa_hash"),
    )
    op.create_index(
        op.f("ix_materias_laboral_causa_laboral_id"), "materias_laboral", ["causa_laboral_id"], unique=False
    )

    op.create_table(
        "notificaciones_laboral",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_laboral_id", sa.UUID(), nullable=False),
        sa.Column("estado_notificacion", sa.String(length=60), nullable=True),
        sa.Column("fecha_tramite", sa.String(length=60), nullable=True),
        sa.Column("tipo_parte", sa.String(length=60), nullable=True),
        sa.Column("nombre", sa.String(length=300), nullable=True),
        sa.Column("tramite", sa.String(length=300), nullable=True),
        sa.Column("observacion_fallida", sa.String(length=500), nullable=True),
        sa.Column("contenido_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["causa_laboral_id"], ["causas_laboral.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "causa_laboral_id", "contenido_hash", name="uq_notificaciones_laboral_causa_hash"
        ),
    )
    op.create_index(
        op.f("ix_notificaciones_laboral_causa_laboral_id"),
        "notificaciones_laboral",
        ["causa_laboral_id"],
        unique=False,
    )

    op.create_table(
        "diligencias_laboral",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_laboral_id", sa.UUID(), nullable=False),
        sa.Column("doc_ida_id", sa.UUID(), nullable=True),
        sa.Column("doc_vta_id", sa.UUID(), nullable=True),
        sa.Column("estado_diligencia", sa.String(length=120), nullable=True),
        sa.Column("rit", sa.String(length=30), nullable=True),
        sa.Column("ruc", sa.String(length=60), nullable=True),
        sa.Column("tipo_diligencia", sa.String(length=200), nullable=True),
        sa.Column("referencia", sa.String(length=500), nullable=True),
        sa.Column("fecha_tramite", sa.String(length=60), nullable=True),
        sa.Column("contenido_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["causa_laboral_id"], ["causas_laboral.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doc_ida_id"], ["documentos_laboral.id"]),
        sa.ForeignKeyConstraint(["doc_vta_id"], ["documentos_laboral.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_laboral_id", "contenido_hash", name="uq_diligencias_laboral_causa_hash"),
    )
    op.create_index(
        op.f("ix_diligencias_laboral_causa_laboral_id"),
        "diligencias_laboral",
        ["causa_laboral_id"],
        unique=False,
    )

    op.create_table(
        "liquidaciones_laboral",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_laboral_id", sa.UUID(), nullable=False),
        sa.Column("liquidacion", sa.String(length=300), nullable=True),
        sa.Column("rut", sa.String(length=15), nullable=True),
        sa.Column("nombre", sa.String(length=300), nullable=True),
        sa.Column("monto_liquido", sa.String(length=60), nullable=True),
        sa.Column("contenido_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["causa_laboral_id"], ["causas_laboral.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "causa_laboral_id", "contenido_hash", name="uq_liquidaciones_laboral_causa_hash"
        ),
    )
    op.create_index(
        op.f("ix_liquidaciones_laboral_causa_laboral_id"),
        "liquidaciones_laboral",
        ["causa_laboral_id"],
        unique=False,
    )

    op.create_table(
        "escritos_pendientes_laboral",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_laboral_id", sa.UUID(), nullable=False),
        sa.Column("doc_id", sa.UUID(), nullable=True),
        sa.Column("anexo_id", sa.UUID(), nullable=True),
        sa.Column("fecha_ing", sa.String(length=60), nullable=True),
        sa.Column("referencia", sa.String(length=300), nullable=True),
        sa.Column("solicitante", sa.String(length=300), nullable=True),
        sa.Column("tipo_ingreso", sa.String(length=200), nullable=True),
        sa.Column("contenido_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["anexo_id"], ["documentos_laboral.id"]),
        sa.ForeignKeyConstraint(["causa_laboral_id"], ["causas_laboral.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doc_id"], ["documentos_laboral.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "causa_laboral_id", "contenido_hash", name="uq_escritos_pendientes_laboral_causa_hash"
        ),
    )
    op.create_index(
        op.f("ix_escritos_pendientes_laboral_causa_laboral_id"),
        "escritos_pendientes_laboral",
        ["causa_laboral_id"],
        unique=False,
    )

    # --- sync_job: soportar jobs de laboral -------------------------------------
    op.add_column("sync_job", sa.Column("causa_laboral_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_sync_job_causa_laboral_id"), "sync_job", ["causa_laboral_id"], unique=False)
    op.create_foreign_key(
        "fk_sync_job_causa_laboral_id",
        "sync_job",
        "causas_laboral",
        ["causa_laboral_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("ck_sync_job_una_causa", "sync_job", type_="check")
    op.create_check_constraint(
        "ck_sync_job_una_causa",
        "sync_job",
        "(CASE WHEN causa_id IS NOT NULL THEN 1 ELSE 0 END) "
        "+ (CASE WHEN causa_familia_id IS NOT NULL THEN 1 ELSE 0 END) "
        "+ (CASE WHEN causa_laboral_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sync_job_una_causa", "sync_job", type_="check")
    op.create_check_constraint(
        "ck_sync_job_una_causa",
        "sync_job",
        "(causa_id IS NOT NULL) <> (causa_familia_id IS NOT NULL)",
    )
    op.drop_constraint("fk_sync_job_causa_laboral_id", "sync_job", type_="foreignkey")
    op.drop_index(op.f("ix_sync_job_causa_laboral_id"), table_name="sync_job")
    op.drop_column("sync_job", "causa_laboral_id")

    op.drop_index(
        op.f("ix_escritos_pendientes_laboral_causa_laboral_id"), table_name="escritos_pendientes_laboral"
    )
    op.drop_table("escritos_pendientes_laboral")
    op.drop_index(op.f("ix_liquidaciones_laboral_causa_laboral_id"), table_name="liquidaciones_laboral")
    op.drop_table("liquidaciones_laboral")
    op.drop_index(op.f("ix_diligencias_laboral_causa_laboral_id"), table_name="diligencias_laboral")
    op.drop_table("diligencias_laboral")
    op.drop_index(op.f("ix_notificaciones_laboral_causa_laboral_id"), table_name="notificaciones_laboral")
    op.drop_table("notificaciones_laboral")
    op.drop_index(op.f("ix_materias_laboral_causa_laboral_id"), table_name="materias_laboral")
    op.drop_table("materias_laboral")
    op.drop_index(op.f("ix_litigantes_laboral_causa_laboral_id"), table_name="litigantes_laboral")
    op.drop_table("litigantes_laboral")
    op.drop_index(
        op.f("ix_movimientos_laboral_geo_imagenes_movimiento_id"), table_name="movimientos_laboral_geo_imagenes"
    )
    op.drop_table("movimientos_laboral_geo_imagenes")
    op.drop_index(op.f("ix_movimientos_laboral_anexos_movimiento_id"), table_name="movimientos_laboral_anexos")
    op.drop_table("movimientos_laboral_anexos")
    op.drop_index(op.f("ix_movimientos_laboral_docs_movimiento_id"), table_name="movimientos_laboral_docs")
    op.drop_table("movimientos_laboral_docs")
    op.drop_index("uq_movimientos_laboral_causa_folio", table_name="movimientos_laboral")
    op.drop_index(op.f("ix_movimientos_laboral_causa_laboral_id"), table_name="movimientos_laboral")
    op.drop_table("movimientos_laboral")
    op.drop_index(op.f("ix_audios_laboral_causa_laboral_id"), table_name="audios_laboral")
    op.drop_table("audios_laboral")
    op.drop_index(op.f("ix_textos_demanda_laboral_causa_laboral_id"), table_name="textos_demanda_laboral")
    op.drop_table("textos_demanda_laboral")
    op.drop_index(op.f("ix_documentos_laboral_causa_laboral_id"), table_name="documentos_laboral")
    op.drop_table("documentos_laboral")
    op.drop_table("causas_laboral")
