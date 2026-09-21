"""Sincronizacion incremental de una causa Laboral. Analogo a `worker/sync_familia.py`
(cuaderno unico, misma forma de Movimientos) pero:

- Laboral admite modo PUBLICO (Consulta Unificada) o PRIVADO (rut/clave/metodo_login),
  igual que `worker/sync_civil.py` -- no siempre privada como Familia.
- Secciones del modal: Movimientos, Litigantes, Notificaciones, Diligencias,
  Liquidacion, Materias, Escritos Pendientes (no hay Plazos).
- Escritos Pendientes es un listado transiente (PJUD saca la fila una vez resuelta):
  se sincroniza con delete-si-desaparecio, igual que "Escritos por Resolver" de Civil,
  no con reemplazo completo.
- Cabecera: Texto Demanda y "Listado de Archivos de Audios de Audiencia" son popups
  con TABLA (varias filas), a diferencia de civil (Texto Demanda = documento unico).

Politica de persistencia (igual que familia):
- Movimientos: clave natural (causa, folio, ocurrencia) -> INSERT/UPDATE; filas sin
  folio o de exhorto ("[NE]") -> borrar + reinsertar. Descargas idempotentes por
  `clave_logica`.
- Litigantes / Notificaciones / Materias / Liquidacion: reemplazo completo por causa en
  cada sync (tablas chicas; `contenido_hash` deduplica filas repetidas por PJUD).
"""

import asyncio
import logging
import os
import re
import shutil

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.laboral import (
    AudioLaboral,
    CausaLaboral,
    DiligenciaLaboral,
    DocumentoLaboral,
    EscritoPendienteLaboral,
    LiquidacionLaboral,
    LitiganteLaboral,
    MateriaLaboral,
    MovimientoLaboral,
    MovimientoLaboralAnexo,
    MovimientoLaboralDoc,
    MovimientoLaboralGeoImagen,
    NotificacionLaboral,
    TextoDemandaLaboral,
)
from api.db.models.tribunales import TribunalCatalogo
from scraper.pjud_client_async import CausaNoEncontrada, PjudSessionLaboralAsync, PjudSessionLaboralPrivada
from worker.idempotencia import extension_por_content_type, hash_fila, ruta_documento, slug
from worker.sync_civil import _archivo_en_disco, _normalizar, _parsear_folio, _parsear_target

logger = logging.getLogger("pjud.worker.sync_laboral")

CATEGORIAS_CABECERA = {
    "certificado de envio": "certificado_envio",
    "certificado envio": "certificado_envio",
    "ebook": "ebook",
}

# Pausa entre descargas sucesivas de audio (ver comentario en el bucle de audios): el
# WAF de `/audio/audioByPass.php` rechaza todo si se piden muchos archivos seguidos sin
# pausa. No aplica al resto de descargas (PDFs), que no mostraron este problema.
PAUSA_ENTRE_AUDIOS_S = 2.5


def _campo(campos: dict, *claves: str) -> str | None:
    for k in claves:
        v = campos.get(k)
        if v:
            return v
    return None


def _es_seccion(nombre: str, *prefijos: str) -> bool:
    n = _normalizar(nombre)
    return any(n.startswith(p) for p in prefijos)


_RE_ARCHIVO_AUDIO = re.compile(r"\.(mp3|wav|wma|m4a|ogg|aac|flac|opus|amr|3gp)\b", re.IGNORECASE)
# Confirmado en vivo (2026-09-17, causa O-692-2019): PJUD usa "-" como separador en
# este popup ("27-03-2020"), no "/" como en el resto del sitio.
_RE_FECHA = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$")


def _fila_audio_fecha_referencia(v: dict) -> tuple[str | None, str | None]:
    """(fecha, referencia) de una fila del popup "Listado de Archivos de Audios de
    Audiencia". CONFIRMADO en vivo (2026-09-17/18, causa O-692-2019): las columnas
    reales son Nro/Descargar/Audio/Fecha pero vienen SWAPEADAS -- "Audio" trae la fecha
    como texto y "Fecha" trae el nombre de archivo. Se detecta primero por forma
    (nombre de archivo de audio / fecha dd/mm/aaaa) en vez de confiar en el nombre de
    columna.

    Bug real (2026-09-21): cuando el nombre de archivo NO trae una extension
    reconocida por `_RE_ARCHIVO_AUDIO`, la deteccion por forma no encuentra
    `referencia` y el fallback anterior usaba `_campo(v, "Fecha")` para `fecha` --
    como esa celda en realidad es el nombre de archivo, terminaba quedando en `fecha`
    y `referencia` en null. El fallback ahora usa el swap ya confirmado (columna
    "Fecha" -> referencia, columna "Audio" -> fecha) en vez del nombre de columna
    literal."""
    referencia = fecha = None
    for texto in v.values():
        t = (texto or "").strip()
        if not t:
            continue
        if referencia is None and _RE_ARCHIVO_AUDIO.search(t):
            referencia = t
        elif fecha is None and _RE_FECHA.match(t):
            fecha = t
    if referencia is None:
        candidato = _campo(v, "Fecha", "Referencia", "Nombre", "Archivo")
        referencia = candidato if candidato != fecha else None
    if fecha is None:
        candidato = _campo(v, "Audio", "Fecha")
        # No caer de vuelta en el mismo valor ya clasificado como `referencia`.
        fecha = candidato if candidato != referencia else None
    return fecha, referencia


