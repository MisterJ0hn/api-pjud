"""Sincronizacion incremental de un recurso de la Corte de Apelaciones. Analoga a
`worker/sync_penal.py` pero sin cuadernos: el modal trae cabecera (Recurso), Expediente
Primera Instancia (causa origen) y las pestanas Movimientos / Litigantes / Exhortos /
Incompetencia (ver el docstring de `scraper.pjud_client_async._ExtraccionApelaciones`, que
detalla que esta CONFIRMADO en vivo y que no).

Politica de persistencia:
- Movimientos: clave natural (causa, folio, ocurrencia) + `hash_contenido`; una fila sin
  cambios no se reprocesa (solo se refrescan los colores de los iconos).
- Litigantes / Texto / Anexo / Exhortos / Incompetencia: reemplazo completo por causa.
- Documentos: idempotentes por `clave_logica`; no se re-descargan si el archivo sigue en disco.
"""

import logging
import re

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.apelaciones.cortes import clave_texto
from api.db.models.apelaciones import (
    AnexoCausaApelaciones,
    CausaApelaciones,
    DocumentoApelaciones,
    LitiganteApelaciones,
    MovimientoApelaciones,
    MovimientoApelacionesAnexo,
    MovimientoApelacionesDoc,
    MovimientoApelacionesGeoImagen,
    RegistroApelaciones,
    TextoApelaciones,
)
from api.db.models.causas import Causa
from scraper.pjud_client_async import CausaNoEncontrada
from worker.idempotencia import color_en, colores_columna, extension_por_content_type, hash_fila, ruta_documento
from worker.sync_civil import _archivo_en_disco

logger = logging.getLogger("pjud.worker.sync_apelaciones")


class LibroAmbiguoError(Exception):
    """El rol/anio existe en varios libros de la corte (o el libro pedido no existe): error
    terminal, reintentar no cambia nada. El usuario debe indicar `libro`."""


def _campo(campos: dict, *claves: str) -> str | None:
    for k in claves:
        v = campos.get(k)
        if v:
            return v
    return None


def _hex(color: str | None) -> str | None:
    """'rgb(173, 84, 84)' -> '#ad5454'; un '#rrggbb' se devuelve en minusculas."""
    if not color:
        return None
    m = re.match(r"^\s*rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", color)
    if m:
        return "#" + "".join(f"{int(n):02x}" for n in m.groups())
    return color.strip().lower() or None


def _primera_columna(dic: dict | None, *nombres: str):
    """Valor de la primera columna (por nombre normalizado, con o sin punto) con contenido."""
    dic = dic or {}
    objetivo = {clave_texto(n).rstrip(". ") for n in nombres}
    for k, v in dic.items():
        if v and clave_texto(k).rstrip(". ") in objetivo:
            return v
    return None


