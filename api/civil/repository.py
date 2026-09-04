from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.civil.schemas import (
    AnexoCausaItem,
    CausaDetalle,
    CuadernoItem,
    DocumentoRef,
    EscritoResolverItem,
    ExhortoItem,
    ExhortoRolDestinoItem as ExhortoRolDestinoSchema,
    ExhortoRolItem,
    HistoriaAnexoItem,
    HistoriaDocItem,
    HistoriaItem,
    InformacionReceptorItem,
    LitiganteItem,
    MovimientosResponse,
    NotificacionItem,
)
from api.civil.urls import rol_formateado, url_publica_documento
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
from api.db.models.sync_job import SyncJob

CAMPO_ESTADO_SINCRONIZANDO = "Sincronizando"
CAMPO_ESTADO_COMPLETO = "Completo"
CAMPO_ESTADO_ERROR = "Error"


async def obtener_o_crear_causa(
    session: AsyncSession, competencia: str, corte: int, tribunal: int, tipo: str, rol: int, anio: int
) -> Causa:
    stmt = select(Causa).where(
        Causa.competencia == competencia,
        Causa.corte == corte,
        Causa.tribunal == tribunal,
        Causa.tipo == tipo,
        Causa.rol == rol,
        Causa.anio == anio,
    )
    causa = (await session.execute(stmt)).scalar_one_or_none()
    if causa is not None:
        return causa

    causa = Causa(
        competencia=competencia,
        corte=corte,
        tribunal=tribunal,
        tipo=tipo,
        rol=rol,
        anio=anio,
        rol_formateado=rol_formateado(tipo, rol, anio),
        estado_sync="Pendiente",
    )
    session.add(causa)
    try:
        await session.commit()
    except IntegrityError:
        # Carrera: otra request creo la misma causa (misma clave natural) primero.
        await session.rollback()
        causa = (await session.execute(stmt)).scalar_one()
        return causa
    await session.refresh(causa)
    return causa