# --- Descarga de documentos (idempotente por clave_logica) --------------------


async def _descargar_a_disco(sesion_pjud, url: str, causa_id, clave_logica: str, post: dict | None = None) -> str | None:
    if post:
        resultado = await sesion_pjud.descargar_post_bytes(post["url"], post["field"], post["value"])
    else:
        resultado = await sesion_pjud.descargar_bytes(url)
    if resultado is None:
        return None
    content_type, cuerpo = resultado
    ruta = ruta_documento(causa_id, clave_logica, None, extension_por_content_type(content_type))
    with open(ruta, "wb") as f:
        f.write(cuerpo)
    return ruta


async def _obtener_o_descargar_doc(
    session: AsyncSession,
    sesion_pjud,
    causa_id,
    categoria: str,
    clave_logica: str,
    url: str | None = None,
    referencia: str | None = None,
    hash_padre: str | None = None,
    post: dict | None = None,
    forzar: bool = False,
) -> DocumentoLaboral | None:
    """`forzar=True` (ebook: PJUD lo regenera completo cada vez que se agrega un
    documento nuevo a la causa) se salta la idempotencia por clave_logica y siempre
    vuelve a pedirlo a PJUD."""
    existente = (
        await session.execute(
            select(DocumentoLaboral).where(
                DocumentoLaboral.causa_laboral_id == causa_id,
                DocumentoLaboral.clave_logica == clave_logica,
            )
        )
    ).scalar_one_or_none()
    if existente is not None:
        if not forzar and _archivo_en_disco(existente.ruta_archivo):
            return existente
        if not forzar:
            logger.warning("Documento '%s' registrado sin archivo en disco; se re-descarga", clave_logica)
        ruta = await _descargar_a_disco(sesion_pjud, url, causa_id, clave_logica, post)
        if ruta is None:
            return existente
        existente.ruta_archivo = ruta
        await session.flush()
        return existente

    ruta = await _descargar_a_disco(sesion_pjud, url, causa_id, clave_logica, post)
    if ruta is None:
        return None

    documento = DocumentoLaboral(
        causa_laboral_id=causa_id,
        categoria=categoria,
        clave_logica=clave_logica,
        nombre_archivo=clave_logica,
        ruta_archivo=ruta,
        hash_contenido_fila_padre=hash_padre,
        referencia_origen=referencia,
    )
    session.add(documento)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return (
            await session.execute(
                select(DocumentoLaboral).where(
                    DocumentoLaboral.causa_laboral_id == causa_id,
                    DocumentoLaboral.clave_logica == clave_logica,
                )
            )
        ).scalar_one_or_none()
    return documento


async def _documento_en_disco(session: AsyncSession, documento_id) -> bool:
    if documento_id is None:
        return False
    ruta = (
        await session.execute(select(DocumentoLaboral.ruta_archivo).where(DocumentoLaboral.id == documento_id))
    ).scalar_one_or_none()
    return _archivo_en_disco(ruta)


async def _registrar_documento_desde_ruta_temporal(
    session: AsyncSession,
    causa_id,
    categoria: str,
    clave_logica: str,
    ruta_temporal: str | None,
    nombre_sugerido: str | None = None,
    referencia: str | None = None,
    hash_padre: str | None = None,
) -> DocumentoLaboral | None:
    """Como `_obtener_o_descargar_doc`, pero para archivos que Playwright ya bajo a un
    temporal via un click real (ver `descarga_click` / `MODALES_DESCARGA_CLICK` en el
    scraper) en vez de pedirlos por fetch/HTTP: copia el temporal a la ubicacion
    idempotente de siempre y registra/actualiza el `DocumentoLaboral`. No re-verifica
    idempotencia por si sola (el llamador ya decide si hace falta descargar)."""
    if not ruta_temporal or not os.path.isfile(ruta_temporal):
        logger.warning("Descarga por click de '%s': sin archivo temporal valido", clave_logica)
        return None
    # `nombre_sugerido` (Playwright `Download.suggested_filename`) vino vacio/sin
    # extension en vivo (PJUD no manda Content-Disposition con nombre y la URL de
    # descarga tampoco trae extension) -- `referencia` (el nombre de archivo real que
    # ya detectamos en la fila, p. ej. "...fecha de juicio.mp3") es mas confiable para
    # esto y se prueba primero. Ultimo fallback ".mp3": unico tipo de archivo conocido
    # que usa esta descarga por click hasta ahora (audio de audiencia de Laboral).
    ext = ""
    for candidato in (referencia, nombre_sugerido):
        if candidato:
            _, ext_candidata = os.path.splitext(candidato)
            if ext_candidata:
                ext = ext_candidata
                break
    ext = ext or ".mp3"

    existente = (
        await session.execute(
            select(DocumentoLaboral).where(
                DocumentoLaboral.causa_laboral_id == causa_id,
                DocumentoLaboral.clave_logica == clave_logica,
            )
        )
    ).scalar_one_or_none()
    destino = ruta_documento(causa_id, clave_logica, None, ext)
    shutil.copyfile(ruta_temporal, destino)

    if existente is not None:
        existente.ruta_archivo = destino
        await session.flush()
        return existente

    documento = DocumentoLaboral(
        causa_laboral_id=causa_id,
        categoria=categoria,
        clave_logica=clave_logica,
        nombre_archivo=clave_logica,
        ruta_archivo=destino,
        hash_contenido_fila_padre=hash_padre,
        referencia_origen=referencia,
    )
    session.add(documento)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return (
            await session.execute(
                select(DocumentoLaboral).where(
                    DocumentoLaboral.causa_laboral_id == causa_id,
                    DocumentoLaboral.clave_logica == clave_logica,
                )
            )
        ).scalar_one_or_none()
    return documento


