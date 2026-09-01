"""Migracion one-shot: mueve los archivos de <documentos_dir>/<rol_fmt>/... al nuevo
layout <documentos_dir>/<causa_id>/... y actualiza documentos.ruta_archivo.

Motivo: la misma RIT (p. ej. C-5656-2021) puede existir en dos tribunales -> mismo
rol_fmt -> los archivos se pisaban entre si en disco. Ahora la carpeta raiz es el id
(UUID) de la causa.

- Si el archivo existe en la ruta vieja: se mueve y se actualiza la fila.
- Si NO existe (una colision previa ya lo habia sobrescrito / borrado): se deja la
  fila apuntando a la ruta nueva inexistente; el worker la re-descarga en el proximo
  sync (ver _obtener_o_descargar_documento).

Uso:  docker compose exec worker python -m scripts.migrar_documentos_a_causa_id
      (agregar --dry-run para solo listar)
"""

import os
import shutil
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from api.config import settings
from api.db.models.causas import Cuaderno
from api.db.models.documentos import Documento
from worker.idempotencia import ruta_documento

DRY_RUN = "--dry-run" in sys.argv


def main() -> None:
    engine = create_engine(settings.database_url_sync)
    movidos = actualizados = faltantes = ok = 0

    with Session(engine) as session:
        docs = session.execute(select(Documento)).scalars().all()
        cuadernos = {c.id: c.numero for c in session.execute(select(Cuaderno)).scalars().all()}

        for d in docs:
            cuaderno_numero = cuadernos.get(d.cuaderno_id) if d.cuaderno_id else None
            _, ext = os.path.splitext(d.ruta_archivo)
            destino = ruta_documento(d.causa_id, d.clave_logica, cuaderno_numero, ext or ".pdf")

            if os.path.abspath(destino) == os.path.abspath(d.ruta_archivo):
                ok += 1
                continue

            if os.path.isfile(d.ruta_archivo):
                print(f"MOVER  {d.ruta_archivo}\n    -> {destino}")
                if not DRY_RUN:
                    os.makedirs(os.path.dirname(destino), exist_ok=True)
                    shutil.move(d.ruta_archivo, destino)
                    d.ruta_archivo = destino
                movidos += 1
            elif os.path.isfile(destino):
                print(f"YA EN DESTINO (solo actualizo fila)  {destino}")
                if not DRY_RUN:
                    d.ruta_archivo = destino
                actualizados += 1
            else:
                print(f"FALTA EN DISCO (quedara para re-descarga)  clave={d.clave_logica} causa={d.causa_id}")
                if not DRY_RUN:
                    d.ruta_archivo = destino
                faltantes += 1

        if not DRY_RUN:
            session.commit()

    print(
        f"\nResumen: {ok} ya en layout nuevo, {movidos} movidos, {actualizados} solo-fila, "
        f"{faltantes} faltantes (re-descarga)."
        + ("  [DRY RUN, nada se escribio]" if DRY_RUN else "")
    )


if __name__ == "__main__":
    main()