def _valor(valores: dict, *nombres: str) -> str | None:
    objetivo = {clave_texto(n) for n in nombres}
    for k, v in valores.items():
        if v and clave_texto(k) in objetivo:
            return v
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
) -> DocumentoApelaciones | None:
    stmt = select(DocumentoApelaciones).where(
        DocumentoApelaciones.causa_apelaciones_id == causa_id,
        DocumentoApelaciones.clave_logica == clave_logica,
    )
    existente = (await session.execute(stmt)).scalar_one_or_none()
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

    documento = DocumentoApelaciones(
        causa_apelaciones_id=causa_id,
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
        return (await session.execute(stmt)).scalar_one_or_none()
    return documento


# --- Cabecera: Recurso, Texto, Anexo, Expediente de primera instancia -----------


def _tabla_submodal(cabecera: dict, *prefijos: str) -> dict | None:
    for label, tabla in (cabecera.get("submodales") or {}).items():
        if any(clave_texto(label).startswith(p) for p in prefijos):
            return tabla
    return None


def _id_target(fila: dict, orden: int) -> int:
    """Atributo `target` del form de la fila (id real de PJUD para la lista); si no hay, la
    posicion."""
    for lista in (fila.get("targets") or {}).values():
        for t in lista:
            if str(t).isdigit():
                return int(t)
    return orden


def _primer_enlace(fila: dict) -> tuple[str | None, str | None]:
    """(url, color) del primer enlace GET de la fila, de la columna que lo tenga."""
    enlaces = fila.get("enlaces") or {}
    colores = fila.get("colores") or {}
    for col, urls in enlaces.items():
        if urls:
            return urls[0], _hex(color_en(colores.get(col), 0))
    return None, None


def _icono_doc_principal(fila: dict) -> tuple[str | None, str | None]:
    """Icono de la columna "Doc. Principal" (fa-check / fa-times) y su color."""
    clases = fila.get("iconos_cls") or {}
    colores = fila.get("iconos_color") or {}
    for col, cls in clases.items():
        if clave_texto(col).startswith("doc principal"):
            m = re.search(r"\bfa-(?!lg\b|fw\b|[2-5]x\b)[\w-]+", cls or "")
            return (m.group(0) if m else None), _hex(colores.get(col))
    return None, None


async def _reemplazar_textos(session: AsyncSession, sesion_pjud, causa: CausaApelaciones, cabecera: dict) -> None:
    tabla = _tabla_submodal(cabecera, "texto")
    await session.execute(delete(TextoApelaciones).where(TextoApelaciones.causa_apelaciones_id == causa.id))
    for orden, fila in enumerate((tabla or {}).get("filas", []), start=1):
        v = fila.get("valores") or {}
        h = hash_fila(v)
        url, color = _primer_enlace(fila)
        target = _id_target(fila, orden)
        doc = None
        if url:
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "texto", f"texto_{target}", url, referencia=_valor(v, "Referencia"),
                hash_padre=h,
            )
        icono, color_icono = _icono_doc_principal(fila)
        session.add(
            TextoApelaciones(
                causa_apelaciones_id=causa.id,
                orden=orden,
                target_id=target,
                doc_principal_icono=icono,
                doc_principal_color=color_icono,
                documento_id=doc.id if doc else None,
                color=color,
                fecha=_valor(v, "Fecha"),
                referencia=_valor(v, "Referencia"),
                contenido_hash=h,
            )
        )
    await session.commit()


async def _reemplazar_anexos_causa(session: AsyncSession, sesion_pjud, causa: CausaApelaciones, cabecera: dict) -> None:
    tabla = _tabla_submodal(cabecera, "anexo")
    await session.execute(delete(AnexoCausaApelaciones).where(AnexoCausaApelaciones.causa_apelaciones_id == causa.id))
    for orden, fila in enumerate((tabla or {}).get("filas", []), start=1):
        v = fila.get("valores") or {}
        h = hash_fila(v)
        url, color = _primer_enlace(fila)
        target = _id_target(fila, orden)
        doc = None
        if url:
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "anexo_causa", f"anexo_causa_{target}", url, hash_padre=h
            )
        session.add(
            AnexoCausaApelaciones(
                causa_apelaciones_id=causa.id,
                orden=orden,
                target_id=target,
                documento_id=doc.id if doc else None,
                color=color,
                codigo=_valor(v, "Código", "Codigo", "Cód.", "Cod."),
                tipo_documento=_valor(v, "Tipo Documento", "Tipo de Documento", "Tipo"),
                cantidad=_valor(v, "Cantidad", "Cant."),
                observacion_documento=_valor(v, "Observación del Documento", "Observacion del Documento", "Observación Documento", "Observacion Documento", "Observación", "Observacion"),
                contenido_hash=h,
            )
        )
    await session.commit()


def _resolver_origen_civil(causas: list[Causa], tribunal_origen: str | None) -> Causa | None:
    """De las causas civiles con el mismo rol formateado, la del tribunal de origen (nombre
    normalizado: 'º' ~ '°', espacios y mayusculas). Con un unico candidato y sin nombre de
    tribunal para comparar, se toma ese; con varios y sin match no se adivina."""
    def norm(s: str | None) -> str:
        return re.sub(r"\s+", " ", (s or "").lower().replace("º", "°")).strip()

    if tribunal_origen:
        for c in causas:
            if norm(c.tribunal_nombre) == norm(tribunal_origen):
                return c
        return None
    return causas[0] if len(causas) == 1 else None