# --- Movimientos ---------------------------------------------------------------


def _anexo_campos(a: dict) -> tuple[str | None, str | None]:
    """(fecha, referencia) de una fila del popup de anexo (`modalAnexoEscritoLaboral` /
    `modalAnexoEscritoPend`). A diferencia de Familia, "Solicitud Laboral.md" define el
    anexo de Laboral solo con doc/fecha/referencia (sin folio ni observación) -- se
    sigue el contrato literal, no se armoniza con Familia."""
    v = a.get("valores") or {}
    return (
        _campo(v, "Fecha"),
        _campo(v, "Referencia", "Nombre Documento", "Nombre del Documento"),
    )


def _asignar_campos_movimiento(mov: MovimientoLaboral, valores: dict) -> None:
    mov.etapa = _campo(valores, "Etapa")
    mov.estado = _campo(valores, "Estado")
    mov.tramite = _campo(valores, "Trámite", "Tramite")
    mov.descripcion_tramite = _campo(valores, "Desc. Trámite", "Desc. Tramite", "Descripción Trámite")
    mov.fecha_tramite = _campo(valores, "Fec. Trámite", "Fecha Trámite", "Fec. Tramite")


async def _persistir_docs_anexos_movimiento(
    session: AsyncSession,
    sesion_pjud,
    causa: CausaLaboral,
    mov: MovimientoLaboral,
    fila: dict,
    enlaces: dict,
    clave_base: str,
    h: str,
) -> None:
    doc_urls = enlaces.get("Doc.") or []
    if doc_urls:
        await session.execute(delete(MovimientoLaboralDoc).where(MovimientoLaboralDoc.movimiento_id == mov.id))
        for i, url in enumerate(doc_urls, start=1):
            clave = clave_base if i == 1 else f"{clave_base}_doc{i}"
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "movimiento", clave, url, hash_padre=h
            )
            session.add(MovimientoLaboralDoc(movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i))

    # Columna "Anexos": carpeta-popup (`modalAnexoEscritoLaboral`, ya volcada por el
    # scraper en `fila["anexos_popup"]`) o enlaces directos.
    anexos_popup = fila.get("anexos_popup") or []
    anexo_urls = enlaces.get("Anexos") or enlaces.get("Anexo") or []
    if anexos_popup:
        await session.execute(
            delete(MovimientoLaboralAnexo).where(MovimientoLaboralAnexo.movimiento_id == mov.id)
        )
        for i, a in enumerate(anexos_popup, start=1):
            fecha_a, referencia_a = _anexo_campos(a)
            doc = None
            if a.get("doc") or a.get("doc_post"):
                doc = await _obtener_o_descargar_doc(
                    session, sesion_pjud, causa.id, "movimiento_anexo", f"{clave_base}_anexo{i}",
                    url=a.get("doc"), post=a.get("doc_post"), referencia=referencia_a, hash_padre=h,
                )
            session.add(
                MovimientoLaboralAnexo(
                    movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i,
                    fecha=fecha_a, referencia=referencia_a,
                )
            )
    elif anexo_urls:
        await session.execute(
            delete(MovimientoLaboralAnexo).where(MovimientoLaboralAnexo.movimiento_id == mov.id)
        )
        for i, url in enumerate(anexo_urls, start=1):
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "movimiento_anexo", f"{clave_base}_anexo{i}", url, hash_padre=h
            )
            session.add(MovimientoLaboralAnexo(movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i))


