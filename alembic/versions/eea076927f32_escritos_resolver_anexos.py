"""escritos_resolver_anexos

Revision ID: eea076927f32
Revises: d8a2c038b60c
Create Date: 2026-09-16 13:00:00.000000

"Escritos por Resolver" tiene su propio popup de anexo (`modalAnexoSolEscritoCivil`,
columnas Doc./Fecha/Referencia) que no se estaba scrapeando -- confirmado en vivo en
C-1964-2026 (tribunal 4 Juzgado de Letras Civil de Antofagasta). Misma forma que
`movimientos_historia_anexos` / `piezas_exhorto_anexos`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'eea076927f32'
down_revision: Union[str, None] = 'd8a2c038b60c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "escritos_resolver_anexos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("escrito_id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.String(length=60), nullable=True),
        sa.Column("referencia", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(["escrito_id"], ["escritos_resolver.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("escrito_id", "orden", name="uq_escritos_resolver_anexo_escrito_orden"),
    )
    op.create_index(
        op.f("ix_escritos_resolver_anexos_escrito_id"),
        "escritos_resolver_anexos",
        ["escrito_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_escritos_resolver_anexos_escrito_id"),
        table_name="escritos_resolver_anexos",
    )
    op.drop_table("escritos_resolver_anexos")
