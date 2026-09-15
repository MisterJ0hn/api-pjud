"""civil: georeferencia por movimiento de Historia (mapa + imagenes)

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-09-15 01:00:00.000000

Mismo popup "Georeferencia" que ya existe en Familia (modalGeoReferenciaCivil, columna
"Georref." de Historia): mapa (lat/long/corrector) como columnas flat en
movimientos_historia, imagenes en tabla propia (se sirven por GUID, ver
`url_publica_imagen`). Videos queda sin tabla (estructura desconocida en PJUD).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("movimientos_historia", sa.Column("geo_latitud", sa.String(length=30), nullable=True))
    op.add_column("movimientos_historia", sa.Column("geo_longitud", sa.String(length=30), nullable=True))
    op.add_column("movimientos_historia", sa.Column("geo_corrector", sa.String(length=30), nullable=True))

    op.create_table(
        "movimientos_historia_geo_imagenes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movimiento_id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"]),
        sa.ForeignKeyConstraint(
            ["movimiento_id"], ["movimientos_historia.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movimiento_id", "orden", name="uq_historia_geo_img_movimiento_orden"),
    )
    op.create_index(
        op.f("ix_movimientos_historia_geo_imagenes_movimiento_id"),
        "movimientos_historia_geo_imagenes",
        ["movimiento_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_movimientos_historia_geo_imagenes_movimiento_id"),
        table_name="movimientos_historia_geo_imagenes",
    )
    op.drop_table("movimientos_historia_geo_imagenes")
    op.drop_column("movimientos_historia", "geo_corrector")
    op.drop_column("movimientos_historia", "geo_longitud")
    op.drop_column("movimientos_historia", "geo_latitud")