async def _vincular_causa_origen(session: AsyncSession, causa: CausaApelaciones) -> None:
    """Relaciona el recurso con la causa de primera instancia si ya existe en nuestro sistema
    (hoy solo Civil: es la unica competencia de la que tenemos tribunal_nombre + rol_formateado
    para comparar). No crea ni encola nada: si no esta, queda solo el texto del expediente."""
    causa.causa_origen_competencia = None
    causa.causa_origen_id = None
    m = re.match(r"^\s*([A-Za-z])\s*-\s*(\d+)\s*-\s*(\d{4})\s*$", causa.origen_rol or "")
    if not m or not clave_texto(causa.libro_texto or causa.libro).startswith("civil"):
        return
    rol_fmt = f"{m.group(1).upper()}-{int(m.group(2))}-{m.group(3)}"
    candidatas = list((await session.execute(select(Causa).where(Causa.rol_formateado == rol_fmt))).scalars())
    origen = _resolver_origen_civil(candidatas, causa.origen_tribunal)
    if origen is not None:
        causa.causa_origen_competencia = "civil"
        causa.causa_origen_id = origen.id
        logger.info("Recurso %s vinculado a la causa civil %s (%s)", causa.rit, rol_fmt, origen.id)


# --- Movimientos ---------------------------------------------------------------


def _docs_fila(fila: dict) -> list[dict]:
    """Documentos de la columna "Doc." de un movimiento, en orden DOM: links GET primero y
    forms POST despues. Cada item: {"url", "post", "color"}."""
    items: list[dict] = []
    enlaces, posts = fila.get("enlaces") or {}, fila.get("posts") or {}
    colores, colores_posts = fila.get("colores") or {}, fila.get("colores_posts") or {}
    k = next((k for k, v in enlaces.items() if v and clave_texto(k).rstrip(". ") in ("doc", "documento")), None)
    for i, url in enumerate(enlaces.get(k) or []):
        items.append({"url": url, "post": None, "color": _hex(color_en(colores.get(k), i))})
    kp = next((k for k, v in posts.items() if v and clave_texto(k).rstrip(". ") in ("doc", "documento")), None)
    for i, post in enumerate(posts.get(kp) or []):
        items.append({"url": None, "post": post, "color": _hex(color_en(colores_posts.get(kp), i))})
    return items


def _parsear_folio(texto: str | None) -> int | None:
    m = re.search(r"\d+", texto or "")
    return int(m.group(0)) if m else None