async def _persistir_georeferencia_movimiento(
    session: AsyncSession, sesion_pjud, causa: CausaLaboral, mov: MovimientoLaboral, fila: dict, clave_base: str, h: str
) -> None:
    datos = fila.get("georeferencia_popup")
    if datos is None:
        return
    mapa = datos.get("mapa") or {}
    mov.geo_latitud = mapa.get("latitud")
    mov.geo_longitud = mapa.get("longitud")
    mov.geo_corrector = mapa.get("corrector")

    imagenes = datos.get("imagenes") or []
    await session.execute(
        delete(MovimientoLaboralGeoImagen).where(MovimientoLaboralGeoImagen.movimiento_id == mov.id)
    )
    for i, img in enumerate(imagenes, start=1):
        doc = await _obtener_o_descargar_doc(
            session, sesion_pjud, causa.id, "movimiento_georef_imagen", f"{clave_base}_geo_img{i}",
            url=img.get("src"), referencia=img.get("alt"), hash_padre=h,
        )
        session.add(
            MovimientoLaboralGeoImagen(movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i)
        )


async def _sincronizar_movimientos(
    session: AsyncSession, sesion_pjud, causa: CausaLaboral, tabla: dict
) -> bool:
    filas = tabla.get("filas", [])

    previas = sorted(
        tuple(r)
        for r in (
            await session.execute(
                select(MovimientoLaboral.folio_texto, MovimientoLaboral.hash_contenido).where(
                    MovimientoLaboral.causa_laboral_id == causa.id,
                    MovimientoLaboral.folio_texto.like("[%"),
                )
            )
        ).all()
    )
    await session.execute(
        delete(MovimientoLaboral).where(
            MovimientoLaboral.causa_laboral_id == causa.id,
            MovimientoLaboral.folio_texto.like("[%"),
        )
    )
    await session.commit()

    hubo_cambios = False
    nuevas_sin_clave: list[tuple[str, str]] = []
    ultimo_folio_normal: int | None = None
    exh_ocurrencias: dict[str, int] = {}
    folio_ocurrencias: dict[int, int] = {}

    for idx, fila in enumerate(filas):
        valores = fila["valores"]
        enlaces = fila.get("enlaces", {})
        folio_parseado = _parsear_folio(valores.get("Folio") or "")
        if folio_parseado is None:
            logger.warning("Folio de movimiento con formato inesperado %r; se omite", valores.get("Folio"))
            continue
        folio_texto, folio, sin_clave_natural = folio_parseado
        h = hash_fila(valores)

        if sin_clave_natural:
            nuevas_sin_clave.append((folio_texto, h))
            ancla = ultimo_folio_normal if ultimo_folio_normal is not None else 0
            clave_base = f"movimiento_sf{ancla}" if folio is None else f"movimiento_exh{ancla}_{folio}"
            exh_ocurrencias[clave_base] = exh_ocurrencias.get(clave_base, 0) + 1
            if exh_ocurrencias[clave_base] > 1:
                clave_base = f"{clave_base}_o{exh_ocurrencias[clave_base]}"
            mov = MovimientoLaboral(
                causa_laboral_id=causa.id, folio=folio, folio_texto=folio_texto, hash_contenido=h, orden=idx,
            )
            _asignar_campos_movimiento(mov, valores)
            session.add(mov)
            await session.flush()
            await _persistir_docs_anexos_movimiento(session, sesion_pjud, causa, mov, fila, enlaces, clave_base, h)
            await _persistir_georeferencia_movimiento(session, sesion_pjud, causa, mov, fila, clave_base, h)
            await session.commit()
            continue

        ultimo_folio_normal = folio
        folio_ocurrencias[folio] = folio_ocurrencias.get(folio, 0) + 1
        ocurrencia = folio_ocurrencias[folio]
        clave_docs = f"movimiento_folio{folio}"
        if ocurrencia > 1:
            clave_docs = f"{clave_docs}_o{ocurrencia}"

        existente = (
            await session.execute(
                select(MovimientoLaboral).where(
                    MovimientoLaboral.causa_laboral_id == causa.id,
                    MovimientoLaboral.folio_texto == folio_texto,
                    MovimientoLaboral.ocurrencia == ocurrencia,
                )
            )
        ).scalar_one_or_none()

        if existente is not None and existente.hash_contenido == h:
            if existente.orden != idx:
                existente.orden = idx
                await session.commit()
            continue

        hubo_cambios = True
        if existente is None:
            existente = MovimientoLaboral(
                causa_laboral_id=causa.id, folio=folio, folio_texto=folio_texto, hash_contenido=h,
                orden=idx, ocurrencia=ocurrencia,
            )
            session.add(existente)
            await session.flush()

        existente.orden = idx
        _asignar_campos_movimiento(existente, valores)
        existente.hash_contenido = h
        await session.flush()
        await _persistir_docs_anexos_movimiento(session, sesion_pjud, causa, existente, fila, enlaces, clave_docs, h)
        await _persistir_georeferencia_movimiento(session, sesion_pjud, causa, existente, fila, clave_docs, h)
        await session.commit()

    if sorted(nuevas_sin_clave) != previas:
        hubo_cambios = True
    return hubo_cambios


# --- Secciones de reemplazo completo -------------------------------------------


