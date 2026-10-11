"""visibilidad causas y verificacion de acceso

Revision ID: 1de143617deb
Revises: dafbdfeaca82
Create Date: 2026-10-10 21:32:48.383854

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1de143617deb'
down_revision: Union[str, None] = 'dafbdfeaca82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLAS = ("causas", "causas_familia", "causas_laboral", "causas_cobranza", "causas_penal")


def upgrade() -> None:
    for tabla in TABLAS:
        op.add_column(tabla, sa.Column("visibilidad", sa.String(length=10), nullable=True))

    op.add_column("sync_job", sa.Column("tipo", sa.String(length=15), nullable=False, server_default="sync"))
    op.add_column("sync_job", sa.Column("acceso_concedido", sa.Boolean(), nullable=True))
    op.add_column("sync_job", sa.Column("huella_acceso", sa.String(length=64), nullable=True))

    op.create_table(
        "acceso_verificado",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("competencia", sa.String(length=20), nullable=False),
        sa.Column("causa_id", sa.UUID(), nullable=False),
        sa.Column("huella", sa.String(length=64), nullable=False),
        sa.Column("verificado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("competencia", "causa_id", "huella", name="uq_acceso_verificado"),
    )


def downgrade() -> None:
    op.drop_table("acceso_verificado")
    op.drop_column("sync_job", "huella_acceso")
    op.drop_column("sync_job", "acceso_concedido")
    op.drop_column("sync_job", "tipo")
    for tabla in TABLAS:
        op.drop_column(tabla, "visibilidad")
