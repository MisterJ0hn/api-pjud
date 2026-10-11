"""Control de acceso de `consultar_*` a las causas almacenadas.

Reglas:
1. Causa marcada `publica` (obtenida de la Consulta Unificada) -> se entrega sin mas.
2. Cualquier otra (`privada` o sin marcar) requiere credenciales de PJUD (rut + clave +
   metodo_login). Se comprueba que la causa aparezca en "Mis Causas" del abogado; esa
   comprobacion la hace el worker (unico dueno de Playwright) via un `sync_job` de tipo
   "verificacion", y el endpoint espera el resultado.
3. Sin credenciales, o si la causa no aparece en Mis Causas -> 404 (igual que una causa
   inexistente, para no revelar que existe).

Las verificaciones exitosas se cachean `acceso_cache_minutos` por (causa, huella), donde la
huella es un HMAC de rut+clave+metodo: no se guardan credenciales y una clave distinta no
reutiliza la verificacion.
"""

import asyncio
import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.civil.cripto import cifrar
from api.common.rut import normalizar_credenciales
from api.config import settings
from api.db.models.acceso import AccesoVerificado
from api.db.models.sync_job import SyncJob
from api.db.session_async import AsyncSessionLocal
from api.errors.exceptions import (
    ConflictoSincronizacionError,
    CredencialesPjudInvalidasError,
    NoEncontradoError,
    VerificacionAccesoError,
)

VISIBILIDAD_PUBLICA = "publica"
VISIBILIDAD_PRIVADA = "privada"

# Prefijo de `sync_job.error_mensaje` cuando el login en PJUD fallo (credenciales malas).
ERROR_CREDENCIALES = "credenciales_invalidas"

# Columna de `SyncJob` que apunta a la causa de cada competencia.
COLUMNA_JOB = {
    "civil": "causa_id",
    "familia": "causa_familia_id",
    "laboral": "causa_laboral_id",
    "cobranza": "causa_cobranza_id",
    "penal": "causa_penal_id",
}

_POLL_INTERVALO_S = 1.0


def huella_credenciales(rut: str, clave: str, metodo_login: int) -> str:
    clave_hmac = settings.pjud_cred_secret_key
    if not clave_hmac:
        raise RuntimeError("PJUD_CRED_SECRET_KEY no configurada")
    mensaje = f"{rut}\x00{clave}\x00{metodo_login}".encode("utf-8")
    return hmac.new(clave_hmac.encode("utf-8"), mensaje, hashlib.sha256).hexdigest()


async def registrar_acceso(session: AsyncSession, competencia: str, causa_id, huella: str) -> None:
    stmt = pg_insert(AccesoVerificado).values(competencia=competencia, causa_id=causa_id, huella=huella)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_acceso_verificado", set_={"verificado_en": datetime.now(timezone.utc)}
    )
    await session.execute(stmt)


async def _acceso_en_cache(session: AsyncSession, competencia: str, causa_id, huella: str) -> bool:
    desde = datetime.now(timezone.utc) - timedelta(minutes=settings.acceso_cache_minutos)
    fila = (
        await session.execute(
            select(AccesoVerificado.id).where(
                AccesoVerificado.competencia == competencia,
                AccesoVerificado.causa_id == causa_id,
                AccesoVerificado.huella == huella,
                AccesoVerificado.verificado_en > desde,
            )
        )
    ).first()
    return fila is not None


async def _job_verificacion(
    session: AsyncSession, competencia: str, causa_id, huella: str, credenciales: tuple[str, str, int]
) -> int:
    """Devuelve el id de un job de verificacion vigente para esta causa+huella, o encola uno."""
    columna = getattr(SyncJob, COLUMNA_JOB[competencia])
    existente = (
        await session.execute(
            select(SyncJob.id).where(
                SyncJob.tipo == "verificacion",
                SyncJob.estado.in_(("pendiente", "en_progreso")),
                SyncJob.huella_acceso == huella,
                columna == causa_id,
            )
        )
    ).scalars().first()
    if existente is not None:
        return existente
    job = SyncJob(
        **{COLUMNA_JOB[competencia]: causa_id},
        tipo="verificacion",
        estado="pendiente",
        huella_acceso=huella,
        rut_cifrado=cifrar(credenciales[0]),
        clave_cifrada=cifrar(credenciales[1]),
        metodo_login=credenciales[2],
    )
    session.add(job)
    await session.commit()
    await session.execute(text("NOTIFY sync_jobs"))
    await session.commit()
    return job.id


