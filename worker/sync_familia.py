"""Sincronizacion incremental de una causa de Familia. Analogo a `worker/sync_civil.py`
pero sobre las tablas `*_familia` y con las diferencias de la competencia:

- Familia es SIEMPRE privada y SIEMPRE cuaderno unico -> no hay bucle de cuadernos.
- Secciones del modal: Historia, Litigantes, Materias, Plazos, Notificaciones,
  Diligencias (no hay "Escritos por Resolver" ni "Exhortos").
- Cabecera: agrega RUC y Forma Inicio; no tiene Ubicacion ni Informacion Receptor.

Politica de persistencia (igual que civil):
- Historia: clave natural (causa, folio, ocurrencia) -> INSERT/UPDATE; filas sin folio
  o de exhorto ("[NE]") -> borrar + reinsertar. Descargas idempotentes por `clave_logica`.
- Litigantes / Materias / Plazos / Notificaciones / Diligencias: reemplazo completo por
  causa en cada sync (tablas chicas; `contenido_hash` deduplica filas repetidas por PJUD).
"""

import logging

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.familia import (
    AnexoCausaFamilia,
    CausaFamilia,
    DiligenciaFamilia,
    DocumentoFamilia,
    LitiganteFamilia,
    MateriaFamilia,
    MovimientoHistoriaFamilia,
    MovimientoHistoriaFamiliaAnexo,
    MovimientoHistoriaFamiliaDoc,
    NotificacionFamilia,
    PlazoFamilia,
)
from scraper.pjud_client_async import CausaNoEncontrada, PjudSessionFamiliaPrivada
from worker.idempotencia import extension_por_content_type, hash_fila, ruta_documento, slug
from worker.sync_civil import _archivo_en_disco, _normalizar, _parsear_folio

logger = logging.getLogger("pjud.worker.sync_familia")

CATEGORIAS_CABECERA = {
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


async def _descargar_a_disco(
    sesion_pjud, url: str, causa_id, clave_logica: str, post: dict | None = None
) -> str | None:
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
) -> DocumentoFamilia | None:
    existente = (
        await session.execute(
            select(DocumentoFamilia).where(
                DocumentoFamilia.causa_familia_id == causa_id,
                DocumentoFamilia.clave_logica == clave_logica,
            )
        )
    ).scalar_one_or_none()
    if existente is not None:
        if _archivo_en_disco(existente.ruta_archivo):
            return existente
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

    documento = DocumentoFamilia(
        causa_familia_id=causa_id,
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
                select(DocumentoFamilia).where(
                    DocumentoFamilia.causa_familia_id == causa_id,
                    DocumentoFamilia.clave_logica == clave_logica,
                )
            )
        ).scalar_one_or_none()
    return documento


async def _documento_en_disco(session: AsyncSession, documento_id) -> bool:
    if documento_id is None:
        return False
    ruta = (
        await session.execute(select(DocumentoFamilia.ruta_archivo).where(DocumentoFamilia.id == documento_id))
    ).scalar_one_or_none()
    return _archivo_en_disco(ruta)


# --- Historia ----------------------------------------------------------------


def _anexo_campos(a: dict) -> tuple[int | None, str | None, str | None, str | None]:
    """(folio, fecha, nombre_documento, observacion) de una fila de anexo-popup, segun
    el tipo de popup del que salio:

    - modalAnexoEscritoFamilia: Folio / Fecha / Nombre Documento / Observación.
    - modalSIIFamilia: sin folio; Fecha Recepción, Nombre Litigante -> nombre_documento,
      Formulario -> observacion.
    """
    v = a.get("valores") or {}
    if a.get("popup") == "modalSIIFamilia":
        return (
            None,
            _campo(v, "Fecha Recepción", "Fecha Recepcion", "Fecha"),
            _campo(v, "Nombre Litigante", "Nombre"),
            _campo(v, "Formulario"),
        )
    folio = _campo(v, "Folio")
    return (
        int(folio) if folio and folio.isdigit() else None,
        _campo(v, "Fecha"),
        _campo(v, "Nombre Documento", "Nombre del Documento", "Referencia"),
        _campo(v, "Observación", "Observacion"),
    )


