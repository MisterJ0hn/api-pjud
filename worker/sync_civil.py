"""Orquesta una sincronizacion incremental de una causa civil: llama al scraper async,
y por cada fila extraida decide -- comparando contra lo ya persistido en Postgres -- si
hay que insertar, actualizar o no tocar nada. La regla general (ver plan de diseno):

- Fila nueva (no existe por su clave natural)        -> INSERT (+ descarga si aplica).
- Fila existente con el mismo hash de contenido      -> no se toca la BD ni se descarga
                                                         nada (ahorro real de trabajo).
- Fila existente con hash distinto                   -> UPDATE; el documento asociado
                                                         solo se descarga si no lo
                                                         teniamos ya guardado.

Tablas sin una clave natural estable en el HTML de origen (Litigantes, Notificaciones)
se resuelven con reemplazo completo por cuaderno en cada sync -- son tablas chicas, sin
documentos asociados, asi que no hay costo de red que ahorrar comparando fila a fila, y
evita que un estado antiguo (ej. una notificacion "Pendiente") quede duplicado junto al
nuevo una vez que cambia (ej. a "Efectuada").
"""

import logging
import re
import unicodedata

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.cabecera import AnexoCausa, InformacionReceptor
from api.db.models.causas import Causa, Cuaderno
from api.db.models.documentos import Documento
from api.db.models.movimientos import (
    EscritoResolver,
    Exhorto,
    ExhortoRolDestino,
    ExhortoRolDestinoItem,
    Litigante,
    MovimientoHistoria,
    MovimientoHistoriaAnexo,
    MovimientoHistoriaDoc,
    Notificacion,
)
from scraper.pjud_client_async import CausaNoEncontrada, PjudSessionAsync, PjudSessionPrivada
from worker.idempotencia import extension_por_content_type, hash_fila, ruta_documento, slug

logger = logging.getLogger("pjud.worker.sync_civil")

CATEGORIAS_CABECERA = {
    "texto demanda": "texto_demanda",
    "certificado de envio": "certificado_envio",
    "ebook": "ebook",
}

# Folio de un movimiento de Historia: "33" (normal) o "[6E]" (movimiento de un exhorto,
# numerado aparte y a veces repetido entre exhortos de la misma causa).
_FOLIO_NORMAL_RE = re.compile(r"^(\d+)$")
_FOLIO_EXHORTO_RE = re.compile(r"^\[(\d+)\s*E\]$")


def _parsear_folio(folio_raw: str) -> tuple[str, int, bool] | None:
    """(folio_texto, folio_numerico, es_exhorto) o None si el formato es desconocido."""
    folio_texto = (folio_raw or "").strip()
    m = _FOLIO_NORMAL_RE.match(folio_texto)
    if m:
        return folio_texto, int(m.group(1)), False
    m = _FOLIO_EXHORTO_RE.match(folio_texto)
    if m:
        return f"[{m.group(1)}E]", int(m.group(1)), True
    return None


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return sin_tildes.strip().lower()