async def exigir_acceso(session: AsyncSession, competencia: str, causa, rut, clave, metodo_login) -> None:
    """Lanza `NoEncontradoError` (404) si el solicitante no puede ver `causa`.

    `causa` puede ser None (causa inexistente): se trata igual que "sin acceso".
    Los campos de credenciales se validan aca (400 si vienen incompletos o mal formados).
    """
    credenciales = normalizar_credenciales(rut, clave, metodo_login, obligatorias=False)

    if causa is None:
        raise NoEncontradoError()
    if causa.visibilidad == VISIBILIDAD_PUBLICA:
        return
    if credenciales is None:
        raise NoEncontradoError()

    causa_id = causa.id
    huella = huella_credenciales(*credenciales)
    if await _acceso_en_cache(session, competencia, causa_id, huella):
        return

    job_id = await _job_verificacion(session, competencia, causa_id, huella, credenciales)

    limite = time.monotonic() + settings.acceso_verificacion_timeout_s
    while time.monotonic() < limite:
        # Sesion corta por consulta: asi se ven los commits del worker sin hacer rollback
        # de `session` (expiraria `causa`, que el router sigue usando).
        async with AsyncSessionLocal() as sesion_poll:
            fila = (
                await sesion_poll.execute(
                    select(SyncJob.estado, SyncJob.acceso_concedido, SyncJob.error_mensaje).where(
                        SyncJob.id == job_id
                    )
                )
            ).first()
        if fila is not None and fila.estado == "completo":
            if fila.acceso_concedido:
                return
            raise NoEncontradoError()
        if fila is not None and fila.estado == "error":
            if (fila.error_mensaje or "").startswith(ERROR_CREDENCIALES):
                raise CredencialesPjudInvalidasError()
            raise VerificacionAccesoError(fila.error_mensaje)
        await asyncio.sleep(_POLL_INTERVALO_S)

    # El job sigue en cola; cuando termine, el worker deja la verificacion en cache y el
    # reintento del cliente responde de inmediato.
    raise ConflictoSincronizacionError(
        motivo="verificacion_en_curso",
        detalle="La verificacion de acceso a la causa en PJUD sigue en curso; reintente en unos segundos.",
    )


# --- Token firmado para las URLs de documentos (/public/...) ------------------------
# Los documentos se piden por GET (sin cuerpo), asi que no pueden llevar credenciales. Los de
# causas no publicas exigen `?t=<expira>.<firma>`, que solo se agrega a las URLs de una
# respuesta que ya paso `exigir_acceso`.


def _firma(competencia: str, causa_id, expira: int) -> str:
    clave = settings.pjud_cred_secret_key
    if not clave:
        raise RuntimeError("PJUD_CRED_SECRET_KEY no configurada")
    mensaje = f"doc:{competencia}:{causa_id}:{expira}".encode("utf-8")
    return hmac.new(clave.encode("utf-8"), mensaje, hashlib.sha256).hexdigest()


def generar_token_documento(competencia: str, causa_id) -> str:
    expira = int(time.time()) + settings.documento_token_minutos * 60
    return f"{expira}.{_firma(competencia, causa_id, expira)}"


def token_documento_valido(competencia: str, causa_id, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expira_txt, firma = token.split(".", 1)
    if not expira_txt.isdigit() or int(expira_txt) < time.time():
        return False
    return hmac.compare_digest(firma, _firma(competencia, causa_id, int(expira_txt)))


def proteger_respuesta(respuesta, competencia: str, causa):
    """Agrega el token a toda URL de documento propia (`{public_base_url}/public/...`) dentro
    de `respuesta` (modelo Pydantic, mutado in situ), salvo que la causa sea publica."""
    if causa.visibilidad == VISIBILIDAD_PUBLICA:
        return respuesta
    prefijo = settings.public_base_url.rstrip("/") + "/public/"
    sufijo = "?t=" + generar_token_documento(competencia, causa.id)

    def _recorrer(valor):
        if isinstance(valor, str):
            return valor + sufijo if valor.startswith(prefijo) and "?t=" not in valor else valor
        if isinstance(valor, list):
            return [_recorrer(v) for v in valor]
        if isinstance(valor, dict):
            return {k: _recorrer(v) for k, v in valor.items()}
        if isinstance(valor, BaseModel):
            for nombre in type(valor).model_fields:
                setattr(valor, nombre, _recorrer(getattr(valor, nombre)))
        return valor

    _recorrer(respuesta)
    return respuesta
