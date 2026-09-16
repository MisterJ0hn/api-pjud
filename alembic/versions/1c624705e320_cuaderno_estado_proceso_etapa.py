"""cuadernos: columnas estado_proceso / etapa

Revision ID: 1c624705e320
Revises: eea076927f32
Create Date: 2026-09-16 14:00:00.000000

"Estado Proc."/"Etapa" de la cabecera cambian segun el cuaderno seleccionado en el
modal de PJUD, no son un valor unico por causa como se asumio originalmente -- ver
`api/db/models/causas.py::Cuaderno` y [[causas-privadas-civil]]. Confirmado en vivo en
C-1964-2026 (cuaderno "Principal" en "Tramitación", cuaderno "Administración Concursal"
en "Sin tramitación").
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '1c624705e320'
down_revision: Union[str, None] = 'eea076927f32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cuadernos", sa.Column("estado_proceso", sa.String(length=200), nullable=True))
    op.add_column("cuadernos", sa.Column("etapa", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("cuadernos", "etapa")
    op.drop_column("cuadernos", "estado_proceso")
