"""penal: notificaciones.estampado pasa a documento (estampado_doc_id)

Revision ID: dafbdfeaca82
Revises: c42292771252
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "dafbdfeaca82"
down_revision: Union[str, None] = "c42292771252"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notificaciones_penal", sa.Column("estampado_doc_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_notificaciones_penal_estampado_doc",
        "notificaciones_penal",
        "documentos_penal",
        ["estampado_doc_id"],
        ["id"],
    )
    op.drop_column("notificaciones_penal", "estampado")


def downgrade() -> None:
    op.add_column("notificaciones_penal", sa.Column("estampado", sa.String(length=300), nullable=True))
    op.drop_constraint("fk_notificaciones_penal_estampado_doc", "notificaciones_penal", type_="foreignkey")
    op.drop_column("notificaciones_penal", "estampado_doc_id")
