"""Sincronizacion incremental de una causa Penal. Analoga a `worker/sync_cobranza.py`
(modo PUBLICO o PRIVADO; la causa puede tener varios cuadernos pero
`consultar_movimientos_penal` NO recibe "cuaderno", asi que la Historia de todos se junta
en una tabla causa-wide) con estas diferencias (ver Solicitud Penal.md):

- Secciones: Historia, Litigantes (Intervinientes), Notificaciones (con Georreferencia por
  fila, popup) y Relaciones.
- Cabecera: ROL, Fecha Ingreso, Caratulado, RUC, Est.Adm., Procedimiento, Proc., Forma
  Inicio, Estado Procesal, Etapa, Tribunal; documentos "Acumulada" y "Certificado de
  Envio" expuestos como URL.

NO validado en vivo contra un sitio real con causa Penal (sin ejemplos HTML en el
repo): los nombres de columna se buscan con varios alias y las pestanas por prefijo de
nombre; ver el docstring de `PjudSessionPenalAsync`.

Politica de persistencia igual a Cobranza: Historia con clave natural (causa, cuaderno,
folio, ocurrencia) y filas sin folio "[..]" borrar+reinsertar; Litigantes/Notificaciones/
Relaciones con reemplazo completo por causa (`contenido_hash` deduplica).
"""

import logging
import re

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.penal import (
    CausaPenal,
    CuadernoPenal,
    DocumentoPenal,
    HistoriaPenal,
    HistoriaPenalAnexo,
    HistoriaPenalDoc,
    LitigantePenal,
    NotificacionPenal,
    NotificacionPenalGeoImagen,
    RelacionPenal,
)
from api.db.models.tribunales import TribunalCatalogo
from scraper.pjud_client_async import CausaNoEncontrada, PjudSessionPenalAsync, PjudSessionPenalPrivada
from worker.idempotencia import (
    color_en,
    colores_anexos_fila,
    colores_columna,
    extension_por_content_type,
    hash_fila,
    refrescar_colores_docs_anexos,
    ruta_documento,
)
from worker.sync_civil import _archivo_en_disco, _normalizar, _parsear_folio

logger = logging.getLogger("pjud.worker.sync_penal")


def _campo(campos: dict, *claves: str) -> str | None:
    for k in claves:
        v = campos.get(k)
        if v:
            return v
    return None


def _es_seccion(nombre: str, *prefijos: str) -> bool:
    n = _normalizar(nombre)
    return any(n.startswith(p) for p in prefijos)