async def _reemplazar_litigantes(session: AsyncSession, causa: CausaLaboral, tabla: dict) -> None:
    await session.execute(delete(LitiganteLaboral).where(LitiganteLaboral.causa_laboral_id == causa.id))
    vistos: set[str] = set()
    for fila in tabla.get("filas", []):
        v = fila["valores"]
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        # "Est." es un icono sin texto (fa-check=1 / fa-minus=0) -- ver `iconos` en
        # `JS_EXTRAER_FILAS_CON_ENLACES`, `valores["Est."]` siempre viene vacio.
        icono_estado = (fila.get("iconos") or {}).get("Est.")
        session.add(
            LitiganteLaboral(
                causa_laboral_id=causa.id,
                estado=None if icono_estado is None else int(icono_estado),
                defensor=_campo(v, "Abog. Defensor", "Defensor"),
                sujeto=_campo(v, "Sujeto", "Participante"),
                rut=_campo(v, "Rut", "RUT"),
                persona=_campo(v, "Persona"),
                razon_social=_campo(v, "Nombre o Razón Social", "Nombre", "Razón Social"),
            )
        )
    await session.commit()


async def _reemplazar_notificaciones(session: AsyncSession, causa: CausaLaboral, tabla: dict) -> None:
    await session.execute(delete(NotificacionLaboral).where(NotificacionLaboral.causa_laboral_id == causa.id))
    vistos: set[str] = set()
    for fila in tabla.get("filas", []):
        v = fila["valores"]
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        session.add(
            NotificacionLaboral(
                causa_laboral_id=causa.id,
                estado_notificacion=_campo(v, "Estado Notif."),
                fecha_tramite=_campo(v, "Fecha Trámite", "Fec. Trámite"),
                tipo_parte=_campo(v, "Tipo Parte", "Tipo Part."),
                nombre=_campo(v, "Nombre"),
                tramite=_campo(v, "Trámite", "Tramite"),
                observacion_fallida=_campo(v, "Obs. Fallida", "Observación Fallida"),
                contenido_hash=h,
            )
        )
    await session.commit()


async def _reemplazar_materias(session: AsyncSession, causa: CausaLaboral, tabla: dict) -> None:
    await session.execute(delete(MateriaLaboral).where(MateriaLaboral.causa_laboral_id == causa.id))
    vistos: set[str] = set()
    for fila in tabla.get("filas", []):
        v = fila["valores"]
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        session.add(
            MateriaLaboral(
                causa_laboral_id=causa.id,
                codigo=_campo(v, "Código", "Codigo"),
                glosa_materia=_campo(v, "Glosa de Materia", "Materia", "Glosa Materia"),
                estado=_campo(v, "Estado"),
                fecha_termino=_campo(v, "Fecha Término", "Fecha Termino", "Fec. Término"),
                contenido_hash=h,
            )
        )
    await session.commit()


async def _reemplazar_liquidacion(session: AsyncSession, causa: CausaLaboral, tabla: dict) -> None:
    """Best-effort: la tabla "Liquidación" no se vio con datos en ningun ejemplo
    disponible -- la primera columna se guarda como texto plano hasta confirmar contra
    una causa real si es un icono de estado o un documento descargable."""
    await session.execute(delete(LiquidacionLaboral).where(LiquidacionLaboral.causa_laboral_id == causa.id))
    vistos: set[str] = set()
    for fila in tabla.get("filas", []):
        v = fila["valores"]
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        session.add(
            LiquidacionLaboral(
                causa_laboral_id=causa.id,
                liquidacion=_campo(v, "Liquidación", "Liquidacion"),
                rut=_campo(v, "Rut", "RUT"),
                nombre=_campo(v, "Nombre"),
                monto_liquido=_campo(v, "Monto Líquido", "Monto Liquido"),
                contenido_hash=h,
            )
        )
    await session.commit()


async def _reemplazar_diligencias(session: AsyncSession, sesion_pjud, causa: CausaLaboral, tabla: dict) -> bool:
    previos = set(
        (
            await session.execute(
                select(DiligenciaLaboral.contenido_hash).where(DiligenciaLaboral.causa_laboral_id == causa.id)
            )
        ).scalars().all()
    )
    await session.execute(delete(DiligenciaLaboral).where(DiligenciaLaboral.causa_laboral_id == causa.id))
    vistos: set[str] = set()
    for i, fila in enumerate(tabla.get("filas", []), start=1):
        v = fila["valores"]
        enlaces = fila.get("enlaces", {})
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        ida_urls = enlaces.get("Doc. Ida") or []
        vta_urls = enlaces.get("Doc. Vta.") or enlaces.get("Doc. Vta") or []
        doc_ida = doc_vta = None
        if ida_urls:
            doc_ida = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "diligencia", f"diligencia_ida_{i}", ida_urls[0], hash_padre=h
            )
        if vta_urls:
            doc_vta = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "diligencia", f"diligencia_vta_{i}", vta_urls[0], hash_padre=h
            )
        session.add(
            DiligenciaLaboral(
                causa_laboral_id=causa.id,
                doc_ida_id=doc_ida.id if doc_ida else None,
                doc_vta_id=doc_vta.id if doc_vta else None,
                estado_diligencia=_campo(v, "Estado Diligencia", "Estado"),
                rit=_campo(v, "RIT", "Rit"),
                ruc=_campo(v, "RUC", "Ruc"),
                tipo_diligencia=_campo(v, "Tipo Diligencia", "Tipo"),
                referencia=_campo(v, "Referencia"),
                fecha_tramite=_campo(v, "Fecha Trámite", "Fec. Trámite"),
                contenido_hash=h,
            )
        )
    await session.commit()
    return vistos != previos


