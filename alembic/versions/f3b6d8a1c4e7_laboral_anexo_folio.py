"""movimientos_laboral_anexos: re-agrega folio (SI existe en el popup real, confirmado en
vivo -- causa O-692-2019, columnas reales Doc./Folio/Fecha/Referencia; la migracion
anterior lo habia quitado siguiendo el ejemplo incompleto de "Solicitud Laboral.md").

Revision ID: f3b6d8a1c4e7
Revises: a4c7f1d9b2e3
Create Date: 2026-09-21 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3b6d8a1c4e7"
down_revision: Union[str, None] = "a4c7f1d9b2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "movimientos_laboral_anexos", sa.Column("folio", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("movimientos_laboral_anexos", "folio")