def _asignar_campos_historia(mov: MovimientoHistoriaFamilia, valores: dict) -> None:
    mov.etapa = _campo(valores, "Etapa")
    mov.estado = _campo(valores, "Estado")
    mov.tramite = _campo(valores, "Trámite", "Tramite")
    mov.descripcion_tramite = _campo(valores, "Desc. Trámite", "Desc. Tramite", "Descripción Trámite")
    mov.fecha_tramite = _campo(valores, "Fec. Trámite", "Fecha Trámite", "Fec. Tramite")


async def _persistir_docs_anexos_historia(
    session: AsyncSession,
    sesion_pjud,
    causa: CausaFamilia,
    mov: MovimientoHistoriaFamilia,
    fila: dict,
    enlaces: dict,
    clave_base: str,
    h: str,
) -> None:
    doc_urls = enlaces.get("Doc.") or []
    if doc_urls:
        await session.execute(
            delete(MovimientoHistoriaFamiliaDoc).where(MovimientoHistoriaFamiliaDoc.movimiento_id == mov.id)
        )
        for i, url in enumerate(doc_urls, start=1):
            clave = clave_base if i == 1 else f"{clave_base}_doc{i}"
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "historia", clave, url, hash_padre=h
            )
            session.add(
                MovimientoHistoriaFamiliaDoc(
                    movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i
                )
            )

    # Anexos del folio: carpeta-popup que el scraper ya volco en `fila["anexos_popup"]`
    # (dos tipos en Familia: "Anexo del Escrito" con descarga GET, y "Documentos SII" con
    # descarga POST) y/o enlaces directos en la celda "Anexos".
    anexos_popup = fila.get("anexos_popup") or []
    anexo_urls = enlaces.get("Anexos") or enlaces.get("Anexo") or []
    if anexos_popup:
        await session.execute(
            delete(MovimientoHistoriaFamiliaAnexo).where(MovimientoHistoriaFamiliaAnexo.movimiento_id == mov.id)
        )
        for i, a in enumerate(anexos_popup, start=1):
            folio_a, fecha_a, nombre_a, obs_a = _anexo_campos(a)
            doc = None
            if a.get("doc") or a.get("doc_post"):
                doc = await _obtener_o_descargar_doc(
                    session, sesion_pjud, causa.id, "historia_anexo", f"{clave_base}_anexo{i}",
                    url=a.get("doc"), post=a.get("doc_post"), referencia=nombre_a, hash_padre=h,
                )
            session.add(
                MovimientoHistoriaFamiliaAnexo(
                    movimiento_id=mov.id,
                    documento_id=doc.id if doc else None,
                    orden=i,
                    folio=folio_a,
                    fecha=fecha_a,
                    nombre_documento=nombre_a,
                    observacion=obs_a,
                )
            )
    elif anexo_urls:
        await session.execute(
            delete(MovimientoHistoriaFamiliaAnexo).where(MovimientoHistoriaFamiliaAnexo.movimiento_id == mov.id)
        )
        for i, url in enumerate(anexo_urls, start=1):
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "historia_anexo", f"{clave_base}_anexo{i}", url, hash_padre=h
            )
            session.add(
                MovimientoHistoriaFamiliaAnexo(
                    movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i
                )
            )