async def _persistir_detalle_movimiento(
    session: AsyncSession, sesion_pjud, causa: CausaApelaciones, mov: MovimientoApelaciones, fila: dict,
    clave_base: str, h: str,
) -> None:
    docs = _docs_fila(fila)
    await session.execute(delete(MovimientoApelacionesDoc).where(MovimientoApelacionesDoc.movimiento_id == mov.id))
    for i, d in enumerate(docs, start=1):
        clave = clave_base if i == 1 else f"{clave_base}_doc{i}"
        doc = await _obtener_o_descargar_doc(
            session, sesion_pjud, causa.id, "movimiento", clave, d["url"], post=d["post"], hash_padre=h
        )
        session.add(
            MovimientoApelacionesDoc(
                movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i, color=d["color"]
            )
        )

    anexos = fila.get("anexos_popup") or []
    await session.execute(delete(MovimientoApelacionesAnexo).where(MovimientoApelacionesAnexo.movimiento_id == mov.id))
    for i, a in enumerate(anexos, start=1):
        v = a.get("valores") or {}
        referencia = _valor(v, "Referencia")
        doc = None
        if a.get("doc") or a.get("doc_post"):
            doc = await _obtener_o_descargar_doc(
                session, sesion_pjud, causa.id, "movimiento_anexo", f"{clave_base}_anexo{i}",
                url=a.get("doc"), post=a.get("doc_post"), referencia=referencia, hash_padre=h,
            )
        session.add(
            MovimientoApelacionesAnexo(
                movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=i,
                color=_hex(a.get("color")), fecha=_valor(v, "Fecha"), referencia=referencia,
            )
        )

    await session.execute(
        delete(MovimientoApelacionesGeoImagen).where(MovimientoApelacionesGeoImagen.movimiento_id == mov.id)
    )
    geo = fila.get("georeferencia_popup")
    mapa = (geo or {}).get("mapa") or {}
    mov.geo_latitud = mapa.get("latitud")
    mov.geo_longitud = mapa.get("longitud")
    mov.geo_corrector = mapa.get("corrector")
    for j, img in enumerate((geo or {}).get("imagenes") or [], start=1):
        # Clave por posicion (no por hash): la lista se reemplaza completa en cada sync.
        doc = await _obtener_o_descargar_doc(
            session, sesion_pjud, causa.id, "movimiento_geo_imagen", f"{clave_base}_geo{j}",
            url=img.get("src"), referencia=img.get("alt"), hash_padre=h,
        )
        session.add(MovimientoApelacionesGeoImagen(movimiento_id=mov.id, documento_id=doc.id if doc else None, orden=j))


async def _refrescar_colores(session: AsyncSession, mov: MovimientoApelaciones, fila: dict) -> None:
    colores = [d["color"] for d in _docs_fila(fila)]
    if colores:
        rows = (
            await session.execute(select(MovimientoApelacionesDoc).where(MovimientoApelacionesDoc.movimiento_id == mov.id))
        ).scalars().all()
        for r in rows:
            nuevo = color_en(colores, r.orden - 1)
            if r.color != nuevo:
                r.color = nuevo
    anexos = fila.get("anexos_popup") or []
    if anexos:
        rows = (
            await session.execute(
                select(MovimientoApelacionesAnexo).where(MovimientoApelacionesAnexo.movimiento_id == mov.id)
            )
        ).scalars().all()
        for r in rows:
            nuevo = _hex(color_en([a.get("color") for a in anexos], r.orden - 1))
            if r.color != nuevo:
                r.color = nuevo


async def _sincronizar_movimientos(
    session: AsyncSession, sesion_pjud, causa: CausaApelaciones, seccion: dict
) -> bool:
    hubo_cambios = False
    ocurrencias: dict[int, int] = {}
    vistos: set[tuple[int, int]] = set()

    for idx, fila in enumerate(seccion.get("filas", []), start=1):
        valores = fila.get("valores") or {}
        folio = _parsear_folio(_valor(valores, "Folio"))
        if folio is None:
            logger.warning("Movimiento con folio inesperado %r; se omite", valores.get("Folio"))
            continue
        ocurrencias[folio] = ocurrencias.get(folio, 0) + 1
        ocurrencia = ocurrencias[folio]
        vistos.add((folio, ocurrencia))
        h = hash_fila(valores)
        clave_base = f"mov_f{folio}" + (f"_o{ocurrencia}" if ocurrencia > 1 else "")

        existente = (
            await session.execute(
                select(MovimientoApelaciones).where(
                    MovimientoApelaciones.causa_apelaciones_id == causa.id,
                    MovimientoApelaciones.folio == folio,
                    MovimientoApelaciones.ocurrencia == ocurrencia,
                )
            )
        ).scalar_one_or_none()

        faltan_docs = False
        if existente is not None and _docs_fila(fila):
            faltan_docs = (
                await session.execute(
                    select(MovimientoApelacionesDoc.id)
                    .where(
                        MovimientoApelacionesDoc.movimiento_id == existente.id,
                        MovimientoApelacionesDoc.documento_id.is_not(None),
                    )
                    .limit(1)
                )
            ).first() is None
        if existente is not None and existente.hash_contenido == h and not faltan_docs:
            existente.orden = idx
            await _refrescar_colores(session, existente, fila)
            await session.commit()
            continue

        hubo_cambios = True
        if existente is None:
            existente = MovimientoApelaciones(
                causa_apelaciones_id=causa.id, folio=folio, ocurrencia=ocurrencia, orden=idx, hash_contenido=h
            )
            session.add(existente)
            await session.flush()
        existente.orden = idx
        existente.tramite = _valor(valores, "Trámite", "Tramite")
        existente.descripcion = _valor(valores, "Descripción", "Descripcion")
        existente.fecha = _valor(valores, "Fecha")
        existente.sala = _valor(valores, "Sala")
        existente.estado = _valor(valores, "Estado")
        existente.hash_contenido = h
        await session.flush()
        await _persistir_detalle_movimiento(session, sesion_pjud, causa, existente, fila, clave_base, h)
        await session.commit()

    # Movimientos que PJUD ya no muestra.
    guardados = (
        await session.execute(
            select(MovimientoApelaciones).where(MovimientoApelaciones.causa_apelaciones_id == causa.id)
        )
    ).scalars().all()
    for m in guardados:
        if (m.folio, m.ocurrencia) not in vistos:
            await session.delete(m)
            hubo_cambios = True
    await session.commit()
    return hubo_cambios


