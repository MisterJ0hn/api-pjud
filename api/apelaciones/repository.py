import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.apelaciones.cortes import CORTES, clave_texto
from api.apelaciones.schemas import (
    AnexoItem,
    CausaApelacionesDetalle,
    DocColorItem,
    DocPrincipalItem,
    ExpedientePrimeraItem,
    LiquidanteItem,
    MovimientoAnexoItem,
    MovimientoApelacionesItem,
    MovimientosApelacionesResponse,
    TextoItem,
)
from api.apelaciones.urls import url_publica_documento_apelaciones, url_publica_imagen_apelaciones
from api.civil.schemas import GeoReferenciaImagenItem, GeoReferenciaItem, GeoReferenciaMapa
from api.db.models.apelaciones import (
    AnexoCausaApelaciones,
    CausaApelaciones,
    DocumentoApelaciones,
    LitiganteApelaciones,
    MovimientoApelaciones,
    RegistroApelaciones,
    TextoApelaciones,
)
from api.common.callback import marcar_completo_omitido
from api.db.models.sync_job import SyncJob
from api.errors.exceptions import CampoInvalidoError

CAMPO_ESTADO_SINCRONIZANDO = "Sincronizando"
CAMPO_ESTADO_COMPLETO = "Completo"
CAMPO_ESTADO_ERROR = "Error"


def _clave_libro(libro: str | None) -> str:
    return (libro or "").strip()


async def _filas_por_libro(session: AsyncSession, corte: int, rol: int, anio: int) -> list[CausaApelaciones]:
    return list(
        (
            await session.execute(
                select(CausaApelaciones).where(
                    CausaApelaciones.corte == corte,
                    CausaApelaciones.rol == rol,
                    CausaApelaciones.anio == anio,
                )
            )
        ).scalars()
    )


def _elegir(filas: list[CausaApelaciones], libro: str | None) -> CausaApelaciones | None:
    """Con `libro`: la fila de ese libro (comparado sin acentos/mayusculas). Sin `libro`: la
    unica fila que exista; si hay varias es ambiguo -> `CampoInvalidoError('libro')`."""
    if libro:
        k = clave_texto(libro)
        return next((f for f in filas if clave_texto(f.libro) == k), None)
    if len(filas) > 1:
        raise CampoInvalidoError("libro")
    return filas[0] if filas else None


async def buscar_causa(
    session: AsyncSession, corte: int, libro: str | None, rol: int, anio: int
) -> CausaApelaciones | None:
    return _elegir(await _filas_por_libro(session, corte, rol, anio), libro)


async def obtener_o_crear_causa(
    session: AsyncSession, corte: int, libro: str | None, rol: int, anio: int
) -> CausaApelaciones:
    existente = _elegir(await _filas_por_libro(session, corte, rol, anio), libro)
    if existente is not None:
        return existente

    causa = CausaApelaciones(
        corte=corte, libro=_clave_libro(libro), rol=rol, anio=anio, corte_nombre=CORTES.get(corte),
        estado_sync="Pendiente",
    )
    session.add(causa)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return _elegir(await _filas_por_libro(session, corte, rol, anio), libro)  # type: ignore[return-value]
    await session.refresh(causa)
    return causa


async def intentar_lock_sincronizacion(session: AsyncSession, causa_id, timeout_minutes: int) -> bool:
    """CAS atomico identico al de las demas competencias."""
    ahora = datetime.now(timezone.utc)
    umbral = ahora - timedelta(minutes=timeout_minutes)
    stmt = (
        update(CausaApelaciones)
        .where(
            CausaApelaciones.id == causa_id,
            or_(
                CausaApelaciones.estado_sync != CAMPO_ESTADO_SINCRONIZANDO,
                CausaApelaciones.sync_iniciado_en < umbral,
            ),
        )
        .values(estado_sync=CAMPO_ESTADO_SINCRONIZANDO, sync_iniciado_en=ahora)
        .returning(CausaApelaciones.id)
    )
    fila = (await session.execute(stmt)).first()
    await session.commit()
    return fila is not None


