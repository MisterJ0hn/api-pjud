"""historia con multiples documentos por folio

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'movimientos_historia_docs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('movimiento_id', sa.Integer(), nullable=False),
        sa.Column('documento_id', sa.UUID(), nullable=True),
        sa.Column('orden', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['documento_id'], ['documentos.id'], ),
        sa.ForeignKeyConstraint(['movimiento_id'], ['movimientos_historia.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('movimiento_id', 'orden', name='uq_historia_doc_movimiento_orden'),
    )
    op.create_index(
        op.f('ix_movimientos_historia_docs_movimiento_id'),
        'movimientos_historia_docs', ['movimiento_id'], unique=False,
    )

    # Migrar el unico documento que hoy cuelga de cada folio a orden = 1.
    op.execute(
        """
        INSERT INTO movimientos_historia_docs (movimiento_id, documento_id, orden)
        SELECT id, documento_id, 1
        FROM movimientos_historia
        WHERE documento_id IS NOT NULL
        """
    )

    op.drop_column('movimientos_historia', 'documento_id')


def downgrade() -> None:
    op.add_column(
        'movimientos_historia',
        sa.Column('documento_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'movimientos_historia_documento_id_fkey',
        'movimientos_historia', 'documentos', ['documento_id'], ['id'],
    )
    op.execute(
        """
        UPDATE movimientos_historia mh
        SET documento_id = d.documento_id
        FROM movimientos_historia_docs d
        WHERE d.movimiento_id = mh.id AND d.orden = 1
        """
    )
    op.drop_index(
        op.f('ix_movimientos_historia_docs_movimiento_id'),
        table_name='movimientos_historia_docs',
    )
    op.drop_table('movimientos_historia_docs')