async def _reemplazar_litigantes(session: AsyncSession, causa: CausaApelaciones, seccion: dict) -> None:
    await session.execute(delete(LitiganteApelaciones).where(LitiganteApelaciones.causa_apelaciones_id == causa.id))
    vistos: set[str] = set()
    for fila in seccion.get("filas", []):
        v = fila.get("valores") or {}
        h = hash_fila(v)
        if h in vistos or not any(v.values()):
            continue
        vistos.add(h)
        session.add(
            LitiganteApelaciones(
                causa_apelaciones_id=causa.id,
                sujeto=_valor(v, "Sujeto"),
                rut=_valor(v, "Rut"),
                persona=_valor(v, "Persona"),
                razon_social=_valor(v, "Nombre o Razón Social", "Nombre o Razon Social", "Razón Social", "Nombre"),
            )
        )
    await session.commit()


async def _reemplazar_registros(session: AsyncSession, causa: CausaApelaciones, tipo: str, seccion: dict) -> None:
    await session.execute(
        delete(RegistroApelaciones).where(
            RegistroApelaciones.causa_apelaciones_id == causa.id, RegistroApelaciones.tipo == tipo
        )
    )
    orden = 0
    for fila in seccion.get("filas", []):
        datos = {k: v for k, v in (fila.get("valores") or {}).items() if v}
        if not datos:
            continue
        orden += 1
        session.add(RegistroApelaciones(causa_apelaciones_id=causa.id, tipo=tipo, orden=orden, datos=datos))
    await session.commit()


# --- Orquestacion ----------------------------------------------------------------


