import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import Principal, obtener_principal
from api.civil.cripto import cifrar
from api.penal.repository import (
    buscar_causa,
    construir_causa_detalle,
    construir_movimientos,
    encolar_sync_job,
    intentar_lock_sincronizacion,
    obtener_o_crear_causa,
)
from api.penal.schemas import (
    ConsultarPenalResponse,
    MovimientosPenalResponse,
    MovimientosRequest,
    CausaPenalRequest,
    SincronizarPenalRequest,
    SincronizarResponse,
)
from api.common.rut import normalizar_credenciales
from api.config import settings
from api.penal.urls import normalizar_tipo_penal
from api.db.models.penal import CausaPenal
from api.db.session_async import get_session
from api.errors.exceptions import CampoInvalidoError, ConflictoSincronizacionError, NoEncontradoError

router = APIRouter(tags=["penal"])


@router.post("/sincronizar_penal", response_model=SincronizarResponse)
async def sincronizar_penal(
    body: SincronizarPenalRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    # Penal admite ambos modos (publico/privado), igual que civil/laboral.
    credenciales = normalizar_credenciales(body.rut, body.clave, body.metodo_login, obligatorias=False)

    tipo = normalizar_tipo_penal(body.tipo)
    if tipo is None:
        raise CampoInvalidoError("tipo")

    causa = await obtener_o_crear_causa(
        session, body.corte, body.tribunal, tipo, body.rol, body.anio
    )

    # Se leen antes del CAS de lock: ese commit expira los atributos del ORM.
    sync_iniciado_en = causa.sync_iniciado_en

    if causa.fecha_ultima_sincronizacion is not None:
        ahora = datetime.now(timezone.utc)
        umbral = timedelta(minutes=settings.sync_min_interval_minutes)
        transcurrido = ahora - causa.fecha_ultima_sincronizacion
        if transcurrido < umbral:
            reintentar_en = causa.fecha_ultima_sincronizacion + umbral
            raise ConflictoSincronizacionError(
                motivo="intervalo_minimo",
                detalle=(
                    f"La causa se sincronizo hace {int(transcurrido.total_seconds() // 60)} min. "
                    f"El intervalo minimo entre sincronizaciones es {settings.sync_min_interval_minutes} min; "
                    f"se puede reintentar a partir de {reintentar_en.isoformat()}."
                ),
                reintentar_en=reintentar_en.isoformat(),
            )

    lock_obtenido = await intentar_lock_sincronizacion(session, causa.id, settings.sync_lock_timeout_minutes)
    if not lock_obtenido:
        expira_en = None
        if sync_iniciado_en is not None:
            expira_en = (
                sync_iniciado_en + timedelta(minutes=settings.sync_lock_timeout_minutes)
            ).isoformat()
        raise ConflictoSincronizacionError(
            motivo="sincronizacion_en_curso",
            detalle=(
                "Ya hay una sincronizacion en curso para esta causa"
                + (f" (iniciada {sync_iniciado_en.isoformat()})" if sync_iniciado_en else "")
                + (f"; el lock expira a las {expira_en}." if expira_en else ".")
            ),
            reintentar_en=expira_en,
        )

    if credenciales is not None:
        rut, clave, metodo_login = credenciales
        await encolar_sync_job(
            session,
            causa.id,
            rut_cifrado=cifrar(rut),
            clave_cifrada=cifrar(clave),
            metodo_login=metodo_login,
        )
    else:
        await encolar_sync_job(session, causa.id)
    return SincronizarResponse()


@router.post("/consultar_penal", response_model=ConsultarPenalResponse)
async def consultar_penal(
    body: CausaPenalRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    tipo = normalizar_tipo_penal(body.tipo)
    if tipo is None:
        raise CampoInvalidoError("tipo")
    causa = await buscar_causa(session, body.corte, body.tribunal, tipo, body.rol, body.anio)
    if causa is None:
        raise NoEncontradoError()

    detalle = await construir_causa_detalle(session, causa)
    return ConsultarPenalResponse(causa=detalle)


@router.post("/consultar_movimientos_penal", response_model=MovimientosPenalResponse)
async def consultar_movimientos_penal(
    body: MovimientosRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    try:
        causa_id = uuid.UUID(body.identificador)
    except (ValueError, AttributeError):
        raise CampoInvalidoError("identificador")

    causa = (await session.execute(select(CausaPenal).where(CausaPenal.id == causa_id))).scalar_one_or_none()
    if causa is None:
        raise NoEncontradoError()

    return await construir_movimientos(session, causa)
