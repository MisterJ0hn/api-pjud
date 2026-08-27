"""credenciales privadas en sync_job

Revision ID: a1b2c3d4e5f6
Revises: 497c8671178f
Create Date: 2026-08-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '497c8671178f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sync_job', sa.Column('rut_cifrado', sa.String(length=500), nullable=True))
    op.add_column('sync_job', sa.Column('clave_cifrada', sa.String(length=1000), nullable=True))
    op.add_column('sync_job', sa.Column('metodo_login', sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('sync_job', 'metodo_login')
    op.drop_column('sync_job', 'clave_cifrada')
    op.drop_column('sync_job', 'rut_cifrado')
