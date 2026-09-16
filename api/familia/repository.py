import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.familia.schemas import (
    AnexoCausaItem,
    CausaFamiliaDetalle,
    DiligenciaItem,
    DocumentoRef,
    GeoReferenciaImagenItem,
    GeoReferenciaItem,
    GeoReferenciaMapa,
    HistoriaAnexoItem,
    HistoriaDocItem,
    LitiganteFamiliaItem,
    MateriaItem,
    MovimientoFamiliaItem,
    MovimientosFamiliaResponse,
    NotificacionFamiliaItem,
    PlazoItem,
)
from api.familia.urls import rit_formateado, url_publica_documento_familia, url_publica_imagen_familia
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
    MovimientoHistoriaFamiliaGeoImagen,
    NotificacionFamilia,
    PlazoFamilia,
)
from api.db.models.sync_job import SyncJob

CAMPO_ESTADO_SINCRONIZANDO = "Sincronizando"
CAMPO_ESTADO_COMPLETO = "Completo"
CAMPO_ESTADO_ERROR = "Error"


async def obtener_o_crear_causa(
    session: AsyncSession, corte: int, tribunal: int, tipo: str, rol: int, anio: int
) -> CausaFamilia:
    stmt = select(CausaFamilia).where(
        CausaFamilia.corte == corte,
        CausaFamilia.tribunal == tribunal,
        CausaFamilia.tipo == tipo,
        CausaFamilia.rol == rol,
        CausaFamilia.anio == anio,
    )
    causa = (await session.execute(stmt)).scalar_one_or_none()
    if causa is not None:
        return causa

    causa = CausaFamilia(
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
) -> CausaFamilia | None:
    stmt = select(CausaFamilia).where(
        CausaFamilia.corte == corte,
        CausaFamilia.tribunal == tribunal,
        CausaFamilia.tipo == tipo,
        CausaFamilia.rol == rol,
        CausaFamilia.anio == anio,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def intentar_lock_sincronizacion(session: AsyncSession, causa_id, timeout_minutes: int) -> bool:
    """CAS atomico identico al de civil: el UPDATE ... RETURNING no afecta filas si ya
    hay un lock 'Sincronizando' vigente -> eso es la senal de 409."""
    ahora = datetime.now(timezone.utc)
    umbral = ahora - timedelta(minutes=timeout_minutes)
    stmt = (
        update(CausaFamilia)
        .where(
            CausaFamilia.id == causa_id,
            or_(
                CausaFamilia.estado_sync != CAMPO_ESTADO_SINCRONIZANDO,
                CausaFamilia.sync_iniciado_en < umbral,
            ),
        )
        .values(estado_sync=CAMPO_ESTADO_SINCRONIZANDO, sync_iniciado_en=ahora)
        .returning(CausaFamilia.id)
    )
    fila = (await session.execute(stmt)).first()
    await session.commit()
    return fila is not None


async def encolar_sync_job(
    session: AsyncSession, causa_familia_id, *, rut_cifrado: str, clave_cifrada: str, metodo_login: int
) -> None:
    session.add(
        SyncJob(
            causa_familia_id=causa_familia_id,
            estado="pendiente",
            rut_cifrado=rut_cifrado,
            clave_cifrada=clave_cifrada,
            metodo_login=metodo_login,
        )
    )
    await session.commit()
    await session.execute(text("NOTIFY sync_jobs"))
    await session.commit()


def _doc_ref(doc: DocumentoFamilia | None, causa_id) -> DocumentoRef | None:
    if doc is None:
        return None
    return DocumentoRef(
        nombre_archivo=doc.nombre_archivo,
        url=url_publica_documento_familia(causa_id, doc.nombre_archivo),
    )


async def construir_causa_detalle(session: AsyncSession, causa: CausaFamilia) -> CausaFamiliaDetalle:
    documentos = (
        await session.execute(select(DocumentoFamilia).where(DocumentoFamilia.causa_familia_id == causa.id))
    ).scalars().all()
    docs_por_categoria: dict[str, DocumentoFamilia] = {}
    docs_por_id: dict = {}
    for d in documentos:
        docs_por_categoria.setdefault(d.categoria, d)
        docs_por_id[d.id] = d

    anexos_rows = (
        await session.execute(
            select(AnexoCausaFamilia)
            .where(AnexoCausaFamilia.causa_familia_id == causa.id)
            .order_by(AnexoCausaFamilia.target.asc().nulls_last())
        )
    ).scalars().all()
    anexos = [
        AnexoCausaItem(
            folio=a.folio,
            fecha=a.fecha,
            referencia=a.referencia,
            nombre_doc=docs_por_id[a.documento_id].nombre_archivo if a.documento_id in docs_por_id else None,
            doc=(
                url_publica_documento_familia(causa.id, docs_por_id[a.documento_id].nombre_archivo)
                if a.documento_id in docs_por_id
                else None
            ),
        )
        for a in anexos_rows
    ]

    if causa.estado_sync == CAMPO_ESTADO_COMPLETO:
        estado_expuesto = CAMPO_ESTADO_COMPLETO
    elif causa.estado_sync == CAMPO_ESTADO_ERROR:
        estado_expuesto = CAMPO_ESTADO_ERROR
    else:
        estado_expuesto = CAMPO_ESTADO_SINCRONIZANDO

    return CausaFamiliaDetalle(
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
        anexos_causa=anexos,
        certificado_envio=_doc_ref(docs_por_categoria.get("certificado_envio"), causa.id),
        ebook=_doc_ref(docs_por_categoria.get("ebook"), causa.id),
    )


async def construir_movimientos(session: AsyncSession, causa: CausaFamilia) -> MovimientosFamiliaResponse:
    todos_docs = (
        await session.execute(select(DocumentoFamilia).where(DocumentoFamilia.causa_familia_id == causa.id))
    ).scalars().all()
    docs_por_id = {d.id: d for d in todos_docs}

    def doc_url(documento_id) -> str | None:
        doc = docs_por_id.get(documento_id)
        return url_publica_documento_familia(causa.id, doc.nombre_archivo) if doc else None

    def imagen_url(documento_id) -> str | None:
        doc = docs_por_id.get(documento_id)
        if doc is None:
            return None
        _, ext = os.path.splitext(doc.ruta_archivo)
        return url_publica_imagen_familia(causa.id, doc.id, ext)

    historia_rows = (
        await session.execute(
            select(MovimientoHistoriaFamilia)
            .where(MovimientoHistoriaFamilia.causa_familia_id == causa.id)
            .order_by(MovimientoHistoriaFamilia.orden, MovimientoHistoriaFamilia.id)
        )
    ).scalars().all()
    movimientos = []
    for h in historia_rows:
        doc_rows = (
            await session.execute(
                select(MovimientoHistoriaFamiliaDoc)
                .where(MovimientoHistoriaFamiliaDoc.movimiento_id == h.id)
                .order_by(MovimientoHistoriaFamiliaDoc.orden)
            )
        ).scalars().all()
        anexo_rows = (
            await session.execute(
                select(MovimientoHistoriaFamiliaAnexo)
                .where(MovimientoHistoriaFamiliaAnexo.movimiento_id == h.id)
                .order_by(MovimientoHistoriaFamiliaAnexo.orden)
            )
        ).scalars().all()
        geo_img_rows = (
            await session.execute(
                select(MovimientoHistoriaFamiliaGeoImagen)
                .where(MovimientoHistoriaFamiliaGeoImagen.movimiento_id == h.id)
                .order_by(MovimientoHistoriaFamiliaGeoImagen.orden)
            )
        ).scalars().all()
        tiene_mapa = h.geo_latitud is not None or h.geo_longitud is not None or h.geo_corrector is not None
        georeferencia = (
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
        movimientos.append(
            MovimientoFamiliaItem(
                folio=h.folio,
                folio_texto=None if h.folio_texto == "[SF]" else h.folio_texto,
                doc=[HistoriaDocItem(doc=doc_url(d.documento_id)) for d in doc_rows],
                anexo=[
                    HistoriaAnexoItem(
                        folio=a.folio,
                        doc=doc_url(a.documento_id),
                        fecha=a.fecha,
                        nombre_documento=a.nombre_documento,
                        observacion=a.observacion,
                    )
                    for a in anexo_rows
                ],
                etapa=h.etapa,
                estado=h.estado,
                tramite=h.tramite,
                descripcion_tramite=h.descripcion_tramite,
                fecha_tramite=h.fecha_tramite,
                georeferencia=georeferencia,
            )
        )

    litigante_rows = (
        await session.execute(
            select(LitiganteFamilia).where(LitiganteFamilia.causa_familia_id == causa.id).order_by(LitiganteFamilia.id)
        )
    ).scalars().all()
    litigantes = [
        LitiganteFamiliaItem(sujeto=l.sujeto, rut=l.rut, persona=l.persona, razon_social=l.razon_social)
        for l in litigante_rows
    ]

    materia_rows = (
        await session.execute(
            select(MateriaFamilia).where(MateriaFamilia.causa_familia_id == causa.id).order_by(MateriaFamilia.id)
        )
    ).scalars().all()
    materias = [
        MateriaItem(codigo=m.codigo, glosa_de_materia=m.glosa, estado=m.estado, fecha_termino=m.fecha_termino)
        for m in materia_rows
    ]

    plazo_rows = (
        await session.execute(
            select(PlazoFamilia).where(PlazoFamilia.causa_familia_id == causa.id).order_by(PlazoFamilia.id)
        )
    ).scalars().all()
    plazos = [
        PlazoItem(
            tipo_plazo=p.tipo_plazo,
            ambito_afectado=p.ambito_afectado,
            fecha_inicio=p.fecha_inicio,
            fecha_termino=p.fecha_termino,
            duracion=p.duracion,
            estado=p.estado,
            tramite=p.tramite,
            fecha_suspension=p.fecha_suspension,
            fecha_reactivacion=p.fecha_reactivacion,
        )
        for p in plazo_rows
    ]

    notif_rows = (
        await session.execute(
            select(NotificacionFamilia)
            .where(NotificacionFamilia.causa_familia_id == causa.id)
            .order_by(NotificacionFamilia.id)
        )
    ).scalars().all()
    notificaciones = [
        NotificacionFamiliaItem(
            estado_fecha_notif=n.estado_fecha_notif,
            tipo_notif=n.tipo_notif,
            ente_notif=n.ente_notif,
            rit=n.rit,
            ruc=n.ruc,
            fecha_tramite=n.fecha_tramite,
            tipo_parte=n.tipo_parte,
            nombre=n.nombre,
            tramite=n.tramite,
            certificacion=n.certificacion,
        )
        for n in notif_rows
    ]

    diligencia_rows = (
        await session.execute(
            select(DiligenciaFamilia)
            .where(DiligenciaFamilia.causa_familia_id == causa.id)
            .order_by(DiligenciaFamilia.id)
        )
    ).scalars().all()
    diligencias = [
        DiligenciaItem(
            doc_solicitud=doc_url(d.doc_solicitud_id),
            doc_respuesta=doc_url(d.doc_respuesta_id),
            estado_diligencia=d.estado_diligencia,
            tipo_diligencia=d.tipo_diligencia,
            fecha_tramite=d.fecha_tramite,
        )
        for d in diligencia_rows
    ]

    return MovimientosFamiliaResponse(
        movimientos=movimientos,
        litigantes=litigantes,
        materias=materias,
        plazos=plazos,
        notificaciones=notificaciones,
        diligencias=diligencias,
    )
