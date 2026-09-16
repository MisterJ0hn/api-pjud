"""Diagnostico puntual: imprime SOLO los headers de la pestana "Piezas Exhorto" tal
como los devuelve la vista privada (Mis Causas), para compararlos con los de la
Consulta Unificada publica. No imprime datos de la causa, solo nombres de columna.
No escribe nada en la base.

Uso:
    python scripts/diag_headers_piezas.py --tipo E --rol 1798 --anio 2026 \
        --rut TU_RUT --clave TU_CLAVE --metodo 1
"""

import argparse
import asyncio

from scraper.pjud_client_async import PjudSessionPrivada


async def _run(args) -> None:
    sesion = PjudSessionPrivada(args.rut, args.clave, args.metodo, headless=False)
    await sesion.iniciar()
    try:
        r = await sesion.buscar_y_extraer_privada(args.tipo, args.rol, args.anio)
        if not r.get("encontrada"):
            print("Causa NO encontrada:", r)
            return
        for c in r.get("cuadernos", []):
            for nombre, sec in c.get("secciones", {}).items():
                if nombre.strip().lower().startswith("piezas exhorto"):
                    print(f"cuaderno {c['numero']} / {nombre} -> headers:")
                    for h in sec.get("headers", []):
                        print(f"  {h!r}")
    finally:
        await sesion.cerrar()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tipo", required=True)
    p.add_argument("--rol", type=int, required=True)
    p.add_argument("--anio", type=int, required=True)
    p.add_argument("--rut", required=True)
    p.add_argument("--clave", required=True)
    p.add_argument("--metodo", type=int, choices=(1, 2), default=1)
    args = p.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
