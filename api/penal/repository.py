import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.civil.schemas import GeoReferenciaImagenItem, GeoReferenciaItem, GeoReferenciaMapa
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
from api.db.models.sync_job import SyncJob
from api.penal.schemas import (
    CausaPenalDetalle,
    CuadernoPenalItem,
    DescripcionTramiteDetalle,
    DescripcionTramiteDocItem,
    HistoriaAnexoItem,
    HistoriaDocItem,
    HistoriaPenalItem,
    LitiganteItem,
    MovimientosPenalResponse,
    NotificacionPenalItem,
    RelacionItem,
)
from api.penal.urls import rit_formateado, url_publica_documento_penal, url_publica_imagen_penal

CAMPO_ESTADO_SINCRONIZANDO = "Sincronizando"
CAMPO_ESTADO_COMPLETO = "Completo"
CAMPO_ESTADO_ERROR = "Error"


async def obtener_o_crear_causa(
    session: AsyncSession, corte: int, tribunal: int, tipo: str, rol: int, anio: int
) -> CausaPenal:
    stmt = select(CausaPenal).where(
        CausaPenal.corte == corte,
        CausaPenal.tribunal == tribunal,
        CausaPenal.tipo == tipo,
        CausaPenal.rol == rol,
        CausaPenal.anio == anio,
    )
    causa = (await session.execute(stmt)).scalar_one_or_none()
    if causa is not None:
        return causa

    causa = CausaPenal(
        corte=corte,
        tribunal=tribunal,
        tipo=tipo,
        rol=rol,
        anio=anio,
        rit=rit_formateado(tipo, rol, anio),
        estado_sync="Pendiente",
    )
    session.add(causa)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return (await session.execute(stmt)).scalar_one()
    await session.refresh(causa)
    return causa


