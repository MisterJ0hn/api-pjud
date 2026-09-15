"""familia: georeferencia por movimiento (mapa + imagenes)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-14 00:00:00.000000

Popup "Georeferencia" de Movimientos: mapa (lat/long/corrector) como columnas flat en
movimientos_historia_familia, imagenes en tabla propia (se sirven por GUID, ver
`url_publica_imagen_familia`). Videos queda sin tabla (estructura desconocida en PJUD).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("movimientos_historia_familia", sa.Column("geo_latitud", sa.String(length=30), nullable=True))
    op.add_column("movimientos_historia_familia", sa.Column("geo_longitud", sa.String(length=30), nullable=True))
    op.add_column("movimientos_historia_familia", sa.Column("geo_corrector", sa.String(length=30), nullable=True))

    op.create_table(
        "movimientos_historia_familia_geo_imagenes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movimiento_id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos_familia.id"]),
        sa.ForeignKeyConstraint(
            ["movimiento_id"], ["movimientos_historia_familia.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movimiento_id", "orden", name="uq_historia_familia_geo_img_mov_orden"),
    )
    op.create_index(
        op.f("ix_movimientos_historia_familia_geo_imagenes_movimiento_id"),
        "movimientos_historia_familia_geo_imagenes",
        ["movimiento_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_movimientos_historia_familia_geo_imagenes_movimiento_id"),
        table_name="movimientos_historia_familia_geo_imagenes",
    )
    op.drop_table("movimientos_historia_familia_geo_imagenes")
    op.drop_column("movimientos_historia_familia", "geo_corrector")
    op.drop_column("movimientos_historia_familia", "geo_longitud")
    op.drop_column("movimientos_historia_familia", "geo_latitud")
