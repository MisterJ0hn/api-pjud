"""anexos_causa_familia: agregar columna folio

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-14 00:00:00.000000

El sub-modal "Anexos de la causa" de Familia trae columna Folio (a diferencia
del de Civil/Cobranza, que no la tiene). Se expone en consultar_familia.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("anexos_causa_familia", sa.Column("folio", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("anexos_causa_familia", "folio")
