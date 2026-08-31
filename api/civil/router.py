import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import Principal, obtener_principal
from api.civil.cripto import cifrar
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
    SincronizarCivilRequest,
    SincronizarResponse,
)
from api.config import settings
from api.db.models.causas import Causa
from api.db.session_async import get_session
from api.errors.exceptions import CampoInvalidoError, ConflictoSincronizacionError, NoEncontradoError

router = APIRouter(tags=["civil"])

COMPETENCIA = "civil"

_RUT_RE = re.compile(r"^(\d{7,8})(?:-([\dkK]))?$")


def _digito_verificador(cuerpo: str) -> str:
    suma, factor = 0, 2
    for digito in reversed(cuerpo):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    return "0" if resto == 11 else "K" if resto == 10 else str(resto)


def _normalizar_credenciales(body: SincronizarCivilRequest) -> tuple[str, str, int] | None:
    """Devuelve (rut, clave, metodo_login) si el request pide modo privado, o None si
    es una sincronizacion publica. Valida que los tres campos vengan juntos y bien
    formados; cualquier problema es un 400 'Error en campo [...]'. El RUT se normaliza
    siempre a 'cuerpo-DV' (con o sin puntos, con o sin DV en la entrada); el DV se
    calcula si no vino y se valida si vino."""
    if body.rut is None and body.clave is None and body.metodo_login is None:
        return None

    if not body.rut:
        raise CampoInvalidoError("rut")
    if not body.clave:
        raise CampoInvalidoError("clave")
    if body.metodo_login not in (1, 2):
        raise CampoInvalidoError("metodo_login")

    match = _RUT_RE.match(body.rut.strip().replace(".", "").replace(" ", "").upper())
    if match is None:
        raise CampoInvalidoError("rut")
    cuerpo, dv = match.group(1), match.group(2)
    esperado = _digito_verificador(cuerpo)
    if dv is not None and dv != esperado:
        raise CampoInvalidoError("rut")

    return f"{cuerpo}-{esperado}", body.clave, body.metodo_login


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
