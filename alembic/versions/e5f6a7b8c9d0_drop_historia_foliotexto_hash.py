"""historia: eliminar constraint uq_historia_cuaderno_foliotexto_hash

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-01 19:00:00.000000

La constraint UNIQUE (cuaderno_id, folio_texto, hash_contenido) se agrego a mano
en produccion y nunca estuvo en el modelo ni en una migracion. Contradice el
diseno de exhortos: un mismo "[NE] <tramite>" puede repetirse identico entre dos
exhortos de la misma causa (mismo folio_texto y mismo hash_contenido), y esas
filas se reemplazan enteras en cada sync. Con la constraint puesta, la segunda
insercion revienta con UniqueViolationError y la causa queda pegada en
"Sincronizando".

Se borra con IF EXISTS porque solo existe en el entorno donde se creo a mano.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE movimientos_historia "
        "DROP CONSTRAINT IF EXISTS uq_historia_cuaderno_foliotexto_hash"
    )


def downgrade() -> None:
    # No se recrea: nunca fue parte del esquema y rompe la sincronizacion de exhortos.
    pass