async def encolar_sync_job(
    session: AsyncSession,
    causa_apelaciones_id,
    *,
    rut_cifrado: str | None = None,
    clave_cifrada: str | None = None,
    metodo_login: int | None = None,
    callback_url: str | None = None,
    omitida: bool = False,
) -> int:
    """Encola el job y devuelve su id. `omitida=True` es la sincronizacion que no hace falta
    (causa al dia): el job nace terminado y solo sirve para entregar el callback."""
    job = SyncJob(
        causa_apelaciones_id=causa_apelaciones_id,
        estado="pendiente",
        rut_cifrado=rut_cifrado,
        clave_cifrada=clave_cifrada,
        metodo_login=metodo_login,
        callback_url=callback_url,
    )
    if omitida:
        marcar_completo_omitido(job)
    session.add(job)
    await session.commit()
    job_id = job.id
    await session.execute(text("NOTIFY sync_jobs"))
    await session.commit()
    return job_id


def _url_doc(doc: DocumentoApelaciones | None, causa_id) -> str | None:
    if doc is None:
        return None
    _, ext = os.path.splitext(doc.ruta_archivo)
    return url_publica_documento_apelaciones(causa_id, doc.nombre_archivo, ext or ".pdf")


async def construir_causa_detalle(session: AsyncSession, causa: CausaApelaciones) -> CausaApelacionesDetalle:
    docs = {
        d.id: d
        for d in (
            await session.execute(
                select(DocumentoApelaciones).where(DocumentoApelaciones.causa_apelaciones_id == causa.id)
            )
        ).scalars()
    }
    por_categoria: dict[str, DocumentoApelaciones] = {}
    for d in docs.values():
        por_categoria.setdefault(d.categoria, d)

    def doc_color(doc_id, color) -> DocColorItem | None:
        url = _url_doc(docs.get(doc_id), causa.id)
        return DocColorItem(doc=url, color=color) if url else None

    textos = (
        await session.execute(
            select(TextoApelaciones)
            .where(TextoApelaciones.causa_apelaciones_id == causa.id)
            .order_by(TextoApelaciones.orden)
        )
    ).scalars().all()
    anexos = (
        await session.execute(
            select(AnexoCausaApelaciones)
            .where(AnexoCausaApelaciones.causa_apelaciones_id == causa.id)
            .order_by(AnexoCausaApelaciones.orden)
        )
    ).scalars().all()

    if causa.estado_sync in (CAMPO_ESTADO_COMPLETO, CAMPO_ESTADO_ERROR):
        estado = causa.estado_sync
    else:
        estado = CAMPO_ESTADO_SINCRONIZANDO

    cert = por_categoria.get("certificado_envio")
    ebook = por_categoria.get("ebook")
    tiene_origen = any(
        (causa.origen_rol, causa.origen_caratulado, causa.origen_materia, causa.origen_tribunal)
    )
    return CausaApelacionesDetalle(
        identificador=str(causa.id),
        estado=estado,
        detalle_estado=causa.sync_detalle if estado == CAMPO_ESTADO_SINCRONIZANDO else None,
        ultimo_error=causa.ultimo_error if estado == CAMPO_ESTADO_ERROR else None,
        fecha_ultima_sincronizacion=(
            causa.fecha_ultima_sincronizacion.date().isoformat() if causa.fecha_ultima_sincronizacion else None
        ),
        libro=causa.libro_texto,
        fecha=causa.fecha,
        estado_recurso=causa.estado_recurso,
        estado_procesal=causa.estado_procesal,
        ubicacion=causa.ubicacion,
        recurso=causa.recurso,
        corte=causa.corte_nombre,
        certificado_envio=doc_color(cert.id, causa.certificado_envio_color) if cert else None,
        ebook=doc_color(ebook.id, causa.ebook_color) if ebook else None,
        texto=[
            TextoItem(
                id=t.target_id,
                doc_principal=(
                    DocPrincipalItem(icono=t.doc_principal_icono, color=t.doc_principal_color)
                    if t.doc_principal_icono or t.doc_principal_color
                    else None
                ),
                doc=doc_color(t.documento_id, t.color),
                fecha=t.fecha,
                referencia=t.referencia,
            )
            for t in textos
        ],
        anexo=[
            AnexoItem(
                id=a.target_id,
                doc=doc_color(a.documento_id, a.color),
                codigo=a.codigo,
                tipo_documento=a.tipo_documento,
                cantidad=a.cantidad,
                observacion_documento=a.observacion_documento,
            )
            for a in anexos
        ],
        expediente_primera=(
            ExpedientePrimeraItem(
                causa_origen=causa.origen_rol,
                caratulado=causa.origen_caratulado,
                materia=causa.origen_materia,
                tribunal=causa.origen_tribunal,
                ruc=causa.origen_ruc,
                fecha_ingreso=causa.origen_fecha_ingreso,
                causa_origen_competencia=causa.causa_origen_competencia,
                causa_origen_identificador=str(causa.causa_origen_id) if causa.causa_origen_id else None,
            )
            if tiene_origen
            else None
        ),
    )


