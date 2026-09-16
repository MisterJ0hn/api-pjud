"""anexos_causa / anexos_causa_familia: columna target

Revision ID: a1b2c3d4e5f6
Revises: e1f2a3b4c5d6
Create Date: 2026-09-16 12:00:00.000000

El popup "Anexo de la Causa" (civil y familia) renderiza cada fila con
`<form name="formAnex" ... target="N">`, con N secuencial en el orden real de PJUD.
El cliente reporto que el orden mostrado no coincidia con ese orden real (la fila se
guardaba/mostraba segun insercion o clave natural referencia+fecha, que no es estable).
Se agrega `target` para poder ordenar por el orden real de PJUD en vez de eso.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("anexos_causa", sa.Column("target", sa.Integer(), nullable=True))
    op.add_column("anexos_causa_familia", sa.Column("target", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("anexos_causa_familia", "target")
    op.drop_column("anexos_causa", "target")
