import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.cobranza.schemas import (
    AnexoCausaCobranzaItem,
    CausaCobranzaDetalle,
    CuadernoCobranzaItem,
    DescripcionTramiteDetalle,
    DescripcionTramiteDocItem,
    DiligenciaCobranzaItem,
    DocumentoRef,
    HistoriaAnexoItem,
    HistoriaCobranzaItem,
    HistoriaDocItem,
    InformacionReceptorCobranzaItem,
    LiquidacionCobranzaItem,
    LitiganteCobranzaItem,
    MovimientosCobranzaResponse,
    NotificacionCobranzaItem,
)
from api.cobranza.urls import rit_formateado, url_publica_documento_cobranza, url_publica_imagen_cobranza
from api.civil.schemas import GeoReferenciaImagenItem, GeoReferenciaItem, GeoReferenciaMapa
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
from api.db.models.sync_job import SyncJob

CAMPO_ESTADO_SINCRONIZANDO = "Sincronizando"
CAMPO_ESTADO_COMPLETO = "Completo"
CAMPO_ESTADO_ERROR = "Error"


async def obtener_o_crear_causa(
    session: AsyncSession, corte: int, tribunal: int, tipo: str, rol: int, anio: int
) -> CausaCobranza:
    stmt = select(CausaCobranza).where(
        CausaCobranza.corte == corte,
        CausaCobranza.tribunal == tribunal,
        CausaCobranza.tipo == tipo,
        CausaCobranza.rol == rol,
        CausaCobranza.anio == anio,
    )
    causa = (await session.execute(stmt)).scalar_one_or_none()
    if causa is not None:
        return causa

    causa = CausaCobranza(
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
) -> CausaCobranza | None:
    stmt = select(CausaCobranza).where(
        CausaCobranza.corte == corte,
        CausaCobranza.tribunal == tribunal,
        CausaCobranza.tipo == tipo,
        CausaCobranza.rol == rol,
        CausaCobranza.anio == anio,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def intentar_lock_sincronizacion(session: AsyncSession, causa_id, timeout_minutes: int) -> bool:
    """CAS atomico identico al de civil/familia/laboral."""
    ahora = datetime.now(timezone.utc)
    umbral = ahora - timedelta(minutes=timeout_minutes)
    stmt = (
        update(CausaCobranza)
        .where(
            CausaCobranza.id == causa_id,
            or_(
                CausaCobranza.estado_sync != CAMPO_ESTADO_SINCRONIZANDO,
                CausaCobranza.sync_iniciado_en < umbral,
            ),
        )
        .values(estado_sync=CAMPO_ESTADO_SINCRONIZANDO, sync_iniciado_en=ahora)
        .returning(CausaCobranza.id)
    )
    fila = (await session.execute(stmt)).first()
    await session.commit()
    return fila is not None


async def encolar_sync_job(
    session: AsyncSession,
    causa_cobranza_id,
    *,
    rut_cifrado: str | None = None,
    clave_cifrada: str | None = None,
    metodo_login: int | None = None,
) -> None:
    session.add(
        SyncJob(
            causa_cobranza_id=causa_cobranza_id,
            estado="pendiente",
            rut_cifrado=rut_cifrado,
            clave_cifrada=clave_cifrada,
            metodo_login=metodo_login,
        )
    )
    await session.commit()
    await session.execute(text("NOTIFY sync_jobs"))
    await session.commit()


def _doc_ref(doc: DocumentoCobranza | None, causa_id) -> DocumentoRef | None:
    if doc is None:
        return None
    _, ext = os.path.splitext(doc.ruta_archivo)
    return DocumentoRef(
        nombre_archivo=doc.nombre_archivo,
        url=url_publica_documento_cobranza(causa_id, doc.nombre_archivo, ext or ".pdf"),
    )


def _anexo_item(
    doc: DocumentoCobranza | None, causa_id, fecha: str | None, referencia: str | None
) -> AnexoCausaCobranzaItem:
    # Misma forma para "Anexos de la causa" y "Documentos Laboral" (ver Solicitud
    # Cobranza.md / popup "Detalle Documentos Laboral"). La extension viene del archivo
    # real en disco -- estos documentos mezclan pdf/doc/docx (confirmado en vivo, causa
    # C-2552-2015: "Resolución de Reenvío a Cobranza" y "Dictación de Sentencia" son
    # .doc); sin esto la URL quedaba forzada a ".pdf" y el documento real no se podia
    # descargar aunque `documento_id` estuviera bien guardado.
    if doc is None:
        return AnexoCausaCobranzaItem(fecha=fecha, referencia=referencia, nombre_doc=None, doc=None)
    _, ext = os.path.splitext(doc.ruta_archivo)
    return AnexoCausaCobranzaItem(
        fecha=fecha,
        referencia=referencia,
        nombre_doc=doc.nombre_archivo,
        doc=url_publica_documento_cobranza(causa_id, doc.nombre_archivo, ext or ".pdf"),
    )


async def construir_causa_detalle(session: AsyncSession, causa: CausaCobranza) -> CausaCobranzaDetalle:
    documentos_cabecera = (
        await session.execute(select(DocumentoCobranza).where(DocumentoCobranza.causa_cobranza_id == causa.id))
    ).scalars().all()
    docs_por_categoria: dict[str, DocumentoCobranza] = {}
    docs_por_id: dict = {}
    for d in documentos_cabecera:
        docs_por_categoria.setdefault(d.categoria, d)
        docs_por_id[d.id] = d

    anexos_rows = (
        await session.execute(
            select(AnexoCausaCobranza)
            .where(AnexoCausaCobranza.causa_cobranza_id == causa.id)
            .order_by(AnexoCausaCobranza.target.asc().nulls_last())
        )
    ).scalars().all()
    anexos = [
        _anexo_item(docs_por_id.get(a.documento_id), causa.id, a.fecha, a.referencia) for a in anexos_rows
    ]

    info_rows = (
        await session.execute(
            select(InformacionReceptorCobranza).where(InformacionReceptorCobranza.causa_cobranza_id == causa.id)
        )
    ).scalars().all()
    informacion_receptor = [
        InformacionReceptorCobranzaItem(
            cuaderno=r.cuaderno_nombre, datos_retiro=r.datos_retiro, fecha_retiro=r.fecha_retiro, estado=r.estado
        )
        for r in info_rows
    ]

    cuadernos_rows = (
        await session.execute(
            select(CuadernoCobranza).where(CuadernoCobranza.causa_cobranza_id == causa.id).order_by(CuadernoCobranza.numero)
        )
    ).scalars().all()
    cuadernos = [
        CuadernoCobranzaItem(id=c.numero, nombre=c.nombre, estado_proceso=c.estado_proceso, etapa=c.etapa)
        for c in cuadernos_rows
    ]

    doc_lab_rows = (
        await session.execute(
            select(DocumentoLaboralCobranza)
            .where(DocumentoLaboralCobranza.causa_cobranza_id == causa.id)
            .order_by(DocumentoLaboralCobranza.orden)
        )
    ).scalars().all()
    documentos_laboral = [
        _anexo_item(docs_por_id.get(d.documento_id), causa.id, d.fecha, d.referencia) for d in doc_lab_rows
    ]

    if causa.estado_sync == CAMPO_ESTADO_COMPLETO:
        estado_expuesto = CAMPO_ESTADO_COMPLETO
    elif causa.estado_sync == CAMPO_ESTADO_ERROR:
        estado_expuesto = CAMPO_ESTADO_ERROR
    else:
        estado_expuesto = CAMPO_ESTADO_SINCRONIZANDO

    return CausaCobranzaDetalle(
        identificador=str(causa.id),
        estado=estado_expuesto,
        detalle_estado=(causa.sync_detalle if estado_expuesto == CAMPO_ESTADO_SINCRONIZANDO else None),
        ultimo_error=(causa.ultimo_error if estado_expuesto == CAMPO_ESTADO_ERROR else None),
        fecha_ultima_sincronizacion=(
            causa.fecha_ultima_sincronizacion.date().isoformat() if causa.fecha_ultima_sincronizacion else None
        ),
        rit=causa.rit,
        caratula=causa.caratula,
        fecha_ingreso=causa.fecha_ingreso,
        ruc=causa.ruc,
        proceso=causa.proceso,
        forma_inicio=causa.forma_inicio,
        est_adm=causa.est_adm,
        estado_proceso=causa.estado_proceso,
        etapa=causa.etapa,
        titulo_ejec=_doc_ref(docs_por_categoria.get("titulo_ejec"), causa.id),
        juez_asignado=causa.juez_asignado,
        tribunal=causa.tribunal_nombre,
        doc_demanda=_doc_ref(docs_por_categoria.get("doc_demanda"), causa.id),
        anexos_causa=anexos,
        ebook=_doc_ref(docs_por_categoria.get("ebook"), causa.id),
        certificado_envio=_doc_ref(docs_por_categoria.get("certificado_envio"), causa.id),
        documentos_laboral=documentos_laboral,
        informacion_receptor=informacion_receptor,
        cuadernos=cuadernos,
    )


async def construir_movimientos(session: AsyncSession, causa: CausaCobranza) -> MovimientosCobranzaResponse:
    todos_docs = (
        await session.execute(select(DocumentoCobranza).where(DocumentoCobranza.causa_cobranza_id == causa.id))
    ).scalars().all()
    docs_por_id = {d.id: d for d in todos_docs}

    def doc_url(documento_id) -> str | None:
        doc = docs_por_id.get(documento_id)
        if doc is None:
            return None
        _, ext = os.path.splitext(doc.ruta_archivo)
        return url_publica_documento_cobranza(causa.id, doc.nombre_archivo, ext or ".pdf")

    def imagen_url(documento_id) -> str | None:
        doc = docs_por_id.get(documento_id)
        if doc is None:
            return None
        _, ext = os.path.splitext(doc.ruta_archivo)
        return url_publica_imagen_cobranza(causa.id, doc.id, ext)

    historia_rows = (
        await session.execute(
            select(HistoriaCobranza)
            .where(HistoriaCobranza.causa_cobranza_id == causa.id)
            .order_by(HistoriaCobranza.orden, HistoriaCobranza.id)
        )
    ).scalars().all()
    historia_items = []
    for h in historia_rows:
        doc_rows = (
            await session.execute(
                select(HistoriaCobranzaDoc).where(HistoriaCobranzaDoc.movimiento_id == h.id).order_by(HistoriaCobranzaDoc.orden)
            )
        ).scalars().all()
        anexo_rows = (
            await session.execute(
                select(HistoriaCobranzaAnexo)
                .where(HistoriaCobranzaAnexo.movimiento_id == h.id)
                .order_by(HistoriaCobranzaAnexo.orden)
            )
        ).scalars().all()
        geo_img_rows = (
            await session.execute(
                select(HistoriaCobranzaGeoImagen)
                .where(HistoriaCobranzaGeoImagen.movimiento_id == h.id)
                .order_by(HistoriaCobranzaGeoImagen.orden)
            )
        ).scalars().all()
        tiene_mapa = h.geo_latitud is not None or h.geo_longitud is not None or h.geo_corrector is not None
        georref = (
            GeoReferenciaItem(
                mapa=(
                    GeoReferenciaMapa(latitud=h.geo_latitud, longitud=h.geo_longitud, corrector=h.geo_corrector)
                    if tiene_mapa
                    else None
                ),
                imagenes=[GeoReferenciaImagenItem(img=imagen_url(i.documento_id)) for i in geo_img_rows],
            )
            if tiene_mapa or geo_img_rows
            else None
        )

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
            HistoriaCobranzaItem(
                folio=h.folio,
                folio_texto=None if h.folio_texto == "[SF]" else h.folio_texto,
                doc=[HistoriaDocItem(doc=doc_url(d.documento_id), color=d.color) for d in doc_rows],
                anexo=[
                    HistoriaAnexoItem(
                        doc=doc_url(a.documento_id), color=a.color, fecha=a.fecha, referencia=a.referencia
                    )
                    for a in anexo_rows
                ],
                etapa=h.etapa,
                tramite=h.tramite,
                descripcion_tramite=descripcion_tramite,
                estado_firma=h.estado_firma,
                fecha_tramite=h.fecha_tramite,
                georref=georref,
            )
        )

    litigante_rows = (
        await session.execute(
            select(LitiganteCobranza).where(LitiganteCobranza.causa_cobranza_id == causa.id).order_by(LitiganteCobranza.id)
        )
    ).scalars().all()
    litigantes = [
        LitiganteCobranzaItem(sujeto=l.sujeto, rut=l.rut, persona=l.persona, razon_social=l.razon_social)
        for l in litigante_rows
    ]

    notif_rows = (
        await session.execute(
            select(NotificacionCobranza)
            .where(NotificacionCobranza.causa_cobranza_id == causa.id)
            .order_by(NotificacionCobranza.id)
        )
    ).scalars().all()
    notificaciones = [
        NotificacionCobranzaItem(
            tipo_notificacion=n.tipo_notificacion,
            estado_notificacion=n.estado_notificacion,
            fecha_notificacion=n.fecha_notificacion,
            fecha_tramite=n.fecha_tramite,
            tramite=n.tramite,
            tipo_part=n.tipo_part,
            nombre=n.nombre,
        )
        for n in notif_rows
    ]

    diligencia_rows = (
        await session.execute(
            select(DiligenciaCobranza).where(DiligenciaCobranza.causa_cobranza_id == causa.id).order_by(DiligenciaCobranza.id)
        )
    ).scalars().all()
    diligencias = [
        DiligenciaCobranzaItem(
            doc_ida=doc_url(d.doc_ida_id),
            doc_vta=doc_url(d.doc_vta_id),
            estado_diligencia=d.estado_diligencia,
            rit=d.rit,
            ruc=d.ruc,
            tipo_diligencia=d.tipo_diligencia,
            fecha_tramite=d.fecha_tramite,
            destinatario=d.destinatario,
            responsable=d.responsable,
        )
        for d in diligencia_rows
    ]

    liquidacion_rows = (
        await session.execute(
            select(LiquidacionCobranza)
            .where(LiquidacionCobranza.causa_cobranza_id == causa.id)
            .order_by(LiquidacionCobranza.id)
        )
    ).scalars().all()
    liquidacion = [
        LiquidacionCobranzaItem(
            liquidacion=doc_url(q.liquidacion_doc_id),
            fecha_liquidacion=q.fecha_liquidacion,
            cuaderno=q.cuaderno,
            estado=q.estado,
            monto_liquido=q.monto_liquido,
        )
        for q in liquidacion_rows
    ]

    return MovimientosCobranzaResponse(
        historia=historia_items,
        litigantes=litigantes,
        notificaciones=notificaciones,
        diligencias=diligencias,
        liquidacion=liquidacion,
    )
