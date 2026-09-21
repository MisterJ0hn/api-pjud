"""Sincronizacion incremental de una causa Cobranza. Analoga a `worker/sync_laboral.py`
(Cobranza tambien admite modo PUBLICO o PRIVADO, igual que Civil/Laboral) con una
diferencia estructural: la causa puede tener VARIOS cuadernos (selector "Historia Causa
Cuaderno" de la cabecera, igual que Civil) pero `consultar_movimientos_cobranza` NO
recibe "cuadeno" (Solicitud Cobranza.md) -- Historia/Litigantes/Notificaciones/
Diligencias/Liquidacion de TODOS los cuadernos se juntan en una sola tabla causa-wide
(`api/db/models/cobranza.py`), a diferencia de Civil que las particiona por cuaderno.

Secciones del modal (confirmadas en vivo, `ejemplos/causa cobranza/*.html`): Historia,
Litigantes, Notificaciones, Diligencias, Liquidacion. Hay ademas una pestana "Deuda
Act." deshabilitada en el UI, sin contraparte en Solicitud Cobranza.md -- no se
sincroniza.

Politica de persistencia:
- Historia: clave natural (causa, cuaderno_numero, folio, ocurrencia) -> INSERT/UPDATE;
  filas sin folio ("[SF]") -> borrar + reinsertar (junto TODOS los cuadernos, igual que
  civil/laboral con los "[NE]" de exhorto). Descargas idempotentes por `clave_logica`.
- Litigantes / Notificaciones / Diligencias / Liquidacion: reemplazo completo por causa
  en cada sync, con las filas de TODOS los cuadernos juntas (`contenido_hash` deduplica
  filas repetidas entre cuadernos o dentro del mismo).
"""

import logging
import re

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.cobranza import (
    AnexoCausaCobranza,
    CausaCobranza,
    CuadernoCobranza,
    DiligenciaCobranza,
    DocumentoCobranza,
    DocumentoLaboralCobranza,
    HistoriaCobranza,
    HistoriaCobranzaAnexo,
    HistoriaCobranzaDoc,
    HistoriaCobranzaGeoImagen,
    InformacionReceptorCobranza,
    LiquidacionCobranza,
    LitiganteCobranza,
    NotificacionCobranza,
)
from api.db.models.tribunales import TribunalCatalogo
from scraper.pjud_client_async import CausaNoEncontrada, PjudSessionCobranzaAsync, PjudSessionCobranzaPrivada
from worker.idempotencia import extension_por_content_type, hash_fila, ruta_documento, slug
from worker.sync_civil import _archivo_en_disco, _normalizar, _parsear_folio, _parsear_target

logger = logging.getLogger("pjud.worker.sync_cobranza")

CATEGORIAS_CABECERA = {
    "titulo ejec": "titulo_ejec",
    "titulo ejec.": "titulo_ejec",
    "doc. demanda": "doc_demanda",
    "doc demanda": "doc_demanda",
    "certificado de envio": "certificado_envio",
    "certificado envio": "certificado_envio",
    "ebook": "ebook",
}


def _campo(campos: dict, *claves: str) -> str | None:
    for k in claves:
        v = campos.get(k)
        if v:
            return v
    return None