async def buscar_causa(
    session: AsyncSession, competencia: str, corte: int, tribunal: int, tipo: str, rol: int, anio: int
) -> Causa | None:
    stmt = select(Causa).where(
        Causa.competencia == competencia,
        Causa.corte == corte,
        Causa.tribunal == tribunal,
        Causa.tipo == tipo,
        Causa.rol == rol,
        Causa.anio == anio,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def intentar_lock_sincronizacion(session: AsyncSession, causa_id, timeout_minutes: int) -> bool:
    """CAS atomico: solo tiene exito si la causa no esta 'Sincronizando' vigente. Un
    UPDATE ... WHERE ... RETURNING no afecta ninguna fila si ya hay un lock activo -> eso
    es la senal de 409 Conflicto, sin necesitar locks externos (Redis, etc.)."""
    ahora = datetime.now(timezone.utc)
    umbral = ahora - timedelta(minutes=timeout_minutes)
    stmt = (
        update(Causa)
        .where(
            Causa.id == causa_id,
            or_(Causa.estado_sync != CAMPO_ESTADO_SINCRONIZANDO, Causa.sync_iniciado_en < umbral),
        )
        .values(estado_sync=CAMPO_ESTADO_SINCRONIZANDO, sync_iniciado_en=ahora)
        .returning(Causa.id)
    )
    resultado = await session.execute(stmt)
    fila = resultado.first()
    await session.commit()
    return fila is not None


async def encolar_sync_job(
    session: AsyncSession,
    causa_id,
    *,
    rut_cifrado: str | None = None,
    clave_cifrada: str | None = None,
    metodo_login: int | None = None,
) -> None:
    session.add(
        SyncJob(
            causa_id=causa_id,
            estado="pendiente",
            rut_cifrado=rut_cifrado,
            clave_cifrada=clave_cifrada,
            metodo_login=metodo_login,
        )
    )
    await session.commit()
    await session.execute(text("NOTIFY sync_jobs"))
    await session.commit()


def _doc_ref(doc: Documento | None, causa_id, cuaderno_numero: int | None = None) -> DocumentoRef | None:
    if doc is None:
        return None
    return DocumentoRef(
        nombre_archivo=doc.nombre_archivo,
        url=url_publica_documento(causa_id, doc.nombre_archivo, cuaderno_numero),
    )


async def construir_causa_detalle(session: AsyncSession, causa: Causa) -> CausaDetalle:
    rol_fmt = causa.rol_formateado

    documentos_cabecera = (
        await session.execute(
            select(Documento).where(Documento.causa_id == causa.id, Documento.cuaderno_id.is_(None))
        )
    ).scalars().all()
    docs_por_categoria: dict[str, Documento] = {}
    docs_por_id: dict = {}
    for d in documentos_cabecera:
        docs_por_categoria.setdefault(d.categoria, d)
        docs_por_id[d.id] = d

    anexos_rows = (
        await session.execute(select(AnexoCausa).where(AnexoCausa.causa_id == causa.id))
    ).scalars().all()
    anexos = [
        AnexoCausaItem(
            fecha=a.fecha,
            referencia=a.referencia,
            nombre_doc=docs_por_id[a.documento_id].nombre_archivo if a.documento_id in docs_por_id else None,
            doc=(
                url_publica_documento(causa.id, docs_por_id[a.documento_id].nombre_archivo)
                if a.documento_id in docs_por_id
                else None
            ),
        )
        for a in anexos_rows
    ]

    info_rows = (
        await session.execute(select(InformacionReceptor).where(InformacionReceptor.causa_id == causa.id))
    ).scalars().all()
    informacion_receptor = [
        InformacionReceptorItem(
            cuaderno=r.cuaderno_nombre, datos_retiro=r.datos_retiro, fecha_retiro=r.fecha_retiro, estado=r.estado
        )
        for r in info_rows
    ]

    cuadernos_rows = (
        await session.execute(select(Cuaderno).where(Cuaderno.causa_id == causa.id).order_by(Cuaderno.numero))
    ).scalars().all()
    cuadernos = [CuadernoItem(id=c.numero, nombre=c.nombre) for c in cuadernos_rows]

    # `estado_sync` en BD tiene un cuarto valor ("Pendiente", antes de que el worker
    # tome el job) que hacia afuera se expone igual que "Sincronizando" -- para el
    # cliente ambos significan "todavia no hay resultado, segui consultando".
    if causa.estado_sync == CAMPO_ESTADO_COMPLETO:
        estado_expuesto = CAMPO_ESTADO_COMPLETO
    elif causa.estado_sync == CAMPO_ESTADO_ERROR:
        estado_expuesto = CAMPO_ESTADO_ERROR
    else:
        estado_expuesto = CAMPO_ESTADO_SINCRONIZANDO

    return CausaDetalle(
        identificador=str(causa.id),
        estado=estado_expuesto,
        detalle_estado=(causa.sync_detalle if estado_expuesto == CAMPO_ESTADO_SINCRONIZANDO else None),
        ultimo_error=(causa.ultimo_error if estado_expuesto == CAMPO_ESTADO_ERROR else None),
        fecha_ultima_sincronizacion=(
            causa.fecha_ultima_sincronizacion.date().isoformat() if causa.fecha_ultima_sincronizacion else None
        ),
        rol=rol_fmt,
        fecha_ingreso=causa.fecha_ingreso,
        caratula=causa.caratula,
        est_adm=causa.est_adm,
        proceso=causa.proceso,
        ubicacion=causa.ubicacion,
        estado_proceso=causa.estado_proceso,
        etapa=causa.etapa,
        tribunal=causa.tribunal_nombre,
        texto_demanda=_doc_ref(docs_por_categoria.get("texto_demanda"), causa.id),
        certificado_envio=_doc_ref(docs_por_categoria.get("certificado_envio"), causa.id),
        ebook=_doc_ref(docs_por_categoria.get("ebook"), causa.id),
        anexos_causa=anexos,
        informacion_receptor=informacion_receptor,
        cuadernos=cuadernos,
    )


async def obtener_cuaderno(session: AsyncSession, causa_id, numero: int) -> Cuaderno | None:
    stmt = select(Cuaderno).where(Cuaderno.causa_id == causa_id, Cuaderno.numero == numero)
    return (await session.execute(stmt)).scalar_one_or_none()


async def construir_movimientos(session: AsyncSession, causa: Causa, cuaderno: Cuaderno) -> MovimientosResponse:
    todos_docs = (await session.execute(select(Documento).where(Documento.causa_id == causa.id))).scalars().all()
    docs_por_id = {d.id: d for d in todos_docs}

    def doc_url(documento_id) -> str | None:
        doc = docs_por_id.get(documento_id)
        return url_publica_documento(causa.id, doc.nombre_archivo, cuaderno.numero) if doc else None

    historia_rows = (
        await session.execute(
            select(MovimientoHistoria)
            .where(MovimientoHistoria.cuaderno_id == cuaderno.id)
            .order_by(MovimientoHistoria.orden, MovimientoHistoria.id)
        )
    ).scalars().all()
    historia_items = []
    for h in historia_rows:
        doc_rows = (
            await session.execute(
                select(MovimientoHistoriaDoc)
                .where(MovimientoHistoriaDoc.movimiento_id == h.id)
                .order_by(MovimientoHistoriaDoc.orden)
            )
        ).scalars().all()
        anexo_rows = (
            await session.execute(
                select(MovimientoHistoriaAnexo)
                .where(MovimientoHistoriaAnexo.movimiento_id == h.id)
                .order_by(MovimientoHistoriaAnexo.orden)
            )
        ).scalars().all()
        historia_items.append(
            HistoriaItem(
                folio=h.folio,
                # "[SF]" es el marcador interno de una fila sin folio; hacia afuera va vacio.
                folio_texto=None if h.folio_texto == "[SF]" else h.folio_texto,
                doc=[HistoriaDocItem(doc=doc_url(d.documento_id)) for d in doc_rows],
                anexo=[
                    HistoriaAnexoItem(doc=doc_url(a.documento_id), fecha=a.fecha, referencia=a.referencia)
                    for a in anexo_rows
                ],
                etapa=h.etapa,
                tramite=h.tramite,
                descripcion_tramite=h.descripcion_tramite,
                fecha_tramite=h.fecha_tramite,
                foja=h.foja,
            )
        )

    litigante_rows = (
        await session.execute(select(Litigante).where(Litigante.cuaderno_id == cuaderno.id).order_by(Litigante.id))
    ).scalars().all()
    litigantes = [
        LitiganteItem(participante=l.participante, rut=l.rut, persona=l.persona, razon_social=l.razon_social)
        for l in litigante_rows
    ]

    notif_rows = (
        await session.execute(
            select(Notificacion).where(Notificacion.cuaderno_id == cuaderno.id).order_by(Notificacion.id)
        )
    ).scalars().all()
    notificaciones = [
        NotificacionItem(
            rol=n.rol,
            estado_notificacion=n.estado_notificacion,
            tipo_notificacion=n.tipo_notificacion,
            fecha_tramite=n.fecha_tramite,
            tipo_part=n.tipo_part,
            nombre=n.nombre,
            tramite=n.tramite,
            observacion_fallida=n.observacion_fallida,
        )
        for n in notif_rows
    ]

    escrito_rows = (
        await session.execute(
            select(EscritoResolver).where(EscritoResolver.cuaderno_id == cuaderno.id).order_by(EscritoResolver.id)
        )
    ).scalars().all()
    escritos_resolver = [
        EscritoResolverItem(
            doc=doc_url(e.documento_id),
            anexo="",
            fecha_ingreso=e.fecha_ingreso,
            tipo_escrito=e.tipo_escrito,
            solicitante=e.solicitante,
        )
        for e in escrito_rows
    ]

    exhorto_rows = (
        await session.execute(select(Exhorto).where(Exhorto.cuaderno_id == cuaderno.id).order_by(Exhorto.id))
    ).scalars().all()
    exhortos = []
    for ex in exhorto_rows:
        rol_destino_rows = (
            await session.execute(
                select(ExhortoRolDestino)
                .where(ExhortoRolDestino.exhorto_id == ex.id)
                .order_by(ExhortoRolDestino.id)
            )
        ).scalars().all()
        rol_destino_items = []
        for rd in rol_destino_rows:
            item_rows = (
                await session.execute(
                    select(ExhortoRolDestinoItem)
                    .where(ExhortoRolDestinoItem.rol_destino_id == rd.id)
                    .order_by(ExhortoRolDestinoItem.orden)
                )
            ).scalars().all()
            rol_destino_items.append(
                ExhortoRolDestinoSchema(
                    nombre=rd.nombre,
                    roles=[
                        ExhortoRolItem(doc=doc_url(it.documento_id), fecha=it.fecha, referencia=it.referencia, tramite=it.tramite)
                        for it in item_rows
                    ],
                )
            )
        exhortos.append(
            ExhortoItem(
                rol_origen=ex.rol_origen,
                tipo_exhorto=ex.tipo_exhorto,
                rol_destino=rol_destino_items,
                fecha_ordena_exhorto=ex.fecha_ordena_exhorto,
                fecha_ingreso_exhorto=ex.fecha_ingreso_exhorto,
                tribunal_destino=ex.tribunal_destino,
                estado_exhorto=ex.estado_exhorto,
            )
        )

    return MovimientosResponse(
        historia=historia_items,
        litigantes=litigantes,
        notificaciones=notificaciones,
        escritos_resolver=escritos_resolver,
        exhortos=exhortos,
    )