async def _sincronizar_historia(
    session: AsyncSession, sesion_pjud, causa: CausaFamilia, tabla: dict
) -> bool:
    filas = tabla.get("filas", [])

    # Filas sin clave natural estable (sin folio "[SF]" / exhorto "[NE]"): se reconstruyen
    # enteras cada sync. Se compara como multiset para detectar cambios.
    previas = sorted(
        tuple(r)
        for r in (
            await session.execute(
                select(MovimientoHistoriaFamilia.folio_texto, MovimientoHistoriaFamilia.hash_contenido).where(
                    MovimientoHistoriaFamilia.causa_familia_id == causa.id,
                    MovimientoHistoriaFamilia.folio_texto.like("[%"),
                )
            )
        ).all()
    )
    await session.execute(
        delete(MovimientoHistoriaFamilia).where(
            MovimientoHistoriaFamilia.causa_familia_id == causa.id,
            MovimientoHistoriaFamilia.folio_texto.like("[%"),
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
            logger.warning("Folio de historia con formato inesperado %r; se omite", valores.get("Folio"))
            continue
        folio_texto, folio, sin_clave_natural = folio_parseado
        h = hash_fila(valores)

        if sin_clave_natural:
            nuevas_sin_clave.append((folio_texto, h))
            ancla = ultimo_folio_normal if ultimo_folio_normal is not None else 0
            if folio is None:
                clave_base = f"historia_sf{ancla}"
            else:
                clave_base = f"historia_exh{ancla}_{folio}"
            exh_ocurrencias[clave_base] = exh_ocurrencias.get(clave_base, 0) + 1
            if exh_ocurrencias[clave_base] > 1:
                clave_base = f"{clave_base}_o{exh_ocurrencias[clave_base]}"
            mov = MovimientoHistoriaFamilia(
                causa_familia_id=causa.id,
                folio=folio,
                folio_texto=folio_texto,
                hash_contenido=h,
                orden=idx,
            )
            _asignar_campos_historia(mov, valores)
            session.add(mov)
            await session.flush()
            await _persistir_docs_anexos_historia(session, sesion_pjud, causa, mov, fila, enlaces, clave_base, h)
            await session.commit()
            continue

        ultimo_folio_normal = folio
        folio_ocurrencias[folio] = folio_ocurrencias.get(folio, 0) + 1
        ocurrencia = folio_ocurrencias[folio]
        clave_docs = f"historia_folio{folio}"
        if ocurrencia > 1:
            clave_docs = f"{clave_docs}_o{ocurrencia}"

        existente = (
            await session.execute(
                select(MovimientoHistoriaFamilia).where(
                    MovimientoHistoriaFamilia.causa_familia_id == causa.id,
                    MovimientoHistoriaFamilia.folio_texto == folio_texto,
                    MovimientoHistoriaFamilia.ocurrencia == ocurrencia,
                )
            )
        ).scalar_one_or_none()

        if existente is not None and existente.hash_contenido == h:
            # Sin cambios de contenido; solo se ajusta la posicion si PJUD agrego filas
            # arriba. Los documentos ya descargados no se re-piden.
            if existente.orden != idx:
                existente.orden = idx
                await session.commit()
            continue

        hubo_cambios = True
        if existente is None:
            existente = MovimientoHistoriaFamilia(
                causa_familia_id=causa.id,
                folio=folio,
                folio_texto=folio_texto,
                hash_contenido=h,
                orden=idx,
                ocurrencia=ocurrencia,
            )
            session.add(existente)
            await session.flush()

        existente.orden = idx
        _asignar_campos_historia(existente, valores)
        existente.hash_contenido = h
        await session.flush()
        await _persistir_docs_anexos_historia(session, sesion_pjud, causa, existente, fila, enlaces, clave_docs, h)
        await session.commit()

    if sorted(nuevas_sin_clave) != previas:
        hubo_cambios = True
    return hubo_cambios


# --- Secciones de reemplazo completo ----------------------------------------


async def _reemplazar_litigantes(session: AsyncSession, causa: CausaFamilia, tabla: dict) -> None:
    await session.execute(delete(LitiganteFamilia).where(LitiganteFamilia.causa_familia_id == causa.id))
    for fila in tabla.get("filas", []):
        v = fila["valores"]
        session.add(
            LitiganteFamilia(
                causa_familia_id=causa.id,
                sujeto=_campo(v, "Sujeto", "Participante"),
                rut=_campo(v, "Rut", "RUT"),
                persona=_campo(v, "Persona"),
                razon_social=_campo(v, "Nombre o Razón Social", "Nombre", "Razón Social"),
            )
        )
    await session.commit()


async def _reemplazar_materias(session: AsyncSession, causa: CausaFamilia, tabla: dict) -> None:
    await session.execute(delete(MateriaFamilia).where(MateriaFamilia.causa_familia_id == causa.id))
    vistos: set[str] = set()
    for fila in tabla.get("filas", []):
        v = fila["valores"]
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        session.add(
            MateriaFamilia(
                causa_familia_id=causa.id,
                codigo=_campo(v, "Código", "Codigo", "Cod. Materia"),
                glosa=_campo(v, "Materia", "Glosa Materia", "Glosa de Materia"),
                estado=_campo(v, "Estado"),
                fecha_termino=_campo(v, "Fecha Término", "Fecha Termino", "Fec. Término"),
                contenido_hash=h,
            )
        )
    await session.commit()


async def _reemplazar_plazos(session: AsyncSession, causa: CausaFamilia, tabla: dict) -> None:
    await session.execute(delete(PlazoFamilia).where(PlazoFamilia.causa_familia_id == causa.id))
    vistos: set[str] = set()
    for fila in tabla.get("filas", []):
        v = fila["valores"]
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        session.add(
            PlazoFamilia(
                causa_familia_id=causa.id,
                tipo_plazo=_campo(v, "Tipo Plazo", "Tipo de Plazo"),
                ambito_afectado=_campo(v, "Ámbito Afectado", "Ambito Afectado"),
                fecha_inicio=_campo(v, "Fecha Inicio", "Fec. Inicio"),
                fecha_termino=_campo(v, "Fecha Término", "Fecha Termino", "Fec. Término"),
                duracion=_campo(v, "Duración", "Duracion"),
                estado=_campo(v, "Estado"),
                tramite=_campo(v, "Trámite", "Tramite"),
                fecha_suspension=_campo(v, "Fecha Suspensión", "Fecha Suspension"),
                fecha_reactivacion=_campo(v, "Fecha Reactivación", "Fecha Reactivacion"),
                contenido_hash=h,
            )
        )
    await session.commit()


async def _reemplazar_notificaciones(session: AsyncSession, causa: CausaFamilia, tabla: dict) -> None:
    await session.execute(delete(NotificacionFamilia).where(NotificacionFamilia.causa_familia_id == causa.id))
    vistos: set[str] = set()
    for fila in tabla.get("filas", []):
        v = fila["valores"]
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        session.add(
            NotificacionFamilia(
                causa_familia_id=causa.id,
                estado_fecha_notif=_campo(
                    v, "Estado y Fecha Notif.", "Estado/Fecha Notif.", "Est./Fecha Notif.", "Estado Notif."
                ),
                tipo_notif=_campo(v, "Tipo Notif.", "Tipo Notificación"),
                ente_notif=_campo(v, "Ente Notif.", "Ente Notificador"),
                rit=_campo(v, "RIT", "Rit"),
                ruc=_campo(v, "RUC", "Ruc"),
                fecha_tramite=_campo(v, "Fecha Trámite", "Fec. Trámite"),
                tipo_parte=_campo(v, "Tipo Parte", "Tipo Part."),
                nombre=_campo(v, "Nombre"),
                tramite=_campo(v, "Trámite", "Tramite"),
                certificacion=_campo(v, "Certificación", "Certificacion"),
                contenido_hash=h,
            )
        )
    await session.commit()


async def _reemplazar_diligencias(
    session: AsyncSession, sesion_pjud, causa: CausaFamilia, tabla: dict
) -> bool:
    """Best-effort (como los exhortos de civil): no se conto con una causa real con
    diligencias con documento durante el desarrollo. `doc_solicitud` / `doc_respuesta`
    salen de los enlaces de las columnas homonimas. Revisar contra un caso real."""
    previos = set(
        (
            await session.execute(
                select(DiligenciaFamilia.contenido_hash).where(
                    DiligenciaFamilia.causa_familia_id == causa.id
                )
            )
        ).scalars().all()
    )
    await session.execute(delete(DiligenciaFamilia).where(DiligenciaFamilia.causa_familia_id == causa.id))
    vistos: set[str] = set()
    for i, fila in enumerate(tabla.get("filas", []), start=1):
        v = fila["valores"]
        enlaces = fila.get("enlaces", {})
        h = hash_fila(v)
        if h in vistos:
            continue
        vistos.add(h)
        sol_urls = enlaces.get("Doc. Solicitud") or enlaces.get("Solicitud") or []
        resp_urls = enlaces.get("Doc. Respuesta.") or enlaces.get("Doc. Respuesta") or enlaces.get("Respuesta") or []
        doc_sol = doc_resp = None
        if sol_urls:
            doc_sol = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "diligencia", f"diligencia_sol_{i}", sol_urls[0], hash_padre=h
            )
        if resp_urls:
            doc_resp = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "diligencia", f"diligencia_resp_{i}", resp_urls[0], hash_padre=h
            )
        session.add(
            DiligenciaFamilia(
                causa_familia_id=causa.id,
                doc_solicitud_id=doc_sol.id if doc_sol else None,
                doc_respuesta_id=doc_resp.id if doc_resp else None,
                estado_diligencia=_campo(v, "Estado Diligencia", "Estado"),
                tipo_diligencia=_campo(v, "Tipo Diligencia", "Tipo"),
                fecha_tramite=_campo(v, "Fecha Trámite", "Fec. Trámite"),
                contenido_hash=h,
            )
        )
    await session.commit()
    return vistos != previos


