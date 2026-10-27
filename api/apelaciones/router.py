import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.apelaciones.cortes import resolver_corte
from api.apelaciones.repository import (
    buscar_causa,
    construir_causa_detalle,
    construir_movimientos,
    encolar_sync_job,
    intentar_lock_sincronizacion,
    obtener_o_crear_causa,
)
from api.apelaciones.schemas import (
    ConsultarApelacionesRequest,
    ConsultarApelacionesResponse,
    MovimientosApelacionesResponse,
    MovimientosRequest,
    SincronizarApelacionesRequest,
    SincronizarResponse,
)
from api.auth.dependencies import Principal, obtener_principal
from api.civil.cripto import cifrar
from api.common.acceso import exigir_acceso, proteger_respuesta
from api.common.rut import normalizar_credenciales
from api.config import settings
from api.db.models.apelaciones import CausaApelaciones
from api.db.session_async import get_session
from api.errors.exceptions import CampoInvalidoError, ConflictoSincronizacionError

router = APIRouter(tags=["apelaciones"])


def _corte_o_400(valor) -> int:
    corte = resolver_corte(valor)
    if corte is None:
        raise CampoInvalidoError("corte")
    return corte


@router.post("/sincronizar_apelaciones", response_model=SincronizarResponse)
async def sincronizar_apelaciones(
    body: SincronizarApelacionesRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    # Admite ambos modos (publico/privado), igual que civil/laboral/penal.
    credenciales = normalizar_credenciales(body.rut, body.clave, body.metodo_login, obligatorias=False)
    corte = _corte_o_400(body.corte)

    causa = await obtener_o_crear_causa(session, corte, body.libro, body.rol, body.anio)

    # Se leen antes del CAS de lock: ese commit expira los atributos del ORM.
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
            expira_en = (sync_iniciado_en + timedelta(minutes=settings.sync_lock_timeout_minutes)).isoformat()
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
            session, causa.id, rut_cifrado=cifrar(rut), clave_cifrada=cifrar(clave), metodo_login=metodo_login,
            callback_url=body.callback_url,
        )
    else:
        job_id = await encolar_sync_job(session, causa.id, callback_url=body.callback_url)
    return SincronizarResponse(job_id=job_id)


@router.post("/consultar_apelaciones", response_model=ConsultarApelacionesResponse)
async def consultar_apelaciones(
    body: ConsultarApelacionesRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    corte = _corte_o_400(body.corte)
    causa = await buscar_causa(session, corte, body.libro, body.rol, body.anio)
    await exigir_acceso(session, "apelaciones", causa, body.rut)

    detalle = await construir_causa_detalle(session, causa)
    return proteger_respuesta(ConsultarApelacionesResponse(causa=detalle), "apelaciones", causa)


@router.post("/consultar_movimientos_apelaciones", response_model=MovimientosApelacionesResponse)
async def consultar_movimientos_apelaciones(
    body: MovimientosRequest,
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    try:
        causa_id = uuid.UUID(body.identificador)
    except (ValueError, AttributeError):
        raise CampoInvalidoError("identificador")

    causa = (
        await session.execute(select(CausaApelaciones).where(CausaApelaciones.id == causa_id))
    ).scalar_one_or_none()
    await exigir_acceso(session, "apelaciones", causa, body.rut)

    return proteger_respuesta(await construir_movimientos(session, causa), "apelaciones", causa)