async def _sincronizar_escritos_pendientes(
    session: AsyncSession, sesion_pjud, causa: CausaLaboral, tabla: dict
) -> bool:
    """Listado transiente (igual que "Escritos por Resolver" de Civil): PJUD saca la
    fila una vez resuelta. `doc`/`anexo` son escalares en el contrato (no listas) --
    se guarda solo el primer enlace de cada columna."""
    hubo_cambios = False
    hashes_vistos: set[str] = set()
    for fila in tabla.get("filas", []):
        valores = fila["valores"]
        enlaces = fila.get("enlaces", {})
        h = hash_fila(valores)
        hashes_vistos.add(h)
        existente = (
            await session.execute(
                select(EscritoPendienteLaboral).where(
                    EscritoPendienteLaboral.causa_laboral_id == causa.id,
                    EscritoPendienteLaboral.contenido_hash == h,
                )
            )
        ).scalar_one_or_none()
        clave = f"escrito_pend_{slug(_campo(valores, 'Referencia'))}_{slug(_campo(valores, 'Solicitante'))}"
        doc_urls = enlaces.get("Doc.") or []
        anexo_urls = enlaces.get("Anexo") or []
        anexos_popup = fila.get("anexos_popup") or []
        if not anexo_urls and anexos_popup:
            primero = anexos_popup[0]
            anexo_urls = [primero["doc"]] if primero.get("doc") else []

        if existente is not None:
            cambiado = False
            if doc_urls and not await _documento_en_disco(session, existente.doc_id):
                doc = await _obtener_o_descargar_doc(
                    session, sesion_pjud, causa.id, "escrito_pendiente", f"{clave}_doc", doc_urls[0], hash_padre=h
                )
                if doc is not None and existente.doc_id != doc.id:
                    existente.doc_id = doc.id
                cambiado = True
            if anexo_urls and not await _documento_en_disco(session, existente.anexo_id):
                anexo = await _obtener_o_descargar_doc(
                    session, sesion_pjud, causa.id, "escrito_pendiente_anexo", f"{clave}_anexo", anexo_urls[0],
                    hash_padre=h,
                )
                if anexo is not None and existente.anexo_id != anexo.id:
                    existente.anexo_id = anexo.id
                cambiado = True
            if cambiado:
                await session.commit()
            continue

        hubo_cambios = True
        doc_id = anexo_id = None
        if doc_urls:
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "escrito_pendiente", f"{clave}_doc", doc_urls[0], hash_padre=h
            )
            doc_id = doc.id if doc else None
        if anexo_urls:
            anexo = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "escrito_pendiente_anexo", f"{clave}_anexo", anexo_urls[0],
                hash_padre=h,
            )
            anexo_id = anexo.id if anexo else None
        session.add(
            EscritoPendienteLaboral(
                causa_laboral_id=causa.id,
                doc_id=doc_id,
                anexo_id=anexo_id,
                fecha_ing=_campo(valores, "Fecha Ing."),
                referencia=_campo(valores, "Referencia"),
                solicitante=_campo(valores, "Solicitante"),
                tipo_ingreso=_campo(valores, "Tipo Ingreso"),
                contenido_hash=h,
            )
        )
        await session.commit()

    condiciones_obsoletos = [EscritoPendienteLaboral.causa_laboral_id == causa.id]
    if hashes_vistos:
        condiciones_obsoletos.append(EscritoPendienteLaboral.contenido_hash.not_in(hashes_vistos))
    ids_obsoletos = (
        await session.execute(select(EscritoPendienteLaboral.id).where(*condiciones_obsoletos))
    ).scalars().all()
    if ids_obsoletos:
        await session.execute(delete(EscritoPendienteLaboral).where(EscritoPendienteLaboral.id.in_(ids_obsoletos)))
        await session.commit()
        hubo_cambios = True
    return hubo_cambios


# --- Orquestacion ----------------------------------------------------------


