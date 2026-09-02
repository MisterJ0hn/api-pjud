"""Estado de los documentos de una causa: cuantos Documento hay registrados, cuales
tienen su archivo en disco, y cuantas filas de movimiento quedaron sin documento
vinculado (descargas que no ocurrieron).

No toca nada. Uso:
    docker compose exec worker python -m scripts.diagnostico_docs_causa --rol 2452 --anio 2022
"""

import argparse
import os

from sqlalchemy import create_engine, text

from api.config import settings

_TABLAS = {
    "movimientos_historia_docs":
        "movimiento_id IN (SELECT mh.id FROM movimientos_historia mh "
        "JOIN cuadernos cu ON cu.id = mh.cuaderno_id WHERE cu.causa_id = :cid)",
    "movimientos_historia_anexos":
        "movimiento_id IN (SELECT mh.id FROM movimientos_historia mh "
        "JOIN cuadernos cu ON cu.id = mh.cuaderno_id WHERE cu.causa_id = :cid)",
    "escritos_resolver":
        "cuaderno_id IN (SELECT id FROM cuadernos WHERE causa_id = :cid)",
    "exhortos_rol_destino_items":
        "rol_destino_id IN (SELECT rd.id FROM exhortos_rol_destino rd "
        "JOIN exhortos ex ON ex.id = rd.exhorto_id "
        "JOIN cuadernos cu ON cu.id = ex.cuaderno_id WHERE cu.causa_id = :cid)",
    "anexos_causa": "causa_id = :cid",
}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rol", type=int, required=True)
    p.add_argument("--anio", type=int, required=True)
    p.add_argument("--tribunal", type=int, help="si la RIT existe en varios tribunales")
    args = p.parse_args()

    engine = create_engine(settings.database_url_sync)
    with engine.connect() as c:
        q = "SELECT id, tribunal_nombre FROM causas WHERE rol = :rol AND anio = :anio"
        params = {"rol": args.rol, "anio": args.anio}
        if args.tribunal is not None:
            q += " AND tribunal = :trib"
            params["trib"] = args.tribunal
        causas = c.execute(text(q), params).all()
        if not causas:
            print("no hay causa con ese rol/anio")
            return
        if len(causas) > 1:
            print("varias causas; pasa --tribunal:", [(str(i), t) for i, t in causas])
            return
        cid, trib = causas[0]
        print(f"causa {cid}  ({trib})\n")

        docs = c.execute(text(
            "SELECT clave_logica, categoria, ruta_archivo FROM documentos "
            "WHERE causa_id = :cid ORDER BY categoria, clave_logica"
        ), {"cid": cid}).all()
        faltan = 0
        print(f"=== {len(docs)} Documento(s) registrados ===")
        for clave, cat, ruta in docs:
            ok = bool(ruta) and os.path.isfile(ruta)
            faltan += not ok
            print(f"  {'OK   ' if ok else 'FALTA'}  [{cat}] {clave}")
            if not ok:
                print(f"           {ruta}")
        print(f"\n  -> {faltan} archivo(s) faltante(s) en disco de {len(docs)} registrados")

        print("\n=== filas de movimiento SIN documento vinculado ===")
        for tabla, cond in _TABLAS.items():
            tot = c.execute(text(f"SELECT count(*) FROM {tabla} WHERE {cond}"), {"cid": cid}).scalar()
            nul = c.execute(
                text(f"SELECT count(*) FROM {tabla} WHERE {cond} AND documento_id IS NULL"),
                {"cid": cid},
            ).scalar()
            marca = "  <-- descargas que no ocurrieron" if nul else ""
            print(f"  {tabla}: {nul}/{tot} sin documento{marca}")


if __name__ == "__main__":
    main()
