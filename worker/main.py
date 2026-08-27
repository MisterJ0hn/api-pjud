"""Proceso worker standalone: unico dueno de la sesion Playwright (una causa a la vez,
nunca en paralelo -- ver plan de diseno). Escucha `sync_job` en Postgres por polling
(mas simple y suficientemente rapido para el volumen esperado; LISTEN/NOTIFY nativo de
Postgres es un near-term follow-up si hiciera falta bajar la latencia de recogida).

Uso: python -m worker.main
"""

import asyncio
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from api.civil.cripto import descifrar
from api.config import settings
from api.db.models.causas import Causa
from api.db.models.sync_job import SyncJob
from api.db.session_async import AsyncSessionLocal
from api.logging_config import configurar_logger
from scraper.pjud_client_async import (
    CausaNoEncontrada,
    LoginPrivadoError,
    PjudSessionAsync,
    PjudSessionPrivada,
)
from worker.sync_civil import sincronizar_causa

logger = configurar_logger("pjud.worker", "worker.log")

POLL_INTERVAL_S = 5
PACING_ENTRE_JOBS_S = 7
MAX_INTENTOS = 2


async def _barrer_jobs_huerfanos() -> None:
    """Al arrancar, libera jobs que quedaron 'en_progreso' porque el worker murio a
    medio proceso -- sin esto, la causa quedaria bloqueada (409 permanente) hasta que
    expirara sola el lock por tiempo."""
    async with AsyncSessionLocal() as session:
        umbral = datetime.now(timezone.utc) - timedelta(minutes=settings.sync_lock_timeout_minutes)
        huerfanos = (
            await session.execute(select(SyncJob).where(SyncJob.estado == "en_progreso", SyncJob.iniciado_en < umbral))
        ).scalars().all()
        for job in huerfanos:
            job.estado = "error"
            job.error_mensaje = "Job huerfano: worker reiniciado a medio proceso"
            job.finalizado_en = datetime.now(timezone.utc)
            _limpiar_credenciales(job)
            causa = await session.get(Causa, job.causa_id)
            if causa is not None and causa.estado_sync == "Sincronizando":
                causa.estado_sync = "Error"
        await session.commit()
        if huerfanos:
            logger.warning("Liberados %d jobs huerfanos", len(huerfanos))


async def _tomar_siguiente_job() -> int | None:
    async with AsyncSessionLocal() as session:
        job = (
            await session.execute(
                select(SyncJob)
                .where(SyncJob.estado == "pendiente")
                .order_by(SyncJob.encolado_en)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if job is None:
            return None
        job.estado = "en_progreso"
        job.iniciado_en = datetime.now(timezone.utc)
        job.intentos += 1
        await session.commit()
        return job.id


def _limpiar_credenciales(job: SyncJob) -> None:
    """Borra las credenciales de PJUD de la fila apenas el job llega a un estado terminal.
    En el camino de reintento (job vuelve a 'pendiente') se conservan."""
    job.rut_cifrado = None
    job.clave_cifrada = None
    job.metodo_login = None


async def _procesar_job(sesion_pjud: PjudSessionAsync, job_id: int) -> None:
    async with AsyncSessionLocal() as session:
        job = await session.get(SyncJob, job_id)
        causa = await session.get(Causa, job.causa_id)

        privada = job.rut_cifrado is not None
        sesion_privada: PjudSessionPrivada | None = None

        try:
            if privada:
                rut = descifrar(job.rut_cifrado)
                clave = descifrar(job.clave_cifrada)
                sesion_privada = PjudSessionPrivada(
                    rut, clave, job.metodo_login or PjudSessionPrivada.METODO_CLAVE_PJUD,
                    headless=settings.playwright_headless,
                )
                await sesion_privada.iniciar()
                await sincronizar_causa(session, sesion_privada, causa, privada=True)
            else:
                await sincronizar_causa(session, sesion_pjud, causa)

            causa.estado_sync = "Completo"
            causa.fecha_ultima_sincronizacion = datetime.now(timezone.utc)
            causa.ultimo_error = None
            job.estado = "completo"
            job.finalizado_en = datetime.now(timezone.utc)
            _limpiar_credenciales(job)
            await session.commit()
            logger.info("Job %s (%s) completado", job.id, causa.rol_formateado)
        except (CausaNoEncontrada, LoginPrivadoError) as exc:
            await session.rollback()
            job = await session.get(SyncJob, job_id)
            causa = await session.get(Causa, job.causa_id)
            causa.estado_sync = "Error"
            causa.ultimo_error = str(exc)
            job.estado = "error"
            job.error_mensaje = str(exc)
            job.finalizado_en = datetime.now(timezone.utc)
            _limpiar_credenciales(job)
            await session.commit()
            logger.warning("Job %s: %s (%s)", job.id, type(exc).__name__, exc)
        except Exception as exc:
            await session.rollback()
            logger.exception("Job %s fallo", job.id)
            job = await session.get(SyncJob, job_id)
            causa = await session.get(Causa, job.causa_id)
            if job.intentos < MAX_INTENTOS:
                job.estado = "pendiente"
                job.error_mensaje = str(exc)
            else:
                causa.estado_sync = "Error"
                causa.ultimo_error = str(exc)
                job.estado = "error"
                job.error_mensaje = str(exc)
                job.finalizado_en = datetime.now(timezone.utc)
                _limpiar_credenciales(job)
            await session.commit()
        finally:
            if sesion_privada is not None:
                try:
                    await sesion_privada.cerrar()
                except Exception:
                    logger.exception("Error al cerrar la sesion privada del job %s", job_id)


async def run() -> None:
    await _barrer_jobs_huerfanos()

    sesion_pjud = PjudSessionAsync(headless=settings.playwright_headless)
    await sesion_pjud.iniciar()
    logger.info("Worker de sincronizacion iniciado (headless=%s)", settings.playwright_headless)

    try:
        while True:
            job_id = await _tomar_siguiente_job()
            if job_id is None:
                await asyncio.sleep(POLL_INTERVAL_S)
                continue

            await _procesar_job(sesion_pjud, job_id)
            await asyncio.sleep(PACING_ENTRE_JOBS_S + random.uniform(0, 2))
    finally:
        await sesion_pjud.cerrar()


if __name__ == "__main__":
    asyncio.run(run())