async def buscar_causa(
    session: AsyncSession, corte: int, tribunal: int, tipo: str, rol: int, anio: int
) -> CausaPenal | None:
    stmt = select(CausaPenal).where(
        CausaPenal.corte == corte,
        CausaPenal.tribunal == tribunal,
        CausaPenal.tipo == tipo,
        CausaPenal.rol == rol,
        CausaPenal.anio == anio,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def intentar_lock_sincronizacion(session: AsyncSession, causa_id, timeout_minutes: int) -> bool:
    """CAS atomico identico al de las demas competencias."""
    ahora = datetime.now(timezone.utc)
    umbral = ahora - timedelta(minutes=timeout_minutes)
    stmt = (
        update(CausaPenal)
        .where(
            CausaPenal.id == causa_id,
            or_(
                CausaPenal.estado_sync != CAMPO_ESTADO_SINCRONIZANDO,
                CausaPenal.sync_iniciado_en < umbral,
            ),
        )
        .values(estado_sync=CAMPO_ESTADO_SINCRONIZANDO, sync_iniciado_en=ahora)
        .returning(CausaPenal.id)
    )
    fila = (await session.execute(stmt)).first()
    await session.commit()
    return fila is not None


async def encolar_sync_job(
    session: AsyncSession,
    causa_penal_id,
    *,
    rut_cifrado: str | None = None,
    clave_cifrada: str | None = None,
    metodo_login: int | None = None,
) -> None:
    session.add(
        SyncJob(
            causa_penal_id=causa_penal_id,
            estado="pendiente",
            rut_cifrado=rut_cifrado,
            clave_cifrada=clave_cifrada,
            metodo_login=metodo_login,
        )
    )
    await session.commit()
    await session.execute(text("NOTIFY sync_jobs"))
    await session.commit()


def _url_doc(doc: DocumentoPenal | None, causa_id) -> str | None:
    if doc is None:
        return None
    _, ext = os.path.splitext(doc.ruta_archivo)
    return url_publica_documento_penal(causa_id, doc.nombre_archivo, ext or ".pdf")


async def construir_causa_detalle(session: AsyncSession, causa: CausaPenal) -> CausaPenalDetalle:
    documentos = (
        await session.execute(select(DocumentoPenal).where(DocumentoPenal.causa_penal_id == causa.id))
    ).scalars().all()
    docs_por_categoria: dict[str, DocumentoPenal] = {}
    for d in documentos:
        docs_por_categoria.setdefault(d.categoria, d)

    cuadernos_rows = (
        await session.execute(
            select(CuadernoPenal).where(CuadernoPenal.causa_penal_id == causa.id).order_by(CuadernoPenal.numero)
        )
    ).scalars().all()
    cuadernos = [
        CuadernoPenalItem(id=c.numero, nombre=c.nombre, estado_proceso=c.estado_proceso, etapa=c.etapa)
        for c in cuadernos_rows
    ]

    if causa.estado_sync == CAMPO_ESTADO_COMPLETO:
        estado_expuesto = CAMPO_ESTADO_COMPLETO
    elif causa.estado_sync == CAMPO_ESTADO_ERROR:
        estado_expuesto = CAMPO_ESTADO_ERROR
    else:
        estado_expuesto = CAMPO_ESTADO_SINCRONIZANDO

    return CausaPenalDetalle(
        identificador=str(causa.id),
        estado=estado_expuesto,
        detalle_estado=(causa.sync_detalle if estado_expuesto == CAMPO_ESTADO_SINCRONIZANDO else None),
        ultimo_error=(causa.ultimo_error if estado_expuesto == CAMPO_ESTADO_ERROR else None),
        fecha_ultima_sincronizacion=(
            causa.fecha_ultima_sincronizacion.date().isoformat() if causa.fecha_ultima_sincronizacion else None
        ),
        rol=causa.rit,
        fecha_ingreso=causa.fecha_ingreso,
        caratula=causa.caratula,
        ruc=causa.ruc,
        estado_adm=causa.estado_adm,
        procedimiento=causa.procedimiento,
        ubicacion=causa.ubicacion,
        proceso=causa.proceso,
        forma_inicio=causa.forma_inicio,
        estado_proceso=causa.estado_proceso,
        etapa=causa.etapa,
        tribunal=causa.tribunal_nombre,
        acumulada=_url_doc(docs_por_categoria.get("acumulada"), causa.id),
        certificado_envio=_url_doc(docs_por_categoria.get("certificado_envio"), causa.id),
        cuadernos=cuadernos,
    )


def _geo_item(latitud, longitud, corrector, imagenes_ids, imagen_url) -> GeoReferenciaItem | None:
    tiene_mapa = latitud is not None or longitud is not None or corrector is not None
    if not tiene_mapa and not imagenes_ids:
        return None
    return GeoReferenciaItem(
        mapa=GeoReferenciaMapa(latitud=latitud, longitud=longitud, corrector=corrector) if tiene_mapa else None,
        imagenes=[GeoReferenciaImagenItem(img=imagen_url(i)) for i in imagenes_ids],
    )


async def construir_movimientos(session: AsyncSession, causa: CausaPenal) -> MovimientosPenalResponse:
    todos_docs = (
        await session.execute(select(DocumentoPenal).where(DocumentoPenal.causa_penal_id == causa.id))
    ).scalars().all()
    docs_por_id = {d.id: d for d in todos_docs}

    def doc_url(documento_id) -> str | None:
        return _url_doc(docs_por_id.get(documento_id), causa.id)

    def imagen_url(documento_id) -> str | None:
        doc = docs_por_id.get(documento_id)
        if doc is None:
            return None
        _, ext = os.path.splitext(doc.ruta_archivo)
        return url_publica_imagen_penal(causa.id, doc.id, ext)

    historia_rows = (
        await session.execute(
            select(HistoriaPenal)
            .where(HistoriaPenal.causa_penal_id == causa.id)
            .order_by(HistoriaPenal.orden, HistoriaPenal.id)
        )
    ).scalars().all()
    historia_items = []
    for h in historia_rows:
        doc_rows = (
            await session.execute(
                select(HistoriaPenalDoc).where(HistoriaPenalDoc.movimiento_id == h.id).order_by(HistoriaPenalDoc.orden)
            )
        ).scalars().all()
        anexo_rows = (
            await session.execute(
                select(HistoriaPenalAnexo)
                .where(HistoriaPenalAnexo.movimiento_id == h.id)
                .order_by(HistoriaPenalAnexo.orden)
            )
        ).scalars().all()

        if h.descripcion_tramite_doc_id is not None:
            doc_desc = docs_por_id.get(h.descripcion_tramite_doc_id)
            descripcion_tramite = DescripcionTramiteDetalle(
                descripcion=h.descripcion_tramite,
                doc=DescripcionTramiteDocItem(
                    nombre=doc_desc.nombre_archivo,
                    ruta=doc_url(h.descripcion_tramite_doc_id),
                    color=h.descripcion_tramite_doc_color,
                )
                if doc_desc is not None
                else None,
            )
        else:
            descripcion_tramite = h.descripcion_tramite

        historia_items.append(
            HistoriaPenalItem(
                folio=h.folio,
                folio_texto=None if h.folio_texto == "[SF]" else h.folio_texto,
                doc=[HistoriaDocItem(doc=doc_url(d.documento_id), color=d.color) for d in doc_rows],
                anexo=[
                    HistoriaAnexoItem(doc=doc_url(a.documento_id), color=a.color, fecha=a.fecha, referencia=a.referencia)
                    for a in anexo_rows
                ],
                tramite=h.tramite,
                descripcion_tramite=descripcion_tramite,
                fecha_tramite=h.fecha_tramite,
                fecha_firma=h.fecha_firma,
                estado=h.estado,
            )
        )

    litigante_rows = (
        await session.execute(
            select(LitigantePenal).where(LitigantePenal.causa_penal_id == causa.id).order_by(LitigantePenal.id)
        )
    ).scalars().all()
    litigantes = [
        LitiganteItem(participantes=l.participantes, persona=l.persona, razon_social=l.razon_social)
        for l in litigante_rows
    ]

    notif_rows = (
        await session.execute(
            select(NotificacionPenal).where(NotificacionPenal.causa_penal_id == causa.id).order_by(NotificacionPenal.id)
        )
    ).scalars().all()
    notificaciones = []
    for n in notif_rows:
        imagenes_ids = (
            await session.execute(
                select(NotificacionPenalGeoImagen.documento_id)
                .where(NotificacionPenalGeoImagen.notificacion_id == n.id)
                .order_by(NotificacionPenalGeoImagen.orden)
            )
        ).scalars().all()
        notificaciones.append(
            NotificacionPenalItem(
                tipo_notificacion=n.tipo_notificacion,
                estado_notificacion=n.estado_notificacion,
                fecha_notificacion=n.fecha_notificacion,
                nombre=n.nombre,
                estampado=doc_url(n.estampado_doc_id) if n.estampado_doc_id else None,
                geo=_geo_item(n.geo_latitud, n.geo_longitud, n.geo_corrector, list(imagenes_ids), imagen_url),
            )
        )

    relacion_rows = (
        await session.execute(
            select(RelacionPenal).where(RelacionPenal.causa_penal_id == causa.id).order_by(RelacionPenal.id)
        )
    ).scalars().all()
    relaciones = [
        RelacionItem(
            nombre=r.nombre, materia=r.materia, estado_causa=r.estado_causa, fecha_cambio_estado=r.fecha_cambio_estado
        )
        for r in relacion_rows
    ]

    return MovimientosPenalResponse(
        historia=historia_items, litigantes=litigantes, notificaciones=notificaciones, Relaciones=relaciones
    )