# --- Orquestacion ----------------------------------------------------------


async def sincronizar_causa_familia(
    session: AsyncSession,
    sesion_pjud: PjudSessionFamiliaPrivada,
    causa: CausaFamilia,
    *,
    progreso=None,
) -> None:
    async def _rep(texto: str) -> None:
        if progreso is not None:
            await progreso(texto)

    resultado = await sesion_pjud.buscar_y_extraer_privada(
        causa.tipo, causa.rol, causa.anio, progreso=progreso, tribunal_nombre=None
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
    await session.commit()

    hubo_cambios = False

    cuadernos = resultado.get("cuadernos") or []
    secciones = cuadernos[0].get("secciones", {}) if cuadernos else {}

    for nombre, tabla in secciones.items():
        if _es_seccion(nombre, "histor", "movimiento"):
            await _rep("Guardando historia")
            if await _sincronizar_historia(session, sesion_pjud, causa, tabla):
                hubo_cambios = True
        elif _es_seccion(nombre, "litigant"):
            await _rep("Guardando litigantes")
            await _reemplazar_litigantes(session, causa, tabla)
        elif _es_seccion(nombre, "materia"):
            await _rep("Guardando materias")
            await _reemplazar_materias(session, causa, tabla)
        elif _es_seccion(nombre, "plazo"):
            await _rep("Guardando plazos")
            await _reemplazar_plazos(session, causa, tabla)
        elif _es_seccion(nombre, "notificac"):
            await _rep("Guardando notificaciones")
            await _reemplazar_notificaciones(session, causa, tabla)
        elif _es_seccion(nombre, "diligenc"):
            await _rep("Guardando diligencias")
            if await _reemplazar_diligencias(session, sesion_pjud, causa, tabla):
                hubo_cambios = True
        else:
            logger.info("Seccion de Familia no mapeada, se ignora: %r", nombre)

    # --- Cabecera: anexos de la causa (sub-modal) -----------------------------
    submodales = cabecera.get("submodales", {}) or {}
    anexos_sub = None
    for k, v in submodales.items():
        if _es_seccion(k, "anexo"):
            anexos_sub = v
            break
    if anexos_sub:
        await _rep("Guardando anexos de la causa")
        for sub in anexos_sub.get("filas", []):
            v = sub["valores"]
            referencia, fecha = _campo(v, "Referencia"), _campo(v, "Fecha")
            existente = (
                await session.execute(
                    select(AnexoCausaFamilia).where(
                        AnexoCausaFamilia.causa_familia_id == causa.id,
                        AnexoCausaFamilia.referencia == referencia,
                        AnexoCausaFamilia.fecha == fecha,
                    )
                )
            ).scalar_one_or_none()
            urls = sub.get("enlaces", {}).get("Doc.") or []
            if existente is not None:
                if urls and not await _documento_en_disco(session, existente.documento_id):
                    doc = await _obtener_o_descargar_doc(
                        session, sesion_pjud, causa.id, "anexo_causa", f"anexo_{slug(referencia)}",
                        urls[0], referencia=referencia,
                    )
                    if doc is not None and existente.documento_id != doc.id:
                        existente.documento_id = doc.id
                    await session.commit()
                continue
            hubo_cambios = True
            documento_id = None
            if urls:
                doc = await _obtener_o_descargar_doc(
                    session, sesion_pjud, causa.id, "anexo_causa", f"anexo_{slug(referencia)}",
                    urls[0], referencia=referencia,
                )
                documento_id = doc.id if doc else None
            session.add(
                AnexoCausaFamilia(
                    causa_familia_id=causa.id, documento_id=documento_id, fecha=fecha, referencia=referencia
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
        if categoria == "ebook" and not hubo_cambios:
            existente = (
                await session.execute(
                    select(DocumentoFamilia).where(
                        DocumentoFamilia.causa_familia_id == causa.id,
                        DocumentoFamilia.clave_logica == "ebook",
                    )
                )
            ).scalar_one_or_none()
            if existente is not None and _archivo_en_disco(existente.ruta_archivo):
                continue
        await _obtener_o_descargar_doc(session, sesion_pjud, causa.id, categoria, categoria, d["url"])
        await session.commit()

    logger.info("Sincronizacion de %s completada (hubo_cambios=%s)", causa.rit, hubo_cambios)
