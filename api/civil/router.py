import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import Principal, obtener_principal
from api.common.acceso import exigir_acceso, proteger_respuesta
from api.civil.cripto import cifrar
from api.common.rut import normalizar_credenciales
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
    ConsultarCausaRequest,
    ConsultarCivilResponse,
    MovimientosRequest,
    MovimientosResponse,
    SincronizarCivilRequest,
    SincronizarResponse,
)
from api.config import settings
from api.db.models.causas import Causa
from api.db.session_async import get_session
from api.errors.exceptions import CampoInvalidoError, ConflictoSincronizacionError, NoEncontradoError

router = APIRouter(tags=["civil"])

COMPETENCIA = "civil"


def _normalizar_credenciales(body: SincronizarCivilRequest) -> tuple[str, str, int] | None:
    """Devuelve (rut, clave, metodo_login) si el request pide modo privado, o None si
    es una sincronizacion publica (civil admite ambos)."""
    return normalizar_credenciales(body.rut, body.clave, body.metodo_login, obligatorias=False)


@router.post("/sincronizar_civil", response_model=SincronizarResponse)
async def sincronizar_civil(
    body: SincronizarCivilRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    credenciales = _normalizar_credenciales(body)

    causa = await obtener_o_crear_causa(
        session, COMPETENCIA, body.corte, body.tribunal, body.tipo, body.rol, body.anio
    )

    # Se leen antes del CAS de lock: ese commit expira los atributos del ORM y en el
    # contexto async un lazy-load posterior fallaria.
    sync_iniciado_en = causa.sync_iniciado_en

    if causa.fecha_ultima_sincronizacion is not None:
        ahora = datetime.now(timezone.utc)
        umbral = timedelta(minutes=settings.sync_min_interval_minutes)
        transcurrido = ahora - causa.fecha_ultima_sincronizacion
        if transcurrido < umbral:
            # La causa esta al dia: con callback no se rechaza, se avisa exito=true por el callback.
            if body.callback_url:
                job_id = await encolar_sync_job(session, causa.id, callback_url=body.callback_url, omitida=True)
                return SincronizarResponse(job_id=job_id)
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
        job_id = await encolar_sync_job(
            session,
            causa.id,
            rut_cifrado=cifrar(rut),
            clave_cifrada=cifrar(clave),
            metodo_login=metodo_login,
            callback_url=body.callback_url,
        )
    else:
        job_id = await encolar_sync_job(session, causa.id, callback_url=body.callback_url)
    return SincronizarResponse(job_id=job_id)


@router.post("/consultar_civil", response_model=ConsultarCivilResponse)
async def consultar_civil(
    body: ConsultarCausaRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    causa = await buscar_causa(session, COMPETENCIA, body.corte, body.tribunal, body.tipo, body.rol, body.anio)
    await exigir_acceso(session, "civil", causa, body.rut)

    detalle = await construir_causa_detalle(session, causa)
    return proteger_respuesta(ConsultarCivilResponse(causa=detalle), "civil", causa)


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
    await exigir_acceso(session, "civil", causa, body.rut)

    cuaderno = await obtener_cuaderno(session, causa.id, body.cuadeno)
    if cuaderno is None:
        raise NoEncontradoError()

    return proteger_respuesta(await construir_movimientos(session, causa, cuaderno), "civil", causa)
