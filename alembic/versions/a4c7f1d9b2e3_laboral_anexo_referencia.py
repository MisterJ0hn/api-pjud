"""movimientos_laboral_anexos: "Solicitud Laboral.md" define el anexo de Laboral solo
con doc/fecha/referencia (sin folio ni observación, a diferencia de Familia) -- se
confirmo en vivo (causa O-692-2019) que la columna real del popup se llama
"Referencia", no "Nombre Documento". Renombra nombre_documento -> referencia y quita
folio/observacion (no forman parte del contrato de Laboral).

Revision ID: a4c7f1d9b2e3
Revises: b8bed03554cd
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4c7f1d9b2e3"
down_revision: Union[str, None] = "b8bed03554cd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "movimientos_laboral_anexos", "nombre_documento", new_column_name="referencia"
    )
    op.drop_column("movimientos_laboral_anexos", "folio")
    op.drop_column("movimientos_laboral_anexos", "observacion")


def downgrade() -> None:
    op.add_column(
        "movimientos_laboral_anexos", sa.Column("observacion", sa.String(length=500), nullable=True)
    )
    op.add_column(
        "movimientos_laboral_anexos", sa.Column("folio", sa.Integer(), nullable=True)
    )
    op.alter_column(
        "movimientos_laboral_anexos", "referencia", new_column_name="nombre_documento"
    )
