"""Entrega del callback opcional de `sincronizar_*`. Corre como tarea aparte dentro del
proceso worker, independiente del ciclo de sincronizacion (que tiene pacing entre jobs y
no debe retrasar los avisos). El estado vive en `sync_job` para retomar los reintentos si
el worker se reinicia."""

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select

from api.common.callback import host_es_publico, preparar_callback  # noqa: F401 (re-export)
from api.db.models.sync_job import SyncJob
from api.db.session_async import AsyncSessionLocal
from api.logging_config import configurar_logger

logger = configurar_logger("pjud.worker.callback", "worker.log")

POLL_INTERVAL_S = 5
MAX_INTENTOS_CALLBACK = 3  # 1 envio + 2 reintentos
INTERVALO_REINTENTO_S = 60  # envios en t=0, 1 min y 2 min
TIMEOUT_S = 10


def _payload(job_id: int, exito: bool, mensaje_error: str | None) -> dict:
    payload = {"job_id": job_id, "exito": exito}
    if not exito:
        payload["mensaje_error"] = mensaje_error
    return payload


async def _enviar(url: str, payload: dict) -> bool:
    """True solo si el cliente responde 2xx con `{"exito": true}`."""
    partes = urlsplit(url)
    if not await host_es_publico(partes.hostname or "", partes.port or 443):
        logger.warning("Callback a %s omitido: el host no resuelve a una IP publica", partes.hostname)
        return False
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False) as client:
            resp = await client.post(url, json=payload)
        return resp.is_success and resp.json().get("exito") is True
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.info("Callback a %s fallo: %s", partes.hostname, exc)
        return False


async def _procesar_siguiente() -> bool:
    """Envia el siguiente callback vencido. False si no habia ninguno."""
    ahora = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        job = (
            await session.execute(
                select(SyncJob)
                .where(SyncJob.callback_estado == "pendiente", SyncJob.callback_proximo_intento <= ahora)
                .order_by(SyncJob.callback_proximo_intento)
                .limit(1)
            )
        ).scalar_one_or_none()
        if job is None:
            return False
        job_id, url = job.id, job.callback_url
        payload = _payload(job_id, job.estado == "completo", job.callback_mensaje_error)

    entregado = await _enviar(url, payload)

    async with AsyncSessionLocal() as session:
        job = await session.get(SyncJob, job_id)
        job.callback_intentos += 1
        if entregado:
            job.callback_estado = "entregado"
            job.callback_proximo_intento = None
        elif job.callback_intentos >= MAX_INTENTOS_CALLBACK:
            job.callback_estado = "fallido"
            job.callback_proximo_intento = None
            logger.warning("Callback del job %s sin confirmar tras %d intentos", job_id, job.callback_intentos)
        else:
            job.callback_proximo_intento = datetime.now(timezone.utc) + timedelta(seconds=INTERVALO_REINTENTO_S)
        await session.commit()
    return True


async def run_callbacks() -> None:
    while True:
        try:
            if await _procesar_siguiente():
                continue
        except Exception:
            logger.exception("Error en el ciclo de callbacks")
        await asyncio.sleep(POLL_INTERVAL_S)
