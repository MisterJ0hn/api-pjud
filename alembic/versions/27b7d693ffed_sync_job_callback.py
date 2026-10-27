"""callback opcional por sync_job

Revision ID: 27b7d693ffed
Revises: ed1178454556
Create Date: 2026-10-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "27b7d693ffed"
down_revision: Union[str, None] = "ed1178454556"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sync_job", sa.Column("callback_url", sa.String(length=2000), nullable=True))
    op.add_column("sync_job", sa.Column("callback_estado", sa.String(length=15), nullable=True))
    op.add_column("sync_job", sa.Column("callback_intentos", sa.SmallInteger(), server_default="0", nullable=False))
    op.add_column("sync_job", sa.Column("callback_proximo_intento", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sync_job", sa.Column("callback_mensaje_error", sa.String(length=2000), nullable=True))
    op.create_check_constraint(
        "ck_sync_job_callback_estado",
        "sync_job",
        "callback_estado IS NULL OR callback_estado IN ('pendiente', 'entregado', 'fallido')",
    )
    op.create_index(
        "ix_sync_job_callback_pendiente",
        "sync_job",
        ["callback_proximo_intento"],
        postgresql_where=sa.text("callback_estado = 'pendiente'"),
    )


def downgrade() -> None:
    op.drop_index("ix_sync_job_callback_pendiente", table_name="sync_job")
    op.drop_constraint("ck_sync_job_callback_estado", "sync_job", type_="check")
    op.drop_column("sync_job", "callback_mensaje_error")
    op.drop_column("sync_job", "callback_proximo_intento")
    op.drop_column("sync_job", "callback_intentos")
    op.drop_column("sync_job", "callback_estado")
    op.drop_column("sync_job", "callback_url")
