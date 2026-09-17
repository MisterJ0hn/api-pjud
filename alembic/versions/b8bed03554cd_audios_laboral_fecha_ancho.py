"""audios_laboral.fecha: ensanchar a 300 (el popup real trae el nombre de archivo, mas
largo de lo asumido, en la celda que se estaba mapeando como "fecha" -- ver worker/sync_laboral.py)

Revision ID: b8bed03554cd
Revises: e5d780a90703
Create Date: 2026-09-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8bed03554cd"
down_revision: Union[str, None] = "e5d780a90703"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "audios_laboral", "fecha", existing_type=sa.String(length=60), type_=sa.String(length=300)
    )


def downgrade() -> None:
    op.alter_column(
        "audios_laboral", "fecha", existing_type=sa.String(length=300), type_=sa.String(length=60)
    )
