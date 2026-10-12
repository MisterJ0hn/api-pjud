"""usuarios permitidos por causa privada

Revision ID: d428f11eb9a8
Revises: 1de143617deb
Create Date: 2026-10-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd428f11eb9a8'
down_revision: Union[str, None] = '1de143617deb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# competencia -> tabla de causas
COMPETENCIAS = {
    "civil": "causas",
    "familia": "causas_familia",
    "laboral": "causas_laboral",
    "cobranza": "causas_cobranza",
    "penal": "causas_penal",
}


def upgrade() -> None:
    for competencia, tabla_causas in COMPETENCIAS.items():
        nombre = f"usuario_{competencia}_permitido"
        op.create_table(
            nombre,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("causa_id", sa.UUID(), nullable=False),
            sa.Column("rut", sa.String(length=12), nullable=False),
            sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["causa_id"], [f"{tabla_causas}.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("causa_id", "rut", name=f"uq_{nombre}"),
        )
        op.create_index(f"ix_{nombre}_causa_id", nombre, ["causa_id"])

    # La verificacion de acceso por scraping desaparece.
    op.drop_table("acceso_verificado")
    op.drop_column("sync_job", "huella_acceso")
    op.drop_column("sync_job", "acceso_concedido")
    op.drop_column("sync_job", "tipo")


def downgrade() -> None:
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
    for competencia in COMPETENCIAS:
        op.drop_table(f"usuario_{competencia}_permitido")