async def construir_movimientos(session: AsyncSession, causa: CausaApelaciones) -> MovimientosApelacionesResponse:
    docs_por_id = {
        d.id: d
        for d in (
            await session.execute(
                select(DocumentoApelaciones).where(DocumentoApelaciones.causa_apelaciones_id == causa.id)
            )
        ).scalars()
    }

    def doc_url(documento_id) -> str | None:
        return _url_doc(docs_por_id.get(documento_id), causa.id)

    def imagen_url(documento_id) -> str | None:
        doc = docs_por_id.get(documento_id)
        if doc is None:
            return None
        _, ext = os.path.splitext(doc.ruta_archivo)
        return url_publica_imagen_apelaciones(causa.id, doc.id, ext)

    movs = (
        await session.execute(
            select(MovimientoApelaciones)
            .where(MovimientoApelaciones.causa_apelaciones_id == causa.id)
            .options(
                selectinload(MovimientoApelaciones.docs),
                selectinload(MovimientoApelaciones.anexos),
                selectinload(MovimientoApelaciones.geo_imagenes),
            )
            .order_by(MovimientoApelaciones.orden, MovimientoApelaciones.id)
        )
    ).scalars().all()
    items = []
    for m in movs:
        tiene_mapa = any(v is not None for v in (m.geo_latitud, m.geo_longitud, m.geo_corrector))
        imagenes = [imagen_url(i.documento_id) for i in m.geo_imagenes]
        geo = None
        if tiene_mapa or imagenes:
            geo = GeoReferenciaItem(
                mapa=(
                    GeoReferenciaMapa(latitud=m.geo_latitud, longitud=m.geo_longitud, corrector=m.geo_corrector)
                    if tiene_mapa
                    else None
                ),
                imagenes=[GeoReferenciaImagenItem(img=u) for u in imagenes],
            )
        items.append(
            MovimientoApelacionesItem(
                folio=m.folio,
                doc=[DocColorItem(doc=doc_url(d.documento_id), color=d.color) for d in m.docs],
                anexo=[
                    MovimientoAnexoItem(doc=doc_url(a.documento_id), color=a.color, fecha=a.fecha, referencia=a.referencia)
                    for a in m.anexos
                ],
                tramite=m.tramite,
                descripcion=m.descripcion,
                fecha=m.fecha,
                sala=m.sala,
                estado=m.estado,
                georeferencia=geo,
            )
        )

    litigantes = (
        await session.execute(
            select(LitiganteApelaciones)
            .where(LitiganteApelaciones.causa_apelaciones_id == causa.id)
            .order_by(LitiganteApelaciones.id)
        )
    ).scalars().all()
    registros = (
        await session.execute(
            select(RegistroApelaciones)
            .where(RegistroApelaciones.causa_apelaciones_id == causa.id)
            .order_by(RegistroApelaciones.tipo, RegistroApelaciones.orden)
        )
    ).scalars().all()

    return MovimientosApelacionesResponse(
        movimientos=items,
        liquidantes=[
            LiquidanteItem(sujeto=l.sujeto, rut=l.rut, persona=l.persona, razon_social=l.razon_social)
            for l in litigantes
        ],
        exhortos=[r.datos for r in registros if r.tipo == "exhorto"],
        incompentencia=[r.datos for r in registros if r.tipo == "incompetencia"],
    )
