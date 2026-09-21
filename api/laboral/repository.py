import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text, update
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
from api.db.models.sync_job import SyncJob
from api.laboral.schemas import (
    AudioItem,
    CausaLaboralDetalle,
    DiligenciaLaboralItem,
    DocumentoRef,
    EscritoPendienteItem,
    LiquidacionItem,
    LitiganteLaboralItem,
    MateriaLaboralItem,
    MovimientoAnexoItem,
    MovimientoDocItem,
    MovimientoLaboralItem,
    MovimientosLaboralResponse,
    NotificacionLaboralItem,
    TextoDemandaItem,
)
from api.laboral.urls import (
    rit_formateado,
    url_publica_audio_laboral,
    url_publica_documento_laboral,
    url_publica_imagen_laboral,
)
from api.civil.schemas import GeoReferenciaImagenItem, GeoReferenciaItem, GeoReferenciaMapa

CAMPO_ESTADO_SINCRONIZANDO = "Sincronizando"
CAMPO_ESTADO_COMPLETO = "Completo"
CAMPO_ESTADO_ERROR = "Error"


async def obtener_o_crear_causa(
    session: AsyncSession, corte: int, tribunal: int, tipo: str, rol: int, anio: int
) -> CausaLaboral:
    stmt = select(CausaLaboral).where(
        CausaLaboral.corte == corte,
        CausaLaboral.tribunal == tribunal,
        CausaLaboral.tipo == tipo,
        CausaLaboral.rol == rol,
        CausaLaboral.anio == anio,
    )
    causa = (await session.execute(stmt)).scalar_one_or_none()
    if causa is not None:
        return causa

    causa = CausaLaboral(
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
) -> CausaLaboral | None:
    stmt = select(CausaLaboral).where(
        CausaLaboral.corte == corte,
        CausaLaboral.tribunal == tribunal,
        CausaLaboral.tipo == tipo,
        CausaLaboral.rol == rol,
        CausaLaboral.anio == anio,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def intentar_lock_sincronizacion(session: AsyncSession, causa_id, timeout_minutes: int) -> bool:
    """CAS atomico identico al de civil/familia."""
    ahora = datetime.now(timezone.utc)
    umbral = ahora - timedelta(minutes=timeout_minutes)
    stmt = (
        update(CausaLaboral)
        .where(
            CausaLaboral.id == causa_id,
            or_(
                CausaLaboral.estado_sync != CAMPO_ESTADO_SINCRONIZANDO,
                CausaLaboral.sync_iniciado_en < umbral,
            ),
        )
        .values(estado_sync=CAMPO_ESTADO_SINCRONIZANDO, sync_iniciado_en=ahora)
        .returning(CausaLaboral.id)
    )
    fila = (await session.execute(stmt)).first()
    await session.commit()
    return fila is not None


async def encolar_sync_job(
    session: AsyncSession,
    causa_laboral_id,
    *,
    rut_cifrado: str | None = None,
    clave_cifrada: str | None = None,
    metodo_login: int | None = None,
) -> None:
    session.add(
        SyncJob(
            causa_laboral_id=causa_laboral_id,
            estado="pendiente",
            rut_cifrado=rut_cifrado,
            clave_cifrada=clave_cifrada,
            metodo_login=metodo_login,
        )
    )
    await session.commit()
    await session.execute(text("NOTIFY sync_jobs"))
    await session.commit()


def _doc_ref(doc: DocumentoLaboral | None, causa_id) -> DocumentoRef | None:
    if doc is None:
        return None
    _, ext = os.path.splitext(doc.ruta_archivo)
    return DocumentoRef(
        nombre_archivo=doc.nombre_archivo,
        url=url_publica_documento_laboral(causa_id, doc.nombre_archivo, ext or ".pdf"),
    )


async def construir_causa_detalle(session: AsyncSession, causa: CausaLaboral) -> CausaLaboralDetalle:
    documentos = (
        await session.execute(select(DocumentoLaboral).where(DocumentoLaboral.causa_laboral_id == causa.id))
    ).scalars().all()
    docs_por_categoria: dict[str, DocumentoLaboral] = {}
    docs_por_id: dict = {}
    for d in documentos:
        docs_por_categoria.setdefault(d.categoria, d)
        docs_por_id[d.id] = d

    def doc_url(documento_id) -> str | None:
        doc = docs_por_id.get(documento_id)
        if doc is None:
            return None
        _, ext = os.path.splitext(doc.ruta_archivo)
        return url_publica_documento_laboral(causa.id, doc.nombre_archivo, ext or ".pdf")

    def audio_url(documento_id) -> str | None:
        # Los audios son mp3, no pdf -- `doc_url`/`url_publica_documento_laboral`
        # fuerzan `.pdf` (correcto para el resto de documentos de Laboral, que si son
        # pdf). Mismo esquema que las imagenes de Georref: por GUID + extension real.
        doc = docs_por_id.get(documento_id)
        if doc is None:
            return None
        _, ext = os.path.splitext(doc.ruta_archivo)
        return url_publica_audio_laboral(causa.id, doc.id, ext)

    texto_demanda_rows = (
        await session.execute(
            select(TextoDemandaLaboral)
            .where(TextoDemandaLaboral.causa_laboral_id == causa.id)
            .order_by(TextoDemandaLaboral.orden)
        )
    ).scalars().all()
    texto_demanda = [
        TextoDemandaItem(
            doc_demanda=t.doc_demanda, doc=doc_url(t.documento_id), fecha=t.fecha, referencia=t.referencia
        )
        for t in texto_demanda_rows
    ]

    audio_rows = (
        await session.execute(
            select(AudioLaboral).where(AudioLaboral.causa_laboral_id == causa.id).order_by(AudioLaboral.orden)
        )
    ).scalars().all()
    audio_laboral = [
        AudioItem(numero=a.numero, audio=audio_url(a.documento_id), fecha=a.fecha, referencia=a.referencia)
        for a in audio_rows
    ]

    if causa.estado_sync == CAMPO_ESTADO_COMPLETO:
        estado_expuesto = CAMPO_ESTADO_COMPLETO
    elif causa.estado_sync == CAMPO_ESTADO_ERROR:
        estado_expuesto = CAMPO_ESTADO_ERROR
    else:
        estado_expuesto = CAMPO_ESTADO_SINCRONIZANDO

    return CausaLaboralDetalle(
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
        etapa=causa.etapa,
        estado_proceso=causa.estado_proceso,
        tribunal=causa.tribunal_nombre,
        texto_demanda=texto_demanda,
        tramites=causa.tramites,
        ebook=_doc_ref(docs_por_categoria.get("ebook"), causa.id),
        certificado_envio=_doc_ref(docs_por_categoria.get("certificado_envio"), causa.id),
        audio_laboral=audio_laboral,
    )


async def construir_movimientos(session: AsyncSession, causa: CausaLaboral) -> MovimientosLaboralResponse:
    todos_docs = (
        await session.execute(select(DocumentoLaboral).where(DocumentoLaboral.causa_laboral_id == causa.id))
    ).scalars().all()
    docs_por_id = {d.id: d for d in todos_docs}

    def doc_url(documento_id) -> str | None:
        doc = docs_por_id.get(documento_id)
        if doc is None:
            return None
        _, ext = os.path.splitext(doc.ruta_archivo)
        return url_publica_documento_laboral(causa.id, doc.nombre_archivo, ext or ".pdf")

    def imagen_url(documento_id) -> str | None:
        doc = docs_por_id.get(documento_id)
        if doc is None:
            return None
        _, ext = os.path.splitext(doc.ruta_archivo)
        return url_publica_imagen_laboral(causa.id, doc.id, ext)

    mov_rows = (
        await session.execute(
            select(MovimientoLaboral)
            .where(MovimientoLaboral.causa_laboral_id == causa.id)
            .order_by(MovimientoLaboral.orden, MovimientoLaboral.id)
        )
    ).scalars().all()
    movimientos = []
    for m in mov_rows:
        doc_rows = (
            await session.execute(
                select(MovimientoLaboralDoc)
                .where(MovimientoLaboralDoc.movimiento_id == m.id)
                .order_by(MovimientoLaboralDoc.orden)
            )
        ).scalars().all()
        anexo_rows = (
            await session.execute(
                select(MovimientoLaboralAnexo)
                .where(MovimientoLaboralAnexo.movimiento_id == m.id)
                .order_by(MovimientoLaboralAnexo.orden)
            )
        ).scalars().all()
        geo_img_rows = (
            await session.execute(
                select(MovimientoLaboralGeoImagen)
                .where(MovimientoLaboralGeoImagen.movimiento_id == m.id)
                .order_by(MovimientoLaboralGeoImagen.orden)
            )
        ).scalars().all()
        tiene_mapa = m.geo_latitud is not None or m.geo_longitud is not None or m.geo_corrector is not None
        georreferencia = (
            GeoReferenciaItem(
                mapa=(
                    GeoReferenciaMapa(latitud=m.geo_latitud, longitud=m.geo_longitud, corrector=m.geo_corrector)
                    if tiene_mapa
                    else None
                ),
                imagenes=[GeoReferenciaImagenItem(img=imagen_url(i.documento_id)) for i in geo_img_rows],
            )
            if tiene_mapa or geo_img_rows
            else None
        )
        movimientos.append(
            MovimientoLaboralItem(
                folio=m.folio,
                folio_texto=None if m.folio_texto == "[SF]" else m.folio_texto,
                doc=[MovimientoDocItem(doc=doc_url(d.documento_id)) for d in doc_rows],
                anexo=[
                    MovimientoAnexoItem(
                        doc=doc_url(a.documento_id),
                        fecha=a.fecha,
                        referencia=a.referencia,
                    )
                    for a in anexo_rows
                ],
                etapa=m.etapa,
                tramite=m.tramite,
                descripcion_tramite=m.descripcion_tramite,
                fecha_tramite=m.fecha_tramite,
                estado=m.estado,
                georreferencia=georreferencia,
            )
        )

    litigante_rows = (
        await session.execute(
            select(LitiganteLaboral)
            .where(LitiganteLaboral.causa_laboral_id == causa.id)
            .order_by(LitiganteLaboral.id)
        )
    ).scalars().all()
    litigantes = [
        LitiganteLaboralItem(
            estado=l.estado, defensor=l.defensor, sujeto=l.sujeto, rut=l.rut, persona=l.persona,
            razon_social=l.razon_social,
        )
        for l in litigante_rows
    ]

    notif_rows = (
        await session.execute(
            select(NotificacionLaboral)
            .where(NotificacionLaboral.causa_laboral_id == causa.id)
            .order_by(NotificacionLaboral.id)
        )
    ).scalars().all()
    notificaciones = [
        NotificacionLaboralItem(
            estado_notificacion=n.estado_notificacion,
            fecha_tramite=n.fecha_tramite,
            tipo_part=n.tipo_parte,
            nombre=n.nombre,
            tramite=n.tramite,
            observacion_fallida=n.observacion_fallida,
        )
        for n in notif_rows
    ]

    diligencia_rows = (
        await session.execute(
            select(DiligenciaLaboral)
            .where(DiligenciaLaboral.causa_laboral_id == causa.id)
            .order_by(DiligenciaLaboral.id)
        )
    ).scalars().all()
    diligencias = [
        DiligenciaLaboralItem(
            doc_ida=doc_url(d.doc_ida_id),
            doc_vta=doc_url(d.doc_vta_id),
            estado_diligencia=d.estado_diligencia,
            rit=d.rit,
            ruc=d.ruc,
            tipo_diligencia=d.tipo_diligencia,
            referencia=d.referencia,
            fecha_tramite=d.fecha_tramite,
        )
        for d in diligencia_rows
    ]

    liquidacion_rows = (
        await session.execute(
            select(LiquidacionLaboral)
            .where(LiquidacionLaboral.causa_laboral_id == causa.id)
            .order_by(LiquidacionLaboral.id)
        )
    ).scalars().all()
    liquidacion = [
        LiquidacionItem(liquidacion=q.liquidacion, rut=q.rut, nombre=q.nombre, monto_liquido=q.monto_liquido)
        for q in liquidacion_rows
    ]

    materia_rows = (
        await session.execute(
            select(MateriaLaboral).where(MateriaLaboral.causa_laboral_id == causa.id).order_by(MateriaLaboral.id)
        )
    ).scalars().all()
    materias = [
        MateriaLaboralItem(
            codigo=m.codigo, glosa_materia=m.glosa_materia, estado=m.estado, fecha_termino=m.fecha_termino
        )
        for m in materia_rows
    ]

    escrito_rows = (
        await session.execute(
            select(EscritoPendienteLaboral)
            .where(EscritoPendienteLaboral.causa_laboral_id == causa.id)
            .order_by(EscritoPendienteLaboral.id)
        )
    ).scalars().all()
    escritos_pendientes = [
        EscritoPendienteItem(
            doc=doc_url(e.doc_id),
            anexo=doc_url(e.anexo_id),
            fecha_ing=e.fecha_ing,
            referencia=e.referencia,
            solicitante=e.solicitante,
            tipo_ingreso=e.tipo_ingreso,
        )
        for e in escrito_rows
    ]

    return MovimientosLaboralResponse(
        movimiento=movimientos,
        litigantes=litigantes,
        notificaciones=notificaciones,
        diligencias=diligencias,
        liquidacion=liquidacion,
        materias=materias,
        escritos_pendientes=escritos_pendientes,
    )
