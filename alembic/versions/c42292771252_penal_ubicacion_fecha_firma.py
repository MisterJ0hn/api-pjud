"""penal: ubicacion en cabecera, historia.estado_firma -> fecha_firma, sin etapa/rut

Revision ID: c42292771252
Revises: c25eaeaa737b
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c42292771252"
down_revision: Union[str, None] = "c25eaeaa737b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("causas_penal", sa.Column("ubicacion", sa.String(length=200), nullable=True))
    op.alter_column("historia_penal", "estado_firma", new_column_name="fecha_firma")
    op.drop_column("historia_penal", "etapa")
    op.drop_column("litigantes_penal", "rut")


def downgrade() -> None:
    op.add_column("litigantes_penal", sa.Column("rut", sa.String(length=15), nullable=True))
    op.add_column("historia_penal", sa.Column("etapa", sa.String(length=300), nullable=True))
    op.alter_column("historia_penal", "fecha_firma", new_column_name="estado_firma")
    op.drop_column("causas_penal", "ubicacion")
