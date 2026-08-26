import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import Principal, obtener_principal
from api.civil.repository import (
    buscar_causa,
    construir_causa_detalle,
    construir_movimientos,
    encolar_sync_job,
    intentar_lock_sincronizacion,
    obtener_cuaderno,
    obtener_o_crear_causa,
)
from api.civil.schemas import (
    CausaRequest,
    ConsultarCivilResponse,
    MovimientosRequest,
    MovimientosResponse,
    SincronizarResponse,
)
from api.config import settings
from api.db.models.causas import Causa
from api.db.session_async import get_session
from api.errors.exceptions import CampoInvalidoError, ConflictoSincronizacionError, NoEncontradoError

router = APIRouter(tags=["civil"])

COMPETENCIA = "civil"


@router.post("/sincronizar_civil", response_model=SincronizarResponse)
async def sincronizar_civil(
    body: CausaRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    causa = await obtener_o_crear_causa(
        session, COMPETENCIA, body.corte, body.tribunal, body.tipo, body.rol, body.anio
    )

    if causa.fecha_ultima_sincronizacion is not None:
        ahora = datetime.now(timezone.utc)
        umbral = timedelta(minutes=settings.sync_min_interval_minutes)
        if ahora - causa.fecha_ultima_sincronizacion < umbral:
            raise ConflictoSincronizacionError()

    lock_obtenido = await intentar_lock_sincronizacion(session, causa.id, settings.sync_lock_timeout_minutes)
    if not lock_obtenido:
        raise ConflictoSincronizacionError()

    await encolar_sync_job(session, causa.id)
    return SincronizarResponse()


@router.post("/consultar_civil", response_model=ConsultarCivilResponse)
async def consultar_civil(
    body: CausaRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    causa = await buscar_causa(session, COMPETENCIA, body.corte, body.tribunal, body.tipo, body.rol, body.anio)
    if causa is None:
        raise NoEncontradoError()

    detalle = await construir_causa_detalle(session, causa)
    return ConsultarCivilResponse(causa=detalle)


@router.post("/consultar_movimientos_civil", response_model=MovimientosResponse)
async def consultar_movimientos_civil(
    body: MovimientosRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    try:
        causa_id = uuid.UUID(body.identificador)
    except (ValueError, AttributeError):
        raise CampoInvalidoError("identificador")

    causa = (await session.execute(select(Causa).where(Causa.id == causa_id))).scalar_one_or_none()
    if causa is None:
        raise NoEncontradoError()

    cuaderno = await obtener_cuaderno(session, causa.id, body.cuadeno)
    if cuaderno is None:
        raise NoEncontradoError()

    return await construir_movimientos(session, causa, cuaderno)
