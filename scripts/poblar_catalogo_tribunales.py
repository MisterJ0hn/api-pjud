"""Puebla tribunales_catalogo recorriendo, corte por corte, el combo real de
tribunales del sitio del PJUD con un navegador (no hay endpoint publico que
devuelva esta lista completa). Es una operacion administrativa puntual: se corre
a mano cuando hace falta (primera carga, o refrescar si el PJUD agrega/cambia
tribunales), no es parte del flujo normal de sincronizacion.

IMPORTANTE: usa la misma sesion de Chromium (headed) que el worker -- si el
worker esta activo al mismo tiempo, hay dos navegadores distintos golpeando el
sitio del PJUD en paralelo, lo que aumenta el riesgo de que el sitio bloquee la
IP (ya paso con un WAF real en produccion). Conviene parar el worker mientras
corre esto:

    docker compose stop worker
    docker compose run --rm worker python scripts/poblar_catalogo_tribunales.py
    docker compose start worker

Uso (en local, sin Docker):
    python scripts/poblar_catalogo_tribunales.py [civil laboral cobranza]
"""

import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.db.models.tribunales import TribunalCatalogo
from api.db.session_sync import session_scope
from scraper.pjud_client import COMPETENCIAS, PjudSession


def poblar(competencias: list[str]) -> None:
    sesion = PjudSession(headless=False)
    try:
        cortes = sesion.get_cortes()
        for competencia in competencias:
            print(f"=== competencia={competencia} ===")
            for corte in cortes:
                corte_id = int(corte["value"])
                corte_nombre = corte["label"]
                tribunales = sesion.get_tribunales(competencia, corte["value"])
                print(f"  corte {corte_id} ({corte_nombre}): {len(tribunales)} tribunales")

                with session_scope() as session:
                    for t in tribunales:
                        tribunal_id = int(t["value"])
                        tribunal_nombre = t["label"]
                        fila = session.execute(
                            select(TribunalCatalogo).where(
                                TribunalCatalogo.competencia == competencia,
                                TribunalCatalogo.corte_id == corte_id,
                                TribunalCatalogo.tribunal_id == tribunal_id,
                            )
                        ).scalar_one_or_none()
                        if fila is None:
                            session.add(
                                TribunalCatalogo(
                                    competencia=competencia,
                                    corte_id=corte_id,
                                    corte_nombre=corte_nombre,
                                    tribunal_id=tribunal_id,
                                    tribunal_nombre=tribunal_nombre,
                                )
                            )
                        else:
                            fila.corte_nombre = corte_nombre
                            fila.tribunal_nombre = tribunal_nombre
    finally:
        sesion.close()


if __name__ == "__main__":
    competencias = sys.argv[1:] or list(COMPETENCIAS.keys())
    poblar(competencias)
    print("Listo.")