async def sincronizar_causa_apelaciones(
    session: AsyncSession,
    sesion_pjud,
    causa: CausaApelaciones,
    *,
    privada: bool = False,
    progreso=None,
) -> None:
    async def _rep(texto: str) -> None:
        if progreso is not None:
            await progreso(texto)

    if privada:
        resultado = await sesion_pjud.buscar_y_extraer_privada(causa.libro, causa.rol, causa.anio, progreso=progreso)
    else:
        resultado = await sesion_pjud.buscar_y_extraer_apelaciones(
            causa.corte, causa.libro or None, causa.rol, causa.anio, progreso=progreso
        )

    if resultado.get("libros"):
        raise LibroAmbiguoError(
            f"El recurso {causa.rol}-{causa.anio} existe en varios libros de la corte "
            f"({', '.join(resultado['libros'])}); indique `libro` en la solicitud."
            if not causa.libro
            else f"El libro '{causa.libro}' no existe para {causa.rol}-{causa.anio}; "
            f"libros disponibles: {', '.join(resultado['libros'])}."
        )
    if not resultado.get("encontrada"):
        raise CausaNoEncontrada(f"Recurso {causa.libro or '?'}-{causa.rol}-{causa.anio} no encontrado en PJUD")
    if resultado.get("error"):
        raise RuntimeError(resultado["error"])

    await _rep("Guardando cabecera")
    cabecera = resultado["cabecera"]
    campos = cabecera.get("campos", {})
    logger.info("Cabecera apelaciones (campos crudos): %r", campos)

    libro_texto = _campo(campos, "Libro")
    causa.libro_texto = libro_texto or causa.libro_texto
    # El libro real sale del texto "Civil - 23414 - 2026"; la fila de resultados tambien lo trae.
    libro_real = resultado.get("libro_fila") or (
        re.sub(r"\s*-\s*\d+\s*-\s*\d+\s*$", "", libro_texto).strip() if libro_texto else None
    )
    if libro_real and not causa.libro:
        ya = (
            await session.execute(
                select(CausaApelaciones.id).where(
                    CausaApelaciones.corte == causa.corte,
                    CausaApelaciones.libro == libro_real,
                    CausaApelaciones.rol == causa.rol,
                    CausaApelaciones.anio == causa.anio,
                    CausaApelaciones.id != causa.id,
                )
            )
        ).first()
        if ya is None:
            causa.libro = libro_real
    causa.fecha = _campo(campos, "Fecha") or causa.fecha
    causa.estado_recurso = _campo(campos, "Estado Recurso") or causa.estado_recurso
    causa.estado_procesal = _campo(campos, "Estado Procesal") or causa.estado_procesal
    causa.ubicacion = _campo(campos, "Ubicación", "Ubicacion") or causa.ubicacion
    causa.recurso = _campo(campos, "Recurso") or causa.recurso
    causa.corte_nombre = _campo(campos, "Corte") or causa.corte_nombre

    causa.origen_rol = _campo(campos, "Causa Origen") or causa.origen_rol
    causa.origen_tribunal = _campo(campos, "Tribunal") or causa.origen_tribunal
    causa.origen_caratulado = _campo(campos, "Caratulado", "Carátula") or causa.origen_caratulado
    causa.origen_materia = _campo(campos, "Materia") or causa.origen_materia
    causa.origen_ruc = _campo(campos, "Ruc", "RUC") or causa.origen_ruc
    causa.origen_fecha_ingreso = _campo(campos, "Fecha Ingreso") or causa.origen_fecha_ingreso
    await _vincular_causa_origen(session, causa)
    await session.commit()

    for d in cabecera.get("descargas", []):
        n = clave_texto(d["label"])
        if n.startswith("certificado"):
            categoria = "certificado_envio"
            causa.certificado_envio_color = _hex(d.get("color"))
        elif n.startswith("ebook"):
            categoria = "ebook"
            causa.ebook_color = _hex(d.get("color"))
        else:
            logger.info("Descarga de cabecera no mapeada, se ignora: %r", d["label"])
            continue
        await _rep("Descargando documentos de la causa")
        await _obtener_o_descargar_doc(session, sesion_pjud, causa.id, categoria, categoria, d["url"])
        await session.commit()

    await _rep("Guardando documentos del recurso")
    await _reemplazar_textos(session, sesion_pjud, causa, cabecera)
    await _reemplazar_anexos_causa(session, sesion_pjud, causa, cabecera)

    await _rep("Guardando movimientos")
    hubo_cambios = await _sincronizar_movimientos(session, sesion_pjud, causa, resultado.get("movimientos") or {})
    await _rep("Guardando litigantes")
    await _reemplazar_litigantes(session, causa, resultado.get("litigantes") or {})
    await _reemplazar_registros(session, causa, "exhorto", resultado.get("exhortos") or {})
    await _reemplazar_registros(session, causa, "incompetencia", resultado.get("incompetencia") or {})

    logger.info("Sincronizacion de %s completada (hubo_cambios=%s)", causa.rit, hubo_cambios)
