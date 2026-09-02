"""Diagnostico: abre una causa en PJUD y, por cada enlace de documento, muestra QUE
devuelve PJUD al descargarlo (status, content-type, tamano, primeros bytes). Sirve
para distinguir 'el tramite no tiene documento' de 'PJUD nos esta bloqueando / la
sesion expiro / hay que abrirlo de otra forma'.

NO escribe nada en la base ni en disco.

Uso (causa publica):
    docker compose exec worker python -m scripts.diagnostico_descarga_docs \\
        --competencia civil --corte 90 --tribunal 276 --tipo C --rol 5656 --anio 2021

Uso (causa privada):
    docker compose exec worker python -m scripts.diagnostico_descarga_docs \\
        --tipo C --rol 5656 --anio 2021 --rut 12345678-9 --clave MICLAVE --metodo 1

    --metodo 1 = Clave Poder Judicial, 2 = Clave Unica.
"""

import argparse
import asyncio

from api.config import settings
from scraper.pjud_client_async import PjudSessionAsync, PjudSessionPrivada


def _recolectar_urls(resultado: dict) -> list[tuple[str, str]]:
    """(etiqueta, url) de todos los documentos del detalle."""
    urls: list[tuple[str, str]] = []
    for d in resultado.get("cabecera", {}).get("descargas", []):
        urls.append((f"cabecera/{d.get('label')}", d["url"]))
    for sub_nombre, sub in resultado.get("cabecera", {}).get("submodales", {}).items():
        for fila in sub.get("filas", []):
            for col, lista in (fila.get("enlaces") or {}).items():
                for u in lista:
                    urls.append((f"submodal:{sub_nombre}/{col}", u))
    for c in resultado.get("cuadernos", []):
        for sec_nombre, sec in c.get("secciones", {}).items():
            for fila in sec.get("filas", []):
                for col, lista in (fila.get("enlaces") or {}).items():
                    for u in lista:
                        urls.append((f"cuad{c['numero']}/{sec_nombre}/{col}", u))
                for i, a in enumerate(fila.get("anexos_popup") or [], start=1):
                    if a.get("doc"):
                        urls.append((f"cuad{c['numero']}/{sec_nombre}/anexo_popup{i}", a["doc"]))
    return urls


async def _probar_una_url(sesion, url: str) -> None:
    from scraper.pjud_client_async import _jwt_expirado

    vencido, restante = _jwt_expirado(url)
    if restante is not None:
        estado = f"VENCIDO hace {-restante}s" if vencido else f"vence en {restante}s"
        print(f"token JWT de la URL: {estado}")
    page = sesion._page  # noqa: SLF001
    try:
        resp = await sesion._context.request.get(url, headers={"Referer": page.url})
        body = await resp.body()
        ct = resp.headers.get("content-type")
        print(f"request -> HTTP {resp.status}  ct={ct!r}  {len(body)} bytes")
        if not ct or "pdf" not in ct.lower():
            print("--- cuerpo (no es PDF) ---")
            print(body[:4000].decode("utf-8", "replace"))
            print("--- fin cuerpo ---")
        else:
            print(f"inicio={body[:40]!r}")
    except Exception as e:  # noqa: BLE001
        print(f"request -> EXCEPCION {e}")
    res = await sesion.descargar_bytes(url)
    print(f"descargar_bytes -> {'None (descartado)' if res is None else f'OK {res[0]!r} {len(res[1])} bytes'}")


async def _run(args) -> None:
    # Igual que el worker: PJUD bloquea el navegador headless, se corre "headed" contra
    # el Xvfb :99 que ya levanto el proceso principal del contenedor.
    headless = settings.playwright_headless
    if args.rut:
        sesion = PjudSessionPrivada(args.rut, args.clave, args.metodo, headless=headless)
        await sesion.iniciar()
    else:
        sesion = PjudSessionAsync(headless=headless)
        await sesion.iniciar()

    if args.url:
        try:
            await _probar_una_url(sesion, args.url)
        finally:
            await sesion.cerrar()
        return

    if args.rut:
        resultado = await sesion.buscar_y_extraer_privada(args.tipo, args.rol, args.anio)
    else:
        resultado = await sesion.buscar_y_extraer(
            args.competencia, str(args.corte), str(args.tribunal), args.tipo, args.rol, args.anio
        )

    try:
        if not resultado.get("encontrada"):
            print("Causa NO encontrada:", resultado)
            return
        if resultado.get("error"):
            print("Error al extraer:", resultado["error"])
            return

        urls = _recolectar_urls(resultado)
        print(f"\n{len(urls)} enlaces de documento encontrados.\n" + "=" * 70)

        page = sesion._page  # noqa: SLF001 - diagnostico
        for etiqueta, url in urls:
            print(f"\n[{etiqueta}]\n  {url}")
            # request "pelado" para ver el status/tipo real
            try:
                resp = await sesion._context.request.get(url, headers={"Referer": page.url})
                body = await resp.body()
                print(f"  request  -> HTTP {resp.status}  ct={resp.headers.get('content-type')!r}  "
                      f"{len(body)} bytes  inicio={body[:40]!r}")
            except Exception as e:  # noqa: BLE001
                print(f"  request  -> EXCEPCION {e}")
            # el metodo real que usa el worker (fetch en la pagina + validacion)
            res = await sesion.descargar_bytes(url)
            if res is None:
                print("  descargar_bytes -> None (se descarta; ver WARNING en el log de arriba)")
            else:
                ct, cuerpo = res
                print(f"  descargar_bytes -> OK  ct={ct!r}  {len(cuerpo)} bytes")
    finally:
        await sesion.cerrar()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--competencia", default="civil")
    p.add_argument("--corte", type=int)
    p.add_argument("--tribunal", type=int)
    p.add_argument("--tipo")
    p.add_argument("--rol", type=int)
    p.add_argument("--anio", type=int)
    p.add_argument("--rut")
    p.add_argument("--clave")
    p.add_argument("--metodo", type=int, choices=(1, 2), default=1)
    p.add_argument("--url", help="probar SOLO esta URL de documento (solo login + descarga)")
    args = p.parse_args()
    if not args.url:
        if not (args.tipo and args.rol and args.anio):
            p.error("--tipo/--rol/--anio son obligatorios (salvo que uses --url)")
        if not args.rut and (args.corte is None or args.tribunal is None):
            p.error("causa publica: --corte y --tribunal obligatorios (o --rut/--clave para modo privado)")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