async def sincronizar_causa_laboral(
    session: AsyncSession,
    sesion_pjud: "PjudSessionLaboralAsync | PjudSessionLaboralPrivada",
    causa: CausaLaboral,
    *,
    privada: bool = False,
    progreso=None,
) -> None:
    async def _rep(texto: str) -> None:
        if progreso is not None:
            await progreso(texto)

    if privada:
        tribunal_esperado = (
            await session.execute(
                select(TribunalCatalogo.tribunal_nombre).where(
                    TribunalCatalogo.competencia == "laboral",
                    TribunalCatalogo.corte_id == causa.corte,
                    TribunalCatalogo.tribunal_id == causa.tribunal,
                )
            )
        ).scalar_one_or_none()
        resultado = await sesion_pjud.buscar_y_extraer_privada(
            causa.tipo, causa.rol, causa.anio, progreso=progreso, tribunal_nombre=tribunal_esperado,
        )
    else:
        resultado = await sesion_pjud.buscar_y_extraer(
            "laboral", str(causa.corte), str(causa.tribunal), causa.tipo, causa.rol, causa.anio, progreso=progreso,
        )

    if not resultado.get("encontrada"):
        raise CausaNoEncontrada(f"Causa {causa.rit} no encontrada en PJUD")
    if resultado.get("error"):
        raise RuntimeError(resultado["error"])

    await _rep("Guardando cabecera")
    cabecera = resultado["cabecera"]
    campos = cabecera.get("campos", {})
    causa.caratula = _campo(campos, "Carátula", "Caratula") or causa.caratula
    causa.ruc = _campo(campos, "RUC", "Ruc") or causa.ruc
    causa.fecha_ingreso = _campo(campos, "F. Ing.", "Fecha Ingreso") or causa.fecha_ingreso
    causa.proceso = _campo(campos, "Proc.", "Proceso") or causa.proceso
    causa.forma_inicio = _campo(campos, "Forma Inicio", "F. Inicio", "Forma de Inicio") or causa.forma_inicio
    causa.est_adm = _campo(campos, "Est. Adm.", "Estado Administrativo") or causa.est_adm
    causa.etapa = _campo(campos, "Etapa") or causa.etapa
    causa.estado_proceso = _campo(campos, "Estado Proc.", "Estado Procesal") or causa.estado_proceso
    causa.tribunal_nombre = _campo(campos, "Tribunal") or causa.tribunal_nombre
    causa.tramites = _campo(campos, "Trámites", "Tramites") or causa.tramites
    await session.commit()

    hubo_cambios = False

    cuadernos = resultado.get("cuadernos") or []
    secciones = cuadernos[0].get("secciones", {}) if cuadernos else {}

    for nombre, tabla in secciones.items():
        if _es_seccion(nombre, "movimiento"):
            await _rep("Guardando movimientos")
            if await _sincronizar_movimientos(session, sesion_pjud, causa, tabla):
                hubo_cambios = True
        elif _es_seccion(nombre, "litigant"):
            await _rep("Guardando litigantes")
            await _reemplazar_litigantes(session, causa, tabla)
        elif _es_seccion(nombre, "notificac"):
            await _rep("Guardando notificaciones")
            await _reemplazar_notificaciones(session, causa, tabla)
        elif _es_seccion(nombre, "diligenc"):
            await _rep("Guardando diligencias")
            if await _reemplazar_diligencias(session, sesion_pjud, causa, tabla):
                hubo_cambios = True
        elif _es_seccion(nombre, "liquidac"):
            await _rep("Guardando liquidacion")
            await _reemplazar_liquidacion(session, causa, tabla)
        elif _es_seccion(nombre, "materia"):
            await _rep("Guardando materias")
            await _reemplazar_materias(session, causa, tabla)
        elif _es_seccion(nombre, "escritos pendientes"):
            await _rep("Guardando escritos pendientes")
            if await _sincronizar_escritos_pendientes(session, sesion_pjud, causa, tabla):
                hubo_cambios = True
        else:
            logger.info("Seccion de Laboral no mapeada, se ignora: %r", nombre)

    # --- Cabecera: Texto Demanda (popup con tabla, a diferencia de civil) --------
    submodales = cabecera.get("submodales", {}) or {}
    texto_demanda_sub = next((v for k, v in submodales.items() if _es_seccion(k, "texto demanda")), None)
    if texto_demanda_sub:
        await _rep("Guardando texto demanda")
        for sub in texto_demanda_sub.get("filas", []):
            v = sub["valores"]
            fecha, referencia = _campo(v, "Fecha"), _campo(v, "Referencia")
            # "Doc. Demanda" es un icono sin texto (fa-check=1 / fa-minus=0) -- ver
            # `iconos` en `JS_EXTRAER_FILAS_CON_ENLACES`.
            icono_doc_demanda = (sub.get("iconos") or {}).get("Doc. Demanda")
            doc_demanda = None if icono_doc_demanda is None else int(icono_doc_demanda)
            target = _parsear_target(sub.get("targets"), "Doc.")
            existente = (
                await session.execute(
                    select(TextoDemandaLaboral).where(
                        TextoDemandaLaboral.causa_laboral_id == causa.id,
                        TextoDemandaLaboral.referencia == referencia,
                        TextoDemandaLaboral.fecha == fecha,
                    )
                )
            ).scalar_one_or_none()
            urls = sub.get("enlaces", {}).get("Doc.") or []
            if existente is not None:
                if urls and not await _documento_en_disco(session, existente.documento_id):
                    doc = await _obtener_o_descargar_doc(
                        session, sesion_pjud, causa.id, "texto_demanda", f"texto_demanda_{slug(referencia)}",
                        urls[0], referencia=referencia,
                    )
                    if doc is not None:
                        existente.documento_id = doc.id
                    await session.commit()
                continue
            hubo_cambios = True
            documento_id = None
            if urls:
                doc = await _obtener_o_descargar_doc(
                    session, sesion_pjud, causa.id, "texto_demanda", f"texto_demanda_{slug(referencia)}",
                    urls[0], referencia=referencia,
                )
                documento_id = doc.id if doc else None
            session.add(
                TextoDemandaLaboral(
                    causa_laboral_id=causa.id, documento_id=documento_id, doc_demanda=doc_demanda,
                    fecha=fecha, referencia=referencia, orden=target or 0,
                )
            )
            await session.commit()

    # --- Cabecera: Listado de Archivos de Audios de Audiencia -------------------
    audio_sub = next((v for k, v in submodales.items() if _es_seccion(k, "listado de archivos de audio")), None)
    if audio_sub:
        await _rep("Guardando audios de audiencia")
        filas_audio = audio_sub.get("filas", [])
        for i, sub in enumerate(filas_audio, start=1):
            if i > 1:
                # Confirmado en vivo (2026-09-18, O-692-2019): pedir los audios uno
                # detras de otro sin pausa (40 archivos en ~10s) hace que el WAF de
                # `/audio/audioByPass.php` rechace TODAS las descargas (pagina "Request
                # Rejected" con HTTP 200, tanto via fetch como via el fallback de
                # `descargar_bytes`). Los PDFs normales no tienen este problema; el
                # audio si -- se pacea solo este bucle.
                await asyncio.sleep(PAUSA_ENTRE_AUDIOS_S)
            v = sub["valores"]
            if i == 1:
                logger.info(
                    "Audio de audiencia 1, fila cruda completa del popup: valores=%r enlaces=%r posts=%r",
                    v, sub.get("enlaces"), sub.get("posts"),
                )
            numero_raw = _campo(v, "Número", "Numero", "N°", "Nro")
            numero = int(numero_raw) if numero_raw and numero_raw.strip().isdigit() else i
            fecha, referencia = _fila_audio_fecha_referencia(v)
            existente = (
                await session.execute(
                    select(AudioLaboral).where(
                        AudioLaboral.causa_laboral_id == causa.id, AudioLaboral.orden == i,
                    )
                )
            ).scalar_one_or_none()
            # CONFIRMADO en vivo (2026-09-17/18, O-692-2019): las columnas reales son
            # Nro/Descargar/Audio/Fecha -- "Audio" trae la fecha como texto y "Fecha"
            # trae el nombre de archivo (ver `_fila_audio_fecha_referencia`). El link de
            # descarga vive en la celda "Nro", PERO `audioByPass.php` rechaza (WAF,
            # "Request Rejected" con HTTP 200) cualquier pedido por fetch/HTTP aunque la
            # sesion sea valida -- el scraper ya lo descarga con un click REAL de
            # Playwright durante la extraccion (`descarga_click`, ver
            # `MODALES_DESCARGA_CLICK`); `urls` queda solo de fallback por si algun caso
            # no trae `descarga_click` (p. ej. el link no tenia `download`).
            descarga_click = sub.get("descarga_click")
            urls = (
                sub.get("enlaces", {}).get("Nro")
                or sub.get("enlaces", {}).get("Descargar")
                or sub.get("enlaces", {}).get("Audio")
                or sub.get("enlaces", {}).get("Doc.")
                or []
            )

            async def _descargar_audio() -> DocumentoLaboral | None:
                if descarga_click:
                    return await _registrar_documento_desde_ruta_temporal(
                        session, causa.id, "audio", f"audio_{i}", descarga_click.get("ruta_temporal"),
                        nombre_sugerido=descarga_click.get("nombre_sugerido"), referencia=referencia,
                    )
                if urls:
                    return await _obtener_o_descargar_doc(
                        session, sesion_pjud, causa.id, "audio", f"audio_{i}", urls[0], referencia=referencia,
                    )
                return None

            if existente is not None:
                if (descarga_click or urls) and not await _documento_en_disco(session, existente.documento_id):
                    doc = await _descargar_audio()
                    if doc is not None:
                        existente.documento_id = doc.id
                    await session.commit()
                continue
            hubo_cambios = True
            doc = await _descargar_audio()
            session.add(
                AudioLaboral(
                    causa_laboral_id=causa.id, documento_id=doc.id if doc else None, numero=numero,
                    fecha=fecha, referencia=referencia, orden=i,
                )
            )
            await session.commit()

    # --- Cabecera: certificado_envio / ebook --------------------------------
    if cabecera.get("descargas"):
        await _rep("Descargando documentos de la causa")
    for d in cabecera.get("descargas", []):
        categoria = CATEGORIAS_CABECERA.get(_normalizar(d["label"]))
        if categoria is None:
            continue
        await _obtener_o_descargar_doc(
            session, sesion_pjud, causa.id, categoria, categoria, d["url"], forzar=(categoria == "ebook"),
        )
        await session.commit()

    logger.info("Sincronizacion de %s completada (hubo_cambios=%s)", causa.rit, hubo_cambios)