def _es_seccion(nombre: str, *prefijos: str) -> bool:
    n = _normalizar(nombre)
    return any(n.startswith(p) for p in prefijos)


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
) -> DocumentoCobranza | None:
    """`forzar=True` (ebook: PJUD lo regenera completo cada vez que se agrega un
    documento nuevo a la causa) se salta la idempotencia por clave_logica y siempre
    vuelve a pedirlo a PJUD."""
    existente = (
        await session.execute(
            select(DocumentoCobranza).where(
                DocumentoCobranza.causa_cobranza_id == causa_id,
                DocumentoCobranza.clave_logica == clave_logica,
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

    documento = DocumentoCobranza(
        causa_cobranza_id=causa_id,
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
                select(DocumentoCobranza).where(
                    DocumentoCobranza.causa_cobranza_id == causa_id,
                    DocumentoCobranza.clave_logica == clave_logica,
                )
            )
        ).scalar_one_or_none()
    return documento


async def _documento_en_disco(session: AsyncSession, documento_id) -> bool:
    if documento_id is None:
        return False
    ruta = (
        await session.execute(select(DocumentoCobranza.ruta_archivo).where(DocumentoCobranza.id == documento_id))
    ).scalar_one_or_none()
    return _archivo_en_disco(ruta)


# --- Historia (causa-wide, junta todos los cuadernos) --------------------------


_RE_DESC_TRAMITE_DOC = re.compile(r"^(.*?)\s{2,}", re.DOTALL)


def _separar_descripcion_tramite(valores: dict, enlaces: dict) -> tuple[str | None, str | None]:
    """"Desc. Trámite" normalmente es texto plano, pero algunas filas (ej. "Requiérase"
    de un Oficio) traen ademas un documento embebido en la misma celda -- un `<label>`
    con icono "Descargar Documento" dentro de un `<a>`, mas un `<p style="display:none">`
    con un codigo oculto -- CONFIRMADO en vivo (causa C-10-2025, folio 5, dos filas:
    "Requiérase" + oficio). El texto crudo de la celda mezcla la descripcion real con el
    texto del icono y el codigo oculto; se toma todo lo anterior a la primera corrida
    larga de espacios/tabs (el layout real separa esas partes asi) como la descripcion
    limpia. Sin link en la celda, se devuelve el texto tal cual (caso normal)."""
    texto = _campo(valores, "Desc. Trámite", "Desc. Tramite", "Descripción Trámite")
    urls = enlaces.get("Desc. Trámite") or enlaces.get("Desc. Tramite") or []
    if not urls or not texto:
        return texto, (urls[0] if urls else None)
    m = _RE_DESC_TRAMITE_DOC.match(texto)
    limpio = m.group(1).strip() if m else texto
    return (limpio or None), urls[0]


def _asignar_campos_historia(mov: HistoriaCobranza, valores: dict, descripcion_tramite: str | None) -> None:
    mov.etapa = _campo(valores, "Etapa")
    mov.tramite = _campo(valores, "Trámite", "Tramite")
    mov.descripcion_tramite = descripcion_tramite
    mov.estado_firma = _campo(valores, "Estado Firma")
    mov.fecha_tramite = _campo(valores, "Fec. Trámite", "Fecha Trámite", "Fec. Tramite")


async def _persistir_docs_anexos_historia(
    session: AsyncSession,
    sesion_pjud,
    causa: CausaCobranza,
    mov: HistoriaCobranza,
    fila: dict,
    enlaces: dict,
    clave_base: str,
    h: str,
    descripcion_tramite_url: str | None = None,
) -> None:
    if descripcion_tramite_url:
        doc = await _obtener_o_descargar_doc(
            session, sesion_pjud, causa.id, "historia_desc_tramite", f"{clave_base}_desc_tramite",
            descripcion_tramite_url, hash_padre=h,
        )
        mov.descripcion_tramite_doc_id = doc.id if doc else None

    doc_urls = enlaces.get("Doc.") or []
    if doc_urls:
        await session.execute(delete(HistoriaCobranzaDoc).where(HistoriaCobranzaDoc.movimiento_id == mov.id))
        for i, url in enumerate(doc_urls, start=1):
            clave = clave_base if i == 1 else f"{clave_base}_doc{i}"
            doc = await _obtener_o_descargar_doc(session, sesion_pjud, causa.id, "historia", clave, url, hash_padre=h)
            session.add(HistoriaCobranzaDoc(movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i))

    # Columna "Anexo": carpeta-popup (`modalAnexoEscritoCobranza`, ya volcada por el
    # scraper en `fila["anexos_popup"]`) o enlaces directos.
    anexos_popup = fila.get("anexos_popup") or []
    anexo_urls = enlaces.get("Anexo") or enlaces.get("Anexos") or []
    if anexos_popup:
        await session.execute(delete(HistoriaCobranzaAnexo).where(HistoriaCobranzaAnexo.movimiento_id == mov.id))
        for i, a in enumerate(anexos_popup, start=1):
            v_anexo = a.get("valores") or {}
            fecha_anexo = _campo(v_anexo, "Fecha")
            referencia_anexo = _campo(v_anexo, "Referencia")
            doc = None
            if a.get("doc") or a.get("doc_post"):
                doc = await _obtener_o_descargar_doc(
                    session, sesion_pjud, causa.id, "historia_anexo", f"{clave_base}_anexo{i}",
                    url=a.get("doc"), post=a.get("doc_post"), referencia=referencia_anexo, hash_padre=h,
                )
            session.add(
                HistoriaCobranzaAnexo(
                    movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i,
                    fecha=fecha_anexo, referencia=referencia_anexo,
                )
            )
    elif anexo_urls:
        await session.execute(delete(HistoriaCobranzaAnexo).where(HistoriaCobranzaAnexo.movimiento_id == mov.id))
        for i, url in enumerate(anexo_urls, start=1):
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "historia_anexo", f"{clave_base}_anexo{i}", url, hash_padre=h
            )
            session.add(HistoriaCobranzaAnexo(movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i))


async def _persistir_georeferencia_historia(
    session: AsyncSession, sesion_pjud, causa: CausaCobranza, mov: HistoriaCobranza, fila: dict, clave_base: str, h: str
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
        delete(HistoriaCobranzaGeoImagen).where(HistoriaCobranzaGeoImagen.movimiento_id == mov.id)
    )
    for i, img in enumerate(imagenes, start=1):
        doc = await _obtener_o_descargar_doc(
            session, sesion_pjud, causa.id, "historia_georef_imagen", f"{clave_base}_geo_img{i}",
            url=img.get("src"), referencia=img.get("alt"), hash_padre=h,
        )
        session.add(HistoriaCobranzaGeoImagen(movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i))


async def _sincronizar_historia(
    session: AsyncSession, sesion_pjud, causa: CausaCobranza, cuadernos: list[dict]
) -> bool:
    """Junta la tabla Historia de TODOS los cuadernos en `historia_cobranza` (causa-wide:
    ver docstring del modulo). `cuaderno_numero` evita que dos cuadernos con el mismo
    folio colisionen en la clave natural; `orden` es continuo entre cuadernos (cuaderno 1
    completo, despues cuaderno 2, etc.) para que el repository lo pueda ordenar tal cual."""
    previas = sorted(
        tuple(r)
        for r in (
            await session.execute(
                select(
                    HistoriaCobranza.cuaderno_numero, HistoriaCobranza.folio_texto, HistoriaCobranza.hash_contenido
                ).where(HistoriaCobranza.causa_cobranza_id == causa.id, HistoriaCobranza.folio_texto.like("[%"))
            )
        ).all()
    )
    await session.execute(
        delete(HistoriaCobranza).where(
            HistoriaCobranza.causa_cobranza_id == causa.id, HistoriaCobranza.folio_texto.like("[%")
        )
    )
    await session.commit()

    hubo_cambios = False
    nuevas_sin_clave: list[tuple[int | None, str, str]] = []
    orden_global = 0

    for c in cuadernos:
        cuaderno_numero = c["numero"]
        tabla = (c.get("secciones") or {}).get("Historia") or next(
            (v for k, v in (c.get("secciones") or {}).items() if _es_seccion(k, "historia")), None
        )
        if tabla is None:
            continue
        filas = tabla.get("filas", [])

        ultimo_folio_normal: int | None = None
        exh_ocurrencias: dict[str, int] = {}
        folio_ocurrencias: dict[int, int] = {}

        for fila in filas:
            valores = fila["valores"]
            enlaces = fila.get("enlaces", {})
            folio_parseado = _parsear_folio(valores.get("Folio") or "")
            if folio_parseado is None:
                logger.warning("Folio de historia con formato inesperado %r; se omite", valores.get("Folio"))
                continue
            folio_texto, folio, sin_clave_natural = folio_parseado
            h = hash_fila(valores)
            orden_global += 1
            idx = orden_global

            if sin_clave_natural:
                nuevas_sin_clave.append((cuaderno_numero, folio_texto, h))
                ancla = ultimo_folio_normal if ultimo_folio_normal is not None else 0
                clave_base = (
                    f"historia_c{cuaderno_numero}_sf{ancla}" if folio is None
                    else f"historia_c{cuaderno_numero}_exh{ancla}_{folio}"
                )
                exh_ocurrencias[clave_base] = exh_ocurrencias.get(clave_base, 0) + 1
                if exh_ocurrencias[clave_base] > 1:
                    clave_base = f"{clave_base}_o{exh_ocurrencias[clave_base]}"
                descripcion_limpia, desc_tramite_url = _separar_descripcion_tramite(valores, enlaces)
                mov = HistoriaCobranza(
                    causa_cobranza_id=causa.id, cuaderno_numero=cuaderno_numero,
                    folio=folio, folio_texto=folio_texto, hash_contenido=h, orden=idx,
                )
                _asignar_campos_historia(mov, valores, descripcion_limpia)
                session.add(mov)
                await session.flush()
                await _persistir_docs_anexos_historia(
                    session, sesion_pjud, causa, mov, fila, enlaces, clave_base, h, desc_tramite_url
                )
                await _persistir_georeferencia_historia(session, sesion_pjud, causa, mov, fila, clave_base, h)
                await session.commit()
                continue

            ultimo_folio_normal = folio
            folio_ocurrencias[folio] = folio_ocurrencias.get(folio, 0) + 1
            ocurrencia = folio_ocurrencias[folio]
            clave_docs = f"historia_c{cuaderno_numero}_folio{folio}"
            if ocurrencia > 1:
                clave_docs = f"{clave_docs}_o{ocurrencia}"

            existente = (
                await session.execute(
                    select(HistoriaCobranza).where(
                        HistoriaCobranza.causa_cobranza_id == causa.id,
                        HistoriaCobranza.cuaderno_numero == cuaderno_numero,
                        HistoriaCobranza.folio_texto == folio_texto,
                        HistoriaCobranza.ocurrencia == ocurrencia,
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
                existente = HistoriaCobranza(
                    causa_cobranza_id=causa.id, cuaderno_numero=cuaderno_numero,
                    folio=folio, folio_texto=folio_texto, hash_contenido=h,
                    orden=idx, ocurrencia=ocurrencia,
                )
                session.add(existente)
                await session.flush()

            descripcion_limpia, desc_tramite_url = _separar_descripcion_tramite(valores, enlaces)
            existente.orden = idx
            _asignar_campos_historia(existente, valores, descripcion_limpia)
            existente.hash_contenido = h
            await session.flush()
            await _persistir_docs_anexos_historia(
                session, sesion_pjud, causa, existente, fila, enlaces, clave_docs, h, desc_tramite_url
            )
            await _persistir_georeferencia_historia(session, sesion_pjud, causa, existente, fila, clave_docs, h)
            await session.commit()

    if sorted(nuevas_sin_clave) != previas:
        hubo_cambios = True
    return hubo_cambios


# --- Secciones de reemplazo completo (junta todos los cuadernos) ---------------


def _filas_seccion(cuadernos: list[dict], *prefijos: str) -> list[dict]:
    filas: list[dict] = []
    for c in cuadernos:
        for nombre, tabla in (c.get("secciones") or {}).items():
            if _es_seccion(nombre, *prefijos):
                filas.extend(tabla.get("filas", []))
    return filas


async def _reemplazar_litigantes(session: AsyncSession, causa: CausaCobranza, cuadernos: list[dict]) -> None:
    await session.execute(delete(LitiganteCobranza).where(LitiganteCobranza.causa_cobranza_id == causa.id))
    vistos: set[str] = set()
    for fila in _filas_seccion(cuadernos, "litigant"):
        v = fila["valores"]
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        session.add(
            LitiganteCobranza(
                causa_cobranza_id=causa.id,
                sujeto=_campo(v, "Sujeto"),
                rut=_campo(v, "Rut", "RUT"),
                persona=_campo(v, "Persona"),
                razon_social=_campo(v, "Nombre o Razón Social", "Nombre", "Razón Social"),
            )
        )
    await session.commit()


async def _reemplazar_notificaciones(session: AsyncSession, causa: CausaCobranza, cuadernos: list[dict]) -> None:
    await session.execute(delete(NotificacionCobranza).where(NotificacionCobranza.causa_cobranza_id == causa.id))
    vistos: set[str] = set()
    for fila in _filas_seccion(cuadernos, "notificac"):
        v = fila["valores"]
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        session.add(
            NotificacionCobranza(
                causa_cobranza_id=causa.id,
                tipo_notificacion=_campo(v, "Tip.Not.", "Tipo Notif."),
                estado_notificacion=_campo(v, "Est.Not.", "Estado Notif."),
                fecha_notificacion=_campo(v, "Fec.Not.", "Fecha Notif."),
                fecha_tramite=_campo(v, "Fec.Tram.", "Fecha Trámite"),
                tramite=_campo(v, "Trámite", "Tramite"),
                tipo_part=_campo(v, "Tip.Part.", "Tipo Part."),
                nombre=_campo(v, "Nombre"),
                contenido_hash=h,
            )
        )
    await session.commit()


async def _reemplazar_diligencias(
    session: AsyncSession, sesion_pjud, causa: CausaCobranza, cuadernos: list[dict]
) -> bool:
    previos = set(
        (
            await session.execute(
                select(DiligenciaCobranza.contenido_hash).where(DiligenciaCobranza.causa_cobranza_id == causa.id)
            )
        ).scalars().all()
    )
    await session.execute(delete(DiligenciaCobranza).where(DiligenciaCobranza.causa_cobranza_id == causa.id))
    vistos: set[str] = set()
    for i, fila in enumerate(_filas_seccion(cuadernos, "diligenc"), start=1):
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
            DiligenciaCobranza(
                causa_cobranza_id=causa.id,
                doc_ida_id=doc_ida.id if doc_ida else None,
                doc_vta_id=doc_vta.id if doc_vta else None,
                estado_diligencia=_campo(v, "Estado Diligencia", "Estado"),
                rit=_campo(v, "RIT", "Rit"),
                ruc=_campo(v, "RUC", "Ruc"),
                tipo_diligencia=_campo(v, "Tipo Diligencia", "Tipo"),
                fecha_tramite=_campo(v, "Fecha Trámite", "Fec. Trámite"),
                destinatario=_campo(v, "Destinatario"),
                responsable=_campo(v, "Responsable"),
                contenido_hash=h,
            )
        )
    await session.commit()
    return vistos != previos


async def _reemplazar_liquidacion(
    session: AsyncSession, sesion_pjud, causa: CausaCobranza, cuadernos: list[dict]
) -> None:
    """`Liquidación` es un documento descargable (form GET), no texto -- confirmado en
    vivo (causa C-10-2025, ver `ejemplos/causa cobranza/diligencias.html`)."""
    await session.execute(delete(LiquidacionCobranza).where(LiquidacionCobranza.causa_cobranza_id == causa.id))
    vistos: set[str] = set()
    for i, fila in enumerate(_filas_seccion(cuadernos, "liquidac"), start=1):
        v = fila["valores"]
        enlaces = fila.get("enlaces", {})
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        urls = enlaces.get("Liquidación") or enlaces.get("Liquidacion") or []
        doc = None
        if urls:
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "liquidacion", f"liquidacion_{i}", urls[0], hash_padre=h
            )
        session.add(
            LiquidacionCobranza(
                causa_cobranza_id=causa.id,
                liquidacion_doc_id=doc.id if doc else None,
                fecha_liquidacion=_campo(v, "Fecha Liquidación", "Fecha Liquidacion"),
                cuaderno=_campo(v, "Cuaderno"),
                estado=_campo(v, "Estado"),
                monto_liquido=_campo(v, "Monto Líquido", "Monto Liquido"),
                contenido_hash=h,
            )
        )
    await session.commit()


# --- Orquestacion ----------------------------------------------------------


async def sincronizar_causa_cobranza(
    session: AsyncSession,
    sesion_pjud: "PjudSessionCobranzaAsync | PjudSessionCobranzaPrivada",
    causa: CausaCobranza,
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
                    TribunalCatalogo.competencia == "cobranza",
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
            "cobranza", str(causa.corte), str(causa.tribunal), causa.tipo, causa.rol, causa.anio, progreso=progreso,
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
    causa.fecha_ingreso = _campo(campos, "Fecha Ing.", "F. Ing.") or causa.fecha_ingreso
    causa.proceso = _campo(campos, "Proc.", "Proceso") or causa.proceso
    causa.forma_inicio = _campo(campos, "Forma Inicio.", "Forma Inicio", "F. Inicio") or causa.forma_inicio
    causa.est_adm = _campo(campos, "Est. Adm.", "Estado Administrativo") or causa.est_adm
    causa.etapa = _campo(campos, "Etapa") or causa.etapa
    causa.estado_proceso = _campo(campos, "Estado Proc.", "Estado Procesal") or causa.estado_proceso
    causa.juez_asignado = _campo(campos, "Juez Asignado") or causa.juez_asignado
    causa.tribunal_nombre = _campo(campos, "Tribunal") or causa.tribunal_nombre
    await session.commit()

    hubo_cambios = False
    cuadernos = resultado.get("cuadernos") or []

    # --- Cuadernos (informativo: nombre/estado/etapa, igual que civil) -----------
    for c in cuadernos:
        cuaderno = (
            await session.execute(
                select(CuadernoCobranza).where(
                    CuadernoCobranza.causa_cobranza_id == causa.id, CuadernoCobranza.numero == c["numero"]
                )
            )
        ).scalar_one_or_none()
        if cuaderno is None:
            cuaderno = CuadernoCobranza(causa_cobranza_id=causa.id, numero=c["numero"], nombre=c["nombre"])
            session.add(cuaderno)
        else:
            cuaderno.nombre = c["nombre"]
        cuaderno.estado_proceso = c.get("estado_proceso") or cuaderno.estado_proceso
        cuaderno.etapa = c.get("etapa") or cuaderno.etapa
        await session.commit()

    # --- Historia + secciones de reemplazo completo (juntan todos los cuadernos) -
    await _rep("Guardando historia")
    if await _sincronizar_historia(session, sesion_pjud, causa, cuadernos):
        hubo_cambios = True
    await _rep("Guardando litigantes")
    await _reemplazar_litigantes(session, causa, cuadernos)
    await _rep("Guardando notificaciones")
    await _reemplazar_notificaciones(session, causa, cuadernos)
    await _rep("Guardando diligencias")
    if await _reemplazar_diligencias(session, sesion_pjud, causa, cuadernos):
        hubo_cambios = True
    await _rep("Guardando liquidacion")
    await _reemplazar_liquidacion(session, sesion_pjud, causa, cuadernos)

    # --- Cabecera: Anexos de la causa, Información notificaciones receptor,
    #     Documentos Laboral (submodales) -----------------------------------------
    submodales = cabecera.get("submodales", {}) or {}
    if submodales:
        await _rep("Guardando anexos de la causa")
    for sub in submodales.get("Anexos de la causa", {}).get("filas", []):
        v = sub["valores"]
        referencia, fecha = _campo(v, "Referencia"), _campo(v, "Fecha")
        target = _parsear_target(sub.get("targets"), "Doc.")
        existente = (
            await session.execute(
                select(AnexoCausaCobranza).where(
                    AnexoCausaCobranza.causa_cobranza_id == causa.id,
                    AnexoCausaCobranza.referencia == referencia,
                    AnexoCausaCobranza.fecha == fecha,
                )
            )
        ).scalar_one_or_none()
        urls = sub.get("enlaces", {}).get("Doc.") or []
        if existente is not None:
            cambiado = False
            if target is not None and existente.target != target:
                existente.target = target
                cambiado = True
            if urls and not await _documento_en_disco(session, existente.documento_id):
                doc = await _obtener_o_descargar_doc(
                    session, sesion_pjud, causa.id, "anexo_causa", f"anexo_{slug(referencia)}",
                    urls[0], referencia=referencia,
                )
                if doc is not None and existente.documento_id != doc.id:
                    existente.documento_id = doc.id
                cambiado = True
            if cambiado:
                await session.commit()
            continue
        hubo_cambios = True
        documento_id = None
        if urls:
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "anexo_causa", f"anexo_{slug(referencia)}", urls[0], referencia=referencia
            )
            documento_id = doc.id if doc else None
        session.add(
            AnexoCausaCobranza(
                causa_cobranza_id=causa.id, documento_id=documento_id, fecha=fecha, referencia=referencia, target=target
            )
        )
        await session.commit()

    for sub in submodales.get("Información notificaciones receptor", {}).get("filas", []):
        v = sub["valores"]
        cuaderno_nombre, fecha_retiro = _campo(v, "Cuaderno"), _campo(v, "Fecha Retiro")
        existente = (
            await session.execute(
                select(InformacionReceptorCobranza).where(
                    InformacionReceptorCobranza.causa_cobranza_id == causa.id,
                    InformacionReceptorCobranza.cuaderno_nombre == cuaderno_nombre,
                    InformacionReceptorCobranza.fecha_retiro == fecha_retiro,
                )
            )
        ).scalar_one_or_none()
        if existente is not None:
            continue
        session.add(
            InformacionReceptorCobranza(
                causa_cobranza_id=causa.id,
                cuaderno_nombre=cuaderno_nombre,
                datos_retiro=_campo(v, "Datos del Retiro"),
                fecha_retiro=fecha_retiro,
                # Confirmado en vivo (causa C-10-2025): el popup solo trae Cuaderno/Datos
                # del Retiro/Fecha Retiro, sin columna "Estado" -- queda siempre None,
                # se preserva el campo por fidelidad con Solicitud Cobranza.md.
                estado=_campo(v, "Estado"),
            )
        )
        await session.commit()

    for orden_doc_lab, sub in enumerate(submodales.get("Documentos Laboral", {}).get("filas", []), start=1):
        v = sub["valores"]
        referencia, fecha = _campo(v, "Referencia"), _campo(v, "Fecha")
        existente = (
            await session.execute(
                select(DocumentoLaboralCobranza).where(
                    DocumentoLaboralCobranza.causa_cobranza_id == causa.id,
                    DocumentoLaboralCobranza.referencia == referencia,
                    DocumentoLaboralCobranza.fecha == fecha,
                )
            )
        ).scalar_one_or_none()
        # Confirmado en vivo: form POST (docLaboralCobranza.php), a diferencia de Doc.
        # Demanda/Ebook/Anexo de la Causa que son GET.
        posts = sub.get("posts", {}).get("Doc.") or []
        if existente is not None:
            if posts and not await _documento_en_disco(session, existente.documento_id):
                doc = await _obtener_o_descargar_doc(
                    session, sesion_pjud, causa.id, "documento_laboral", f"doclab_{slug(referencia)}",
                    post=posts[0], referencia=referencia,
                )
                if doc is not None:
                    existente.documento_id = doc.id
                await session.commit()
            continue
        hubo_cambios = True
        documento_id = None
        if posts:
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "documento_laboral", f"doclab_{slug(referencia)}",
                post=posts[0], referencia=referencia,
            )
            documento_id = doc.id if doc else None
        session.add(
            DocumentoLaboralCobranza(
                causa_cobranza_id=causa.id, documento_id=documento_id, fecha=fecha, referencia=referencia,
                orden=orden_doc_lab,
            )
        )
        await session.commit()

    # --- Cabecera: titulo_ejec / doc_demanda / ebook / certificado_envio ---------
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
