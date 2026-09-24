"""color docs y anexos de movimientos

Revision ID: 8b4d102efd0c
Revises: 1d12c39363b2
Create Date: 2026-09-23 15:55:36.464577

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8b4d102efd0c'
down_revision: Union[str, None] = '1d12c39363b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLAS = (
    "movimientos_historia_docs",
    "movimientos_historia_anexos",
    "movimientos_historia_familia_docs",
    "movimientos_historia_familia_anexos",
    "movimientos_laboral_docs",
    "movimientos_laboral_anexos",
    "historia_cobranza_docs",
    "historia_cobranza_anexos",
)


def upgrade() -> None:
    for t in _TABLAS:
        op.add_column(t, sa.Column("color", sa.String(length=32), nullable=True))
    op.add_column("historia_cobranza", sa.Column("descripcion_tramite_doc_color", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("historia_cobranza", "descripcion_tramite_doc_color")
    for t in reversed(_TABLAS):
        op.drop_column(t, "color")
