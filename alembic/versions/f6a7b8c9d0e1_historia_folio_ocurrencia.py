"""historia: columna ocurrencia para folios normales repetidos

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-08 00:00:00.000000

PJUD puede repetir el mismo folio "normal" (no exhorto) dos veces dentro del
mismo cuaderno (visto en C-756-2022, folio 14 del cuaderno Principal). Hasta
ahora la clave natural de un folio normal era (cuaderno_id, folio): la segunda
fila con el mismo folio pisaba a la primera en cada sync en vez de insertarse
aparte, y el UNIQUE (cuaderno_id, folio) la habria rechazado si el codigo
hubiera intentado insertarla.

Se agrega `ocurrencia` (1a vez que aparece ese folio en el orden de Historia,
2a vez, etc.) y se la suma a la clave natural. Las filas existentes son todas
`ocurrencia=1` (caso normal, un folio = una fila); la proxima sync de una causa
con folios repetidos inserta la fila que faltaba en vez de seguir pisandola.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "movimientos_historia",
        sa.Column("ocurrencia", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("movimientos_historia", "ocurrencia", server_default=None)

    op.execute('DROP INDEX IF EXISTS "uq_historia_cuaderno_folio"')
    op.execute(
        'CREATE UNIQUE INDEX "uq_historia_cuaderno_folio" '
        "ON movimientos_historia (cuaderno_id, folio, ocurrencia) "
        "WHERE folio_texto NOT LIKE '[%'"
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS "uq_historia_cuaderno_folio"')
    op.execute(
        'CREATE UNIQUE INDEX "uq_historia_cuaderno_folio" '
        "ON movimientos_historia (cuaderno_id, folio) "
        "WHERE folio_texto NOT LIKE '[%'"
    )
    op.drop_column("movimientos_historia", "ocurrencia")