def _categoria_descarga_cabecera(label: str) -> str | None:
    n = _normalizar(label)
    if n.startswith("certificado"):
        return "certificado_envio"
    if "acumulad" in n:
        return "acumulada"
    return None


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
) -> DocumentoPenal | None:
    existente = (
        await session.execute(
            select(DocumentoPenal).where(
                DocumentoPenal.causa_penal_id == causa_id,
                DocumentoPenal.clave_logica == clave_logica,
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

    documento = DocumentoPenal(
        causa_penal_id=causa_id,
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
                select(DocumentoPenal).where(
                    DocumentoPenal.causa_penal_id == causa_id,
                    DocumentoPenal.clave_logica == clave_logica,
                )
            )
        ).scalar_one_or_none()
    return documento


# --- Historia (causa-wide, junta todos los cuadernos) --------------------------

_RE_DESC_TRAMITE_DOC = re.compile(r"^(.*?)\s{2,}", re.DOTALL)


def _separar_descripcion_tramite(valores: dict, enlaces: dict) -> tuple[str | None, str | None]:
    """"Desc. Trámite" normalmente es texto plano; algunas filas traen ademas un
    documento embebido en la celda (mismo caso que Cobranza -- ver
    `worker/sync_cobranza.py::_separar_descripcion_tramite`)."""
    texto = _campo(valores, "Desc. Trámite", "Desc. Tramite", "Descripción Trámite", "Descripción Tramite")
    urls = enlaces.get("Desc. Trámite") or enlaces.get("Desc. Tramite") or []
    if not urls or not texto:
        return texto, (urls[0] if urls else None)
    m = _RE_DESC_TRAMITE_DOC.match(texto)
    limpio = m.group(1).strip() if m else texto
    return (limpio or None), urls[0]


def _asignar_campos_historia(mov: HistoriaPenal, valores: dict, descripcion_tramite: str | None) -> None:
    mov.etapa = _campo(valores, "Etapa")
    mov.tramite = _campo(valores, "Trámite", "Tramite")
    mov.descripcion_tramite = descripcion_tramite
    mov.estado_firma = _campo(valores, "Estado Firma", "Firma", "Firmado")
    mov.estado = _campo(valores, "Estado")
    mov.fecha_tramite = _campo(valores, "Fec. Trámite", "Fecha Trámite", "Fec. Tramite", "Fecha Tramite")


async def _persistir_docs_anexos_historia(
    session: AsyncSession,
    sesion_pjud,
    causa: CausaPenal,
    mov: HistoriaPenal,
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
        mov.descripcion_tramite_doc_color = color_en(
            colores_columna(fila, "Desc. Trámite", "Desc. Tramite"), 0
        )

    doc_urls = enlaces.get("Doc.") or []
    if doc_urls:
        await session.execute(delete(HistoriaPenalDoc).where(HistoriaPenalDoc.movimiento_id == mov.id))
        for i, url in enumerate(doc_urls, start=1):
            clave = clave_base if i == 1 else f"{clave_base}_doc{i}"
            doc = await _obtener_o_descargar_doc(session, sesion_pjud, causa.id, "historia", clave, url, hash_padre=h)
            session.add(
                HistoriaPenalDoc(
                    movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i,
                    color=color_en(colores_columna(fila, "Doc."), i - 1),
                )
            )

    anexos_popup = fila.get("anexos_popup") or []
    anexo_urls = enlaces.get("Anexo") or enlaces.get("Anexos") or []
    if anexos_popup:
        await session.execute(delete(HistoriaPenalAnexo).where(HistoriaPenalAnexo.movimiento_id == mov.id))
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
                HistoriaPenalAnexo(
                    movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i,
                    fecha=fecha_anexo, referencia=referencia_anexo, color=a.get("color"),
                )
            )
    elif anexo_urls:
        await session.execute(delete(HistoriaPenalAnexo).where(HistoriaPenalAnexo.movimiento_id == mov.id))
        for i, url in enumerate(anexo_urls, start=1):
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "historia_anexo", f"{clave_base}_anexo{i}", url, hash_padre=h
            )
            session.add(
                HistoriaPenalAnexo(
                    movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i,
                    color=color_en(colores_anexos_fila(fila), i - 1),
                )
            )


async def _sincronizar_historia(
    session: AsyncSession, sesion_pjud, causa: CausaPenal, cuadernos: list[dict]
) -> bool:
    """Junta la Historia de TODOS los cuadernos en `historia_penal` (ver docstring del
    modulo). `orden` es continuo entre cuadernos."""
    previas = sorted(
        tuple(r)
        for r in (
            await session.execute(
                select(HistoriaPenal.cuaderno_numero, HistoriaPenal.folio_texto, HistoriaPenal.hash_contenido).where(
                    HistoriaPenal.causa_penal_id == causa.id, HistoriaPenal.folio_texto.like("[%")
                )
            )
        ).all()
    )
    await session.execute(
        delete(HistoriaPenal).where(HistoriaPenal.causa_penal_id == causa.id, HistoriaPenal.folio_texto.like("[%"))
    )
    await session.commit()

    hubo_cambios = False
    nuevas_sin_clave: list[tuple[int | None, str, str]] = []
    orden_global = 0

    for c in cuadernos:
        cuaderno_numero = c["numero"]
        tabla = next(
            (v for k, v in (c.get("secciones") or {}).items() if _es_seccion(k, "historia")), None
        )
        if tabla is None:
            continue

        ultimo_folio_normal: int | None = None
        exh_ocurrencias: dict[str, int] = {}
        folio_ocurrencias: dict[int, int] = {}

        for fila in tabla.get("filas", []):
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
                mov = HistoriaPenal(
                    causa_penal_id=causa.id, cuaderno_numero=cuaderno_numero,
                    folio=folio, folio_texto=folio_texto, hash_contenido=h, orden=idx,
                )
                _asignar_campos_historia(mov, valores, descripcion_limpia)
                session.add(mov)
                await session.flush()
                await _persistir_docs_anexos_historia(
                    session, sesion_pjud, causa, mov, fila, enlaces, clave_base, h, desc_tramite_url
                )
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
                    select(HistoriaPenal).where(
                        HistoriaPenal.causa_penal_id == causa.id,
                        HistoriaPenal.cuaderno_numero == cuaderno_numero,
                        HistoriaPenal.folio_texto == folio_texto,
                        HistoriaPenal.ocurrencia == ocurrencia,
                    )
                )
            ).scalar_one_or_none()

            if existente is not None and existente.hash_contenido == h:
                if existente.orden != idx:
                    existente.orden = idx
                await refrescar_colores_docs_anexos(session, existente.id, fila, HistoriaPenalDoc, HistoriaPenalAnexo)
                mov_color = colores_columna(fila, "Desc. Trámite", "Desc. Tramite")
                if mov_color and existente.descripcion_tramite_doc_id:
                    existente.descripcion_tramite_doc_color = color_en(mov_color, 0)
                await session.commit()
                continue

            hubo_cambios = True
            if existente is None:
                existente = HistoriaPenal(
                    causa_penal_id=causa.id, cuaderno_numero=cuaderno_numero,
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


async def _reemplazar_litigantes(session: AsyncSession, causa: CausaPenal, cuadernos: list[dict]) -> None:
    await session.execute(delete(LitigantePenal).where(LitigantePenal.causa_penal_id == causa.id))
    vistos: set[str] = set()
    for fila in _filas_seccion(cuadernos, "litigant", "intervin"):
        v = fila["valores"]
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        session.add(
            LitigantePenal(
                causa_penal_id=causa.id,
                participantes=_campo(v, "Participante(s)", "Participantes", "Participante", "Sujeto"),
                rut=_campo(v, "Rut", "RUT"),
                persona=_campo(v, "Persona"),
                razon_social=_campo(v, "Nombre o Razón Social", "Razón Social", "Nombre"),
            )
        )
    await session.commit()


async def _reemplazar_notificaciones(
    session: AsyncSession, sesion_pjud, causa: CausaPenal, cuadernos: list[dict]
) -> None:
    await session.execute(delete(NotificacionPenal).where(NotificacionPenal.causa_penal_id == causa.id))
    vistos: set[str] = set()
    for i, fila in enumerate(_filas_seccion(cuadernos, "notificac"), start=1):
        v = fila["valores"]
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        notif = NotificacionPenal(
            causa_penal_id=causa.id,
            tipo_notificacion=_campo(v, "Tip.Not.", "Tipo Notif.", "Tipo Notificación", "Tipo"),
            estado_notificacion=_campo(v, "Est.Not.", "Estado Notif.", "Estado Notificación", "Estado"),
            fecha_notificacion=_campo(v, "Fec.Not.", "Fecha Notif.", "Fecha Notificación", "Fecha"),
            nombre=_campo(v, "Nombre"),
            estampado=_campo(v, "Estampado"),
            contenido_hash=h,
        )
        datos = fila.get("georeferencia_popup")
        if datos is not None:
            mapa = datos.get("mapa") or {}
            notif.geo_latitud = mapa.get("latitud")
            notif.geo_longitud = mapa.get("longitud")
            notif.geo_corrector = mapa.get("corrector")
        session.add(notif)
        await session.flush()
        for j, img in enumerate((datos or {}).get("imagenes") or [], start=1):
            # Clave por posicion (no por hash): la tabla se reemplaza completa en cada
            # sync y el hash de la fila puede variar si cambia el src de la imagen.
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "notificacion_georef_imagen", f"notif{i}_geo_img{j}",
                url=img.get("src"), referencia=img.get("alt"), hash_padre=h,
            )
            session.add(
                NotificacionPenalGeoImagen(notificacion_id=notif.id, documento_id=doc.id if doc else None, orden=j)
            )
    await session.commit()


