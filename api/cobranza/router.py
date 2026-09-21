import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import Principal, obtener_principal
from api.civil.cripto import cifrar
from api.civil.schemas import CausaRequest
from api.cobranza.repository import (
    buscar_causa,
    construir_causa_detalle,
    construir_movimientos,
    encolar_sync_job,
    intentar_lock_sincronizacion,
    obtener_o_crear_causa,
)
from api.cobranza.schemas import (
    ConsultarCobranzaResponse,
    MovimientosCobranzaResponse,
    MovimientosRequest,
    SincronizarCobranzaRequest,
    SincronizarResponse,
)
from api.common.rut import normalizar_credenciales
from api.config import settings
from api.db.models.cobranza import CausaCobranza
from api.db.session_async import get_session
from api.errors.exceptions import CampoInvalidoError, ConflictoSincronizacionError, NoEncontradoError

router = APIRouter(tags=["cobranza"])


@router.post("/sincronizar_cobranza", response_model=SincronizarResponse)
async def sincronizar_cobranza(
    body: SincronizarCobranzaRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    # Cobranza admite ambos modos (publico/privado), igual que civil/laboral.
    credenciales = normalizar_credenciales(body.rut, body.clave, body.metodo_login, obligatorias=False)

    causa = await obtener_o_crear_causa(
        session, body.corte, body.tribunal, body.tipo, body.rol, body.anio
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


@router.post("/consultar_cobranza", response_model=ConsultarCobranzaResponse)
async def consultar_cobranza(
    body: CausaRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    causa = await buscar_causa(session, body.corte, body.tribunal, body.tipo, body.rol, body.anio)
    if causa is None:
        raise NoEncontradoError()

    detalle = await construir_causa_detalle(session, causa)
    return ConsultarCobranzaResponse(causa=detalle)


@router.post("/consultar_movimientos_cobranza", response_model=MovimientosCobranzaResponse)
async def consultar_movimientos_cobranza(
    body: MovimientosRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    try:
        causa_id = uuid.UUID(body.identificador)
    except (ValueError, AttributeError):
        raise CampoInvalidoError("identificador")

    causa = (await session.execute(select(CausaCobranza).where(CausaCobranza.id == causa_id))).scalar_one_or_none()
    if causa is None:
        raise NoEncontradoError()

    return await construir_movimientos(session, causa)
