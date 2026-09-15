"""civil: causa_origen (cabecera) + piezas_exhorto

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-15 00:00:00.000000

Actualizacion 15-09-2026 de Solicitud.md: causas de tipo Exhorto exponen "Causa Origen"
(rol + tribunal) en la cabecera, y una pestana propia "Piezas Exhorto" (causa-wide, no
por cuaderno) con los tramites del exhorto en el tribunal de destino. Validado en vivo
contra E-1798-2026.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("causas", sa.Column("causa_origen_rol", sa.String(length=40), nullable=True))
    op.add_column("causas", sa.Column("causa_origen_tribunal", sa.String(length=200), nullable=True))

    op.create_table(
        "piezas_exhorto",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("causa_id", sa.UUID(), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("folio", sa.String(length=30), nullable=True),
        sa.Column("cuaderno_texto", sa.String(length=30), nullable=True),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("etapa", sa.String(length=300), nullable=True),
        sa.Column("tramite", sa.String(length=300), nullable=True),
        sa.Column("descripcion_tramite", sa.String(length=1000), nullable=True),
        sa.Column("fecha_tramite", sa.String(length=60), nullable=True),
        sa.Column("foja", sa.String(length=30), nullable=True),
        sa.Column("hash_contenido", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["causa_id"], ["causas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("causa_id", "orden", name="uq_piezas_exhorto_causa_orden"),
    )
    op.create_index(
        op.f("ix_piezas_exhorto_causa_id"), "piezas_exhorto", ["causa_id"], unique=False
    )

    op.create_table(
        "piezas_exhorto_anexos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pieza_id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.String(length=60), nullable=True),
        sa.Column("referencia", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(["pieza_id"], ["piezas_exhorto.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pieza_id", "orden", name="uq_pieza_exhorto_anexo_pieza_orden"),
    )
    op.create_index(
        op.f("ix_piezas_exhorto_anexos_pieza_id"), "piezas_exhorto_anexos", ["pieza_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_piezas_exhorto_anexos_pieza_id"), table_name="piezas_exhorto_anexos")
    op.drop_table("piezas_exhorto_anexos")
    op.drop_index(op.f("ix_piezas_exhorto_causa_id"), table_name="piezas_exhorto")
    op.drop_table("piezas_exhorto")
    op.drop_column("causas", "causa_origen_tribunal")
    op.drop_column("causas", "causa_origen_rol")