async def _reemplazar_relaciones(session: AsyncSession, causa: CausaPenal, cuadernos: list[dict]) -> None:
    await session.execute(delete(RelacionPenal).where(RelacionPenal.causa_penal_id == causa.id))
    vistos: set[str] = set()
    for fila in _filas_seccion(cuadernos, "relacion"):
        v = fila["valores"]
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        session.add(
            RelacionPenal(
                causa_penal_id=causa.id,
                nombre=_campo(v, "Nombre"),
                materia=_campo(v, "Materia"),
                estado_causa=_campo(v, "Estado Causa", "Estado de la Causa", "Estado"),
                fecha_cambio_estado=_campo(
                    v, "Fecha Cambio Estado", "Fecha cambio de estado", "Fec. Cambio Estado", "Fecha"
                ),
                contenido_hash=h,
            )
        )
    await session.commit()


# --- Orquestacion ----------------------------------------------------------


async def sincronizar_causa_penal(
    session: AsyncSession,
    sesion_pjud: "PjudSessionPenalAsync | PjudSessionPenalPrivada",
    causa: CausaPenal,
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
                    TribunalCatalogo.competencia == "penal",
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
            "penal", str(causa.corte), str(causa.tribunal), causa.tipo, causa.rol, causa.anio, progreso=progreso,
        )

    if not resultado.get("encontrada"):
        raise CausaNoEncontrada(f"Causa {causa.rit} no encontrada en PJUD")
    if resultado.get("error"):
        raise RuntimeError(resultado["error"])

    await _rep("Guardando cabecera")
    cabecera = resultado["cabecera"]
    campos = cabecera.get("campos", {})
    logger.info("Cabecera penal (campos crudos): %r", campos)
    causa.rit = _campo(campos, "Rol", "ROL", "RIT", "Rit") or causa.rit
    causa.caratula = _campo(campos, "Caratulado", "Carátula", "Caratula") or causa.caratula
    causa.ruc = _campo(campos, "RUC", "Ruc") or causa.ruc
    causa.fecha_ingreso = _campo(campos, "Fecha Ingreso", "Fecha Ing.", "F. Ing.") or causa.fecha_ingreso
    causa.estado_adm = _campo(campos, "Est.Adm.", "Est. Adm.", "Estado Administrativo") or causa.estado_adm
    causa.procedimiento = _campo(campos, "Procedimiento") or causa.procedimiento
    causa.proceso = _campo(campos, "Proc.", "Proceso") or causa.proceso
    causa.forma_inicio = _campo(campos, "Forma Inicio", "Forma Inicio.", "F. Inicio") or causa.forma_inicio
    causa.estado_proceso = _campo(campos, "Estado Procesal", "Estado Proc.") or causa.estado_proceso
    causa.etapa = _campo(campos, "Etapa") or causa.etapa
    causa.tribunal_nombre = _campo(campos, "Tribunal") or causa.tribunal_nombre
    await session.commit()

    hubo_cambios = False
    cuadernos = resultado.get("cuadernos") or []

    for c in cuadernos:
        cuaderno = (
            await session.execute(
                select(CuadernoPenal).where(
                    CuadernoPenal.causa_penal_id == causa.id, CuadernoPenal.numero == c["numero"]
                )
            )
        ).scalar_one_or_none()
        if cuaderno is None:
            cuaderno = CuadernoPenal(causa_penal_id=causa.id, numero=c["numero"], nombre=c["nombre"])
            session.add(cuaderno)
        else:
            cuaderno.nombre = c["nombre"]
        cuaderno.estado_proceso = c.get("estado_proceso") or cuaderno.estado_proceso
        cuaderno.etapa = c.get("etapa") or cuaderno.etapa
        await session.commit()

    for c in cuadernos:
        for nombre in (c.get("secciones") or {}):
            if not _es_seccion(nombre, "historia", "litigant", "intervin", "notificac", "relacion"):
                logger.info("Seccion de Penal no mapeada, se ignora: %r", nombre)

    await _rep("Guardando historia")
    if await _sincronizar_historia(session, sesion_pjud, causa, cuadernos):
        hubo_cambios = True
    await _rep("Guardando litigantes")
    await _reemplazar_litigantes(session, causa, cuadernos)
    await _rep("Guardando notificaciones")
    await _reemplazar_notificaciones(session, sesion_pjud, causa, cuadernos)
    await _rep("Guardando relaciones")
    await _reemplazar_relaciones(session, causa, cuadernos)

    if cabecera.get("descargas"):
        await _rep("Descargando documentos de la causa")
    for d in cabecera.get("descargas", []):
        categoria = _categoria_descarga_cabecera(d["label"])
        if categoria is None:
            continue
        await _obtener_o_descargar_doc(session, sesion_pjud, causa.id, categoria, categoria, d["url"])
        await session.commit()

    logger.info("Sincronizacion de %s completada (hubo_cambios=%s)", causa.rit, hubo_cambios)
