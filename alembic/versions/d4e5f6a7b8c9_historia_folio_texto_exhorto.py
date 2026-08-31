"""historia: folio como texto y soporte de folios de exhorto ("[NE]")

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-31 15:30:00.000000

Los movimientos de un exhorto aparecen en la pestana Historia con el folio entre
corchetes ("[6E]", "[2E]"), numerados aparte y a veces repetidos (cuando la causa
tiene mas de un exhorto). El esquema anterior asumia folio entero y unico por
cuaderno, asi que el worker descartaba esas filas por completo (y sus documentos).

- `folio_texto`: el folio tal cual lo muestra PJUD ("33" o "[6E]").
- `folio`: pasa a ser nullable; solo la parte numerica, para ordenar.
- La unicidad (cuaderno, folio) se mantiene para folios normales via indice parcial;
  las filas de exhorto se identifican por (cuaderno, folio_texto, hash_contenido).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'movimientos_historia',
        sa.Column('folio_texto', sa.String(length=12), nullable=True),
    )
    op.execute(
        "UPDATE movimientos_historia SET folio_texto = folio::text WHERE folio_texto IS NULL"
    )
    op.alter_column('movimientos_historia', 'folio_texto', nullable=False)
    op.alter_column(
        'movimientos_historia', 'folio', existing_type=sa.Integer(), nullable=True
    )

    op.drop_constraint('uq_historia_cuaderno_folio', 'movimientos_historia', type_='unique')
    op.create_index(
        'uq_historia_cuaderno_folio',
        'movimientos_historia',
        ['cuaderno_id', 'folio'],
        unique=True,
        postgresql_where=sa.text("folio_texto NOT LIKE '[%'"),
    )
    op.create_unique_constraint(
        'uq_historia_cuaderno_foliotexto_hash',
        'movimientos_historia',
        ['cuaderno_id', 'folio_texto', 'hash_contenido'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_historia_cuaderno_foliotexto_hash', 'movimientos_historia', type_='unique'
    )
    op.drop_index('uq_historia_cuaderno_folio', table_name='movimientos_historia')

    # Las filas de exhorto no caben en el esquema viejo (folio no-nulo y unico).
    op.execute("DELETE FROM movimientos_historia WHERE folio_texto LIKE '[%'")

    op.alter_column(
        'movimientos_historia', 'folio', existing_type=sa.Integer(), nullable=False
    )
    op.create_unique_constraint(
        'uq_historia_cuaderno_folio', 'movimientos_historia', ['cuaderno_id', 'folio']
    )
    op.drop_column('movimientos_historia', 'folio_texto')