async def _obtener_o_descargar_documento(
    session: AsyncSession,
    sesion_pjud: PjudSessionAsync,
    causa_id,
    cuaderno_id,
    categoria: str,
    clave_logica: str,
    rol_fmt: str,
    cuaderno_numero: int | None,
    url: str,
    referencia: str | None = None,
    hash_padre: str | None = None,
) -> Documento | None:
    """Idempotencia real: si ya existe un Documento con esta clave_logica, se devuelve
    sin volver a llamar a PJUD. Solo se descarga cuando realmente no lo teniamos."""
    existente = (
        await session.execute(select(Documento).where(Documento.causa_id == causa_id, Documento.clave_logica == clave_logica))
    ).scalar_one_or_none()
    if existente is not None:
        return existente

    resultado = await sesion_pjud.descargar_bytes(url)
    if resultado is None:
        return None
    content_type, cuerpo = resultado
    ruta = ruta_documento(rol_fmt, clave_logica, cuaderno_numero, extension_por_content_type(content_type))
    with open(ruta, "wb") as f:
        f.write(cuerpo)

    documento = Documento(
        causa_id=causa_id,
        cuaderno_id=cuaderno_id,
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
        # Carrera improbable (mismo proceso, un solo worker) pero defensiva: otra fila
        # de esta misma sincronizacion ya registro la misma clave_logica.
        await session.rollback()
        return (
            await session.execute(select(Documento).where(Documento.causa_id == causa_id, Documento.clave_logica == clave_logica))
        ).scalar_one_or_none()
    return documento


def _asignar_campos_historia(mov: MovimientoHistoria, valores: dict) -> None:
    foja_raw = (valores.get("Foja") or "").strip()
    mov.etapa = valores.get("Etapa")
    mov.tramite = valores.get("Trámite")
    mov.descripcion_tramite = valores.get("Desc. Trámite")
    mov.fecha_tramite = valores.get("Fec. Trámite")
    mov.foja = int(foja_raw) if foja_raw.isdigit() else None


async def _persistir_docs_anexos_historia(
    session: AsyncSession,
    sesion_pjud: PjudSessionAsync,
    causa: Causa,
    cuaderno: Cuaderno,
    mov: MovimientoHistoria,
    fila: dict,
    enlaces: dict,
    clave_base: str,
    rol_fmt: str,
    h: str,
) -> None:
    """(Re)crea las filas movimientos_historia_docs / _anexos del folio. Las descargas
    van por `clave_logica` (idempotencia real): si el documento ya existe no se vuelve a
    pedir a PJUD, asi que borrar+reinsertar estas filas no tiene costo de red."""
    # Un folio puede traer 0, 1 o varios documentos en la columna "Doc." (p. ej. el
    # escrito + su certificado de envio); se guardan todos con orden estable.
    doc_urls = enlaces.get("Doc.") or []
    if doc_urls:
        await session.execute(
            delete(MovimientoHistoriaDoc).where(MovimientoHistoriaDoc.movimiento_id == mov.id)
        )
        for i, url in enumerate(doc_urls, start=1):
            clave = clave_base if i == 1 else f"{clave_base}_doc{i}"
            doc = await _obtener_o_descargar_documento(
                session, sesion_pjud, causa.id, cuaderno.id, "historia", clave,
                rol_fmt, cuaderno.numero, url, hash_padre=h,
            )
            session.add(
                MovimientoHistoriaDoc(
                    movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i
                )
            )

    # Anexos del folio. Dos formas en el HTML de PJUD:
    #  (a) enlaces directos en la celda "Anexo"          -> enlaces["Anexo"].
    #  (b) una carpeta que abre el popup "Anexo solicitud"; el scraper ya lo abrio y
    #      dejo cada fila (doc/fecha/referencia) en fila["anexos_popup"].
    anexos_popup = fila.get("anexos_popup") or []
    anexo_urls = enlaces.get("Anexo") or []
    if anexos_popup:
        await session.execute(
            delete(MovimientoHistoriaAnexo).where(MovimientoHistoriaAnexo.movimiento_id == mov.id)
        )
        for i, a in enumerate(anexos_popup, start=1):
            doc = None
            if a.get("doc"):
                doc = await _obtener_o_descargar_documento(
                    session, sesion_pjud, causa.id, cuaderno.id, "historia_anexo",
                    f"{clave_base}_anexo{i}", rol_fmt, cuaderno.numero, a["doc"],
                    referencia=a.get("referencia"), hash_padre=h,
                )
            session.add(
                MovimientoHistoriaAnexo(
                    movimiento_id=mov.id,
                    documento_id=doc.id if doc else None,
                    orden=i,
                    fecha=a.get("fecha"),
                    referencia=a.get("referencia"),
                )
            )
    elif anexo_urls:
        await session.execute(
            delete(MovimientoHistoriaAnexo).where(MovimientoHistoriaAnexo.movimiento_id == mov.id)
        )
        for i, url in enumerate(anexo_urls, start=1):
            doc = await _obtener_o_descargar_documento(
                session, sesion_pjud, causa.id, cuaderno.id, "historia_anexo", f"{clave_base}_anexo{i}",
                rol_fmt, cuaderno.numero, url,
            )
            session.add(
                MovimientoHistoriaAnexo(movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i)
            )


async def _sincronizar_historia(
    session: AsyncSession, sesion_pjud: PjudSessionAsync, causa: Causa, cuaderno: Cuaderno, tabla: dict, rol_fmt: str
) -> bool:
    """La tabla Historia mezcla, en un orden que solo PJUD conoce, los folios del cuaderno
    (enteros, descendentes) con bloques de movimientos de exhorto ("[NE]", intercalados
    justo despues del folio que los precede). Se persiste la posicion tal cual
    (`orden` = indice de fila) y el repository ordena por ella.

    - Folios normales: clave natural (cuaderno, folio) -> INSERT/UPDATE, se reusa la fila.
    - Filas de exhorto: no tienen clave estable en el HTML (un mismo "[2E] Ingreso
      Exhorto" puede ser identico entre dos exhortos), asi que se reemplazan por completo
      cada sync. Las descargas siguen siendo idempotentes por `clave_logica`
      (`historia_exh{ancla}_{n}`), asi que el borrar+reinsertar no re-descarga nada.
    """
    filas = tabla.get("filas", [])

    # Snapshot de las filas de exhorto ya guardadas (para detectar cambios) + borrado:
    # se reconstruyen enteras mas abajo. Se compara como multiset (dos "[2E] Ingreso
    # Exhorto" de exhortos distintos pueden tener contenido identico).
    exhorto_previas = sorted(
        tuple(r)
        for r in (
            await session.execute(
                select(MovimientoHistoria.folio_texto, MovimientoHistoria.hash_contenido).where(
                    MovimientoHistoria.cuaderno_id == cuaderno.id,
                    MovimientoHistoria.folio_texto.like("[%"),
                )
            )
        ).all()
    )
    await session.execute(
        delete(MovimientoHistoria).where(
            MovimientoHistoria.cuaderno_id == cuaderno.id,
            MovimientoHistoria.folio_texto.like("[%"),
        )
    )
    await session.commit()

    hubo_cambios = False
    exhorto_nuevas: list[tuple[str, str]] = []
    ultimo_folio_normal: int | None = None

    for idx, fila in enumerate(filas):
        valores = fila["valores"]
        enlaces = fila.get("enlaces", {})
        folio_parseado = _parsear_folio(valores.get("Folio") or "")
        if folio_parseado is None:
            logger.warning("Folio de historia con formato inesperado %r; se omite", valores.get("Folio"))
            continue
        folio_texto, folio, es_exhorto = folio_parseado
        h = hash_fila(valores)

        if es_exhorto:
            exhorto_nuevas.append((folio_texto, h))
            # Ancla = folio normal inmediatamente anterior; identifica el exhorto (dos
            # exhortos distintos rara vez comparten el mismo folio previo) y lo ubica en
            # el orden. `folio` (el N de "[NE]") es unico dentro de un mismo bloque.
            ancla = ultimo_folio_normal if ultimo_folio_normal is not None else 0
            clave_base = f"historia_exh{ancla}_{folio}"
            mov = MovimientoHistoria(
                cuaderno_id=cuaderno.id,
                folio=folio,
                folio_texto=folio_texto,
                hash_contenido=h,
                orden=idx,
            )
            _asignar_campos_historia(mov, valores)
            session.add(mov)
            await session.flush()
            await _persistir_docs_anexos_historia(
                session, sesion_pjud, causa, cuaderno, mov, fila, enlaces, clave_base, rol_fmt, h
            )
            await session.commit()
            continue

        ultimo_folio_normal = folio

        existente = (
            await session.execute(
                select(MovimientoHistoria).where(
                    MovimientoHistoria.cuaderno_id == cuaderno.id,
                    MovimientoHistoria.folio_texto == folio_texto,
                )
            )
        ).scalar_one_or_none()

        if existente is not None and existente.hash_contenido == h:
            # Aunque el texto de la fila no cambio, reprocesa si en BD faltan documentos
            # del folio (p. ej. datos de una version que solo guardaba el primero).
            n_docs = (
                await session.execute(
                    select(func.count())
                    .select_from(MovimientoHistoriaDoc)
                    .where(MovimientoHistoriaDoc.movimiento_id == existente.id)
                )
            ).scalar_one()
            if n_docs == len(enlaces.get("Doc.") or []):
                # Sin cambios de contenido; solo puede haberse movido de posicion (PJUD
                # agrego folios/exhortos arriba). Eso no es un "cambio" que amerite
                # re-descargar nada.
                if existente.orden != idx:
                    existente.orden = idx
                    await session.commit()
                continue
            logger.info(
                "Folio %s: %d/%d documentos en BD, se recompletan",
                folio_texto, n_docs, len(enlaces.get("Doc.") or []),
            )

        hubo_cambios = True
        if existente is None:
            existente = MovimientoHistoria(
                cuaderno_id=cuaderno.id, folio=folio, folio_texto=folio_texto, hash_contenido=h, orden=idx
            )
            session.add(existente)
            await session.flush()

        existente.orden = idx
        _asignar_campos_historia(existente, valores)
        existente.hash_contenido = h
        await session.flush()
        await _persistir_docs_anexos_historia(
            session, sesion_pjud, causa, cuaderno, existente, fila, enlaces,
            f"historia_folio{folio}", rol_fmt, h,
        )
        await session.commit()

    if sorted(exhorto_nuevas) != exhorto_previas:
        hubo_cambios = True
    return hubo_cambios


async def _reemplazar_litigantes(session: AsyncSession, cuaderno: Cuaderno, tabla: dict) -> None:
    await session.execute(delete(Litigante).where(Litigante.cuaderno_id == cuaderno.id))
    for fila in tabla.get("filas", []):
        v = fila["valores"]
        session.add(
            Litigante(
                cuaderno_id=cuaderno.id,
                participante=v.get("Participante"),
                rut=v.get("Rut"),
                persona=v.get("Persona"),
                razon_social=v.get("Nombre o Razón Social"),
            )
        )
    await session.commit()


async def _reemplazar_notificaciones(session: AsyncSession, cuaderno: Cuaderno, tabla: dict) -> None:
    await session.execute(delete(Notificacion).where(Notificacion.cuaderno_id == cuaderno.id))
    for fila in tabla.get("filas", []):
        v = fila["valores"]
        session.add(
            Notificacion(
                cuaderno_id=cuaderno.id,
                rol=v.get("ROL"),
                estado_notificacion=v.get("Est. Notif."),
                tipo_notificacion=v.get("Tipo Notif."),
                fecha_tramite=v.get("Fecha Trámite"),
                tipo_part=v.get("Tipo Part."),
                nombre=v.get("Nombre"),
                tramite=v.get("Trámite"),
                observacion_fallida=v.get("Obs. Fallida"),
                contenido_hash=hash_fila(v),
            )
        )
    await session.commit()


async def _sincronizar_escritos_resolver(
    session: AsyncSession, sesion_pjud: PjudSessionAsync, causa: Causa, cuaderno: Cuaderno, tabla: dict, rol_fmt: str
) -> bool:
    hubo_cambios = False
    for fila in tabla.get("filas", []):
        valores = fila["valores"]
        enlaces = fila.get("enlaces", {})
        h = hash_fila(valores)
        existente = (
            await session.execute(
                select(EscritoResolver).where(EscritoResolver.cuaderno_id == cuaderno.id, EscritoResolver.contenido_hash == h)
            )
        ).scalar_one_or_none()
        if existente is not None:
            continue  # mismo escrito ya registrado (mismo contenido) -> no se toca nada

        hubo_cambios = True
        clave = f"escrito_{slug(valores.get('Fecha de Ingreso'))}_{slug(valores.get('Tipo Escrito'))}"
        doc_urls = enlaces.get("Doc.") or []
        documento_id = None
        if doc_urls:
            doc = await _obtener_o_descargar_documento(
                session, sesion_pjud, causa.id, cuaderno.id, "escrito_resolver", clave, rol_fmt, cuaderno.numero, doc_urls[0], hash_padre=h
            )
            documento_id = doc.id if doc else None

        session.add(
            EscritoResolver(
                cuaderno_id=cuaderno.id,
                documento_id=documento_id,
                fecha_ingreso=valores.get("Fecha de Ingreso"),
                tipo_escrito=valores.get("Tipo Escrito"),
                solicitante=valores.get("Solicitante"),
                contenido_hash=h,
            )
        )
        await session.commit()
    return hubo_cambios


async def _sincronizar_exhortos(
    session: AsyncSession, sesion_pjud: PjudSessionAsync, causa: Causa, cuaderno: Cuaderno, tabla: dict, rol_fmt: str
) -> bool:
    """Best-effort: no se conto con una causa real con exhortos con contenido durante el
    desarrollo (ver plan), asi que la agrupacion en rol_destino[] usa el propio texto de
    la celda "Rol Destino" como nombre del (unico) grupo, y cada enlace encontrado en esa
    celda se registra como un item de ese grupo. Revisar contra un caso real."""
    hubo_cambios = False
    for fila in tabla.get("filas", []):
        valores = fila["valores"]
        enlaces = fila.get("enlaces", {})
        rol_origen = valores.get("Rol Origen")
        tipo_exhorto = valores.get("Tipo Exhorto")

        existente = (
            await session.execute(
                select(Exhorto).where(
                    Exhorto.cuaderno_id == cuaderno.id, Exhorto.rol_origen == rol_origen, Exhorto.tipo_exhorto == tipo_exhorto
                )
            )
        ).scalar_one_or_none()
        if existente is None:
            existente = Exhorto(cuaderno_id=cuaderno.id, rol_origen=rol_origen, tipo_exhorto=tipo_exhorto)
            session.add(existente)
            hubo_cambios = True

        existente.fecha_ordena_exhorto = valores.get("Fecha Ordena Exhorto")
        existente.fecha_ingreso_exhorto = valores.get("Fecha Ingreso Exhorto")
        existente.tribunal_destino = valores.get("Tribunal Destino")
        existente.estado_exhorto = valores.get("Estado Exhorto")
        await session.flush()

        rol_destino_urls = enlaces.get("Rol Destino") or []
        if rol_destino_urls:
            await session.execute(delete(ExhortoRolDestino).where(ExhortoRolDestino.exhorto_id == existente.id))
            grupo = ExhortoRolDestino(exhorto_id=existente.id, nombre=valores.get("Rol Destino") or "destino")
            session.add(grupo)
            await session.flush()
            for i, url in enumerate(rol_destino_urls, start=1):
                doc = await _obtener_o_descargar_documento(
                    session, sesion_pjud, causa.id, cuaderno.id, "exhorto",
                    f"exhorto_{slug(rol_origen)}_{slug(tipo_exhorto)}_item{i}", rol_fmt, cuaderno.numero, url,
                )
                session.add(ExhortoRolDestinoItem(rol_destino_id=grupo.id, documento_id=doc.id if doc else None, orden=i))
            hubo_cambios = True
        await session.commit()
    return hubo_cambios


async def sincronizar_causa(
    session: AsyncSession,
    sesion_pjud: PjudSessionAsync | PjudSessionPrivada,
    causa: Causa,
    *,
    privada: bool = False,
    progreso=None,
) -> None:
    """`progreso`: callback opcional `async (texto: str) -> None` para reportar el paso
    actual (se expone en `consultar_civil` como `detalle_estado`). Granularidad por
    seccion, no por documento."""

    async def _rep(texto: str) -> None:
        if progreso is not None:
            await progreso(texto)

    rol_fmt = causa.rol_formateado
    if privada:
        # Causa privada: ya se busca dentro de "Mis Causas" -> "Civil" filtrando solo por
        # Rit / Rol / Anio (no hay Corte ni Juzgado). El detalle extraido tiene la misma
        # forma que el de la Consulta Unificada, asi que el resto del flujo no cambia.
        resultado = await sesion_pjud.buscar_y_extraer_privada(
            causa.tipo, causa.rol, causa.anio, progreso=progreso
        )
    else:
        resultado = await sesion_pjud.buscar_y_extraer(
            causa.competencia, str(causa.corte), str(causa.tribunal), causa.tipo, causa.rol, causa.anio,
            progreso=progreso,
        )

    if not resultado.get("encontrada"):
        raise CausaNoEncontrada(f"Causa {rol_fmt} no encontrada en PJUD")
    if resultado.get("error"):
        raise RuntimeError(resultado["error"])

    await _rep("Guardando cabecera")
    cabecera = resultado["cabecera"]
    campos = cabecera.get("campos", {})
    causa.fecha_ingreso = campos.get("F. Ing.") or causa.fecha_ingreso
    causa.est_adm = campos.get("Est. Adm.") or causa.est_adm
    causa.proceso = campos.get("Proc.") or causa.proceso
    causa.ubicacion = campos.get("Ubicación") or causa.ubicacion
    causa.estado_proceso = campos.get("Estado Proc.") or causa.estado_proceso
    causa.etapa = campos.get("Etapa") or causa.etapa
    causa.tribunal_nombre = campos.get("Tribunal") or causa.tribunal_nombre
    await session.commit()

    hubo_cambios = False

    # --- Cuadernos y sus pestanas -----------------------------------------------
    for c in resultado.get("cuadernos", []):
        cuaderno = (
            await session.execute(select(Cuaderno).where(Cuaderno.causa_id == causa.id, Cuaderno.numero == c["numero"]))
        ).scalar_one_or_none()
        if cuaderno is None:
            cuaderno = Cuaderno(causa_id=causa.id, numero=c["numero"], nombre=c["nombre"])
            session.add(cuaderno)
        else:
            cuaderno.nombre = c["nombre"]
        await session.commit()
        await session.refresh(cuaderno)

        secciones = c.get("secciones", {})
        if "Historia" in secciones:
            await _rep(f"Guardando historia de cuaderno {cuaderno.nombre}")
            if await _sincronizar_historia(session, sesion_pjud, causa, cuaderno, secciones["Historia"], rol_fmt):
                hubo_cambios = True
        if "Litigantes" in secciones:
            await _rep(f"Guardando litigantes de cuaderno {cuaderno.nombre}")
            await _reemplazar_litigantes(session, cuaderno, secciones["Litigantes"])
        if "Notificaciones" in secciones:
            await _rep(f"Guardando notificaciones de cuaderno {cuaderno.nombre}")
            await _reemplazar_notificaciones(session, cuaderno, secciones["Notificaciones"])
        if "Escritos por Resolver" in secciones:
            await _rep(f"Guardando escritos por resolver de cuaderno {cuaderno.nombre}")
            if await _sincronizar_escritos_resolver(session, sesion_pjud, causa, cuaderno, secciones["Escritos por Resolver"], rol_fmt):
                hubo_cambios = True
        if "Exhortos" in secciones:
            await _rep(f"Guardando exhortos de cuaderno {cuaderno.nombre}")
            if await _sincronizar_exhortos(session, sesion_pjud, causa, cuaderno, secciones["Exhortos"], rol_fmt):
                hubo_cambios = True

    # --- Cabecera: anexos_causa, informacion_receptor ----------------------------
    if cabecera.get("submodales"):
        await _rep("Guardando anexos de la causa")
    for sub in cabecera.get("submodales", {}).get("Anexos de la causa", {}).get("filas", []):
        v = sub["valores"]
        referencia, fecha = v.get("Referencia"), v.get("Fecha")
        existente = (
            await session.execute(
                select(AnexoCausa).where(AnexoCausa.causa_id == causa.id, AnexoCausa.referencia == referencia, AnexoCausa.fecha == fecha)
            )
        ).scalar_one_or_none()
        if existente is not None:
            continue
        hubo_cambios = True
        urls = sub.get("enlaces", {}).get("Doc.") or []
        documento_id = None
        if urls:
            doc = await _obtener_o_descargar_documento(
                session, sesion_pjud, causa.id, None, "anexo_causa", f"anexo_{slug(referencia)}", rol_fmt, None, urls[0], referencia=referencia
            )
            documento_id = doc.id if doc else None
        session.add(AnexoCausa(causa_id=causa.id, documento_id=documento_id, fecha=fecha, referencia=referencia))
        await session.commit()

    for sub in cabecera.get("submodales", {}).get("Información notificaciones receptor", {}).get("filas", []):
        v = sub["valores"]
        cuaderno_nombre, fecha_retiro = v.get("Cuaderno"), v.get("Fecha Retiro")
        existente = (
            await session.execute(
                select(InformacionReceptor).where(
                    InformacionReceptor.causa_id == causa.id,
                    InformacionReceptor.cuaderno_nombre == cuaderno_nombre,
                    InformacionReceptor.fecha_retiro == fecha_retiro,
                )
            )
        ).scalar_one_or_none()
        if existente is not None:
            continue
        session.add(
            InformacionReceptor(
                causa_id=causa.id,
                cuaderno_nombre=cuaderno_nombre,
                datos_retiro=v.get("Datos del Retiro"),
                fecha_retiro=fecha_retiro,
                estado=v.get("Estado"),
            )
        )
        await session.commit()

    # --- Cabecera: texto_demanda / certificado_envio / ebook ---------------------
    # texto_demanda y certificado_envio se tratan como inmutables una vez obtenidos;
    # ebook se reintenta solo si algo mas en la causa cambio en esta sincronizacion
    # (ver tabla de politicas de descarga en el plan de diseno).
    if cabecera.get("descargas"):
        await _rep("Descargando documentos de la causa")
    for d in cabecera.get("descargas", []):
        categoria = CATEGORIAS_CABECERA.get(_normalizar(d["label"]))
        if categoria is None:
            continue
        if categoria == "ebook" and not hubo_cambios:
            existente = (
                await session.execute(select(Documento).where(Documento.causa_id == causa.id, Documento.clave_logica == "ebook"))
            ).scalar_one_or_none()
            if existente is not None:
                continue
        await _obtener_o_descargar_documento(session, sesion_pjud, causa.id, None, categoria, categoria, rol_fmt, None, d["url"])
        await session.commit()

    logger.info("Sincronizacion de %s completada (hubo_cambios=%s)", rol_fmt, hubo_cambios)
