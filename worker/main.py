"""Proceso worker standalone: unico dueno de la sesion Playwright (una causa a la vez,
nunca en paralelo -- ver plan de diseno). Escucha `sync_job` en Postgres por polling
(mas simple y suficientemente rapido para el volumen esperado; LISTEN/NOTIFY nativo de
Postgres es un near-term follow-up si hiciera falta bajar la latencia de recogida).

Uso: python -m worker.main
"""

import asyncio
import functools
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from api.civil.cripto import descifrar
from api.config import settings
from api.db.models.causas import Causa
from api.db.models.cobranza import CausaCobranza
from api.db.models.familia import CausaFamilia
from api.db.models.laboral import CausaLaboral
from api.db.models.penal import CausaPenal
from api.db.models.sync_job import SyncJob
from api.db.session_async import AsyncSessionLocal
from api.logging_config import configurar_logger
from scraper.pjud_client_async import (
    CausaNoEncontrada,
    LoginPrivadoError,
    PjudSessionAsync,
    PjudSessionCobranzaAsync,
    PjudSessionCobranzaPrivada,
    PjudSessionFamiliaPrivada,
    PjudSessionLaboralAsync,
    PjudSessionLaboralPrivada,
    PjudSessionPenalAsync,
    PjudSessionPenalPrivada,
    PjudSessionPrivada,
)
from worker.sync_civil import sincronizar_causa
from worker.sync_cobranza import sincronizar_causa_cobranza
from worker.sync_familia import sincronizar_causa_familia
from worker.sync_laboral import sincronizar_causa_laboral
from worker.sync_penal import sincronizar_causa_penal

logger = configurar_logger("pjud.worker", "worker.log")

POLL_INTERVAL_S = 5
PACING_ENTRE_JOBS_S = 7
MAX_INTENTOS = 2

# "civil" | "familia" | "laboral" | "cobranza" -- que causa apunta el job (ver
# `SyncJob`, XOR de las 4 columnas causa_id/causa_familia_id/causa_laboral_id/
# causa_cobranza_id).
COMPETENCIA_MODELO = {
    "civil": Causa,
    "familia": CausaFamilia,
    "laboral": CausaLaboral,
    "cobranza": CausaCobranza,
    "penal": CausaPenal,
}


def _competencia_job(job: SyncJob) -> str:
    if job.causa_familia_id is not None:
        return "familia"
    if job.causa_laboral_id is not None:
        return "laboral"
    if job.causa_cobranza_id is not None:
        return "cobranza"
    if job.causa_penal_id is not None:
        return "penal"
    return "civil"


def _causa_id_job(job: SyncJob, competencia: str):
    if competencia == "familia":
        return job.causa_familia_id
    if competencia == "laboral":
        return job.causa_laboral_id
    if competencia == "cobranza":
        return job.causa_cobranza_id
    if competencia == "penal":
        return job.causa_penal_id
    return job.causa_id


async def _reportar_progreso(causa_id, competencia: str, texto: str) -> None:
    """Escribe el paso actual de la sincronizacion en `<causas>.sync_detalle`, en una
    sesion corta e independiente de la transaccion del job (solo toca esa columna).
    Se expone en `consultar_civil` / `consultar_familia` / `consultar_laboral` como
    `detalle_estado`."""
    modelo = COMPETENCIA_MODELO[competencia]
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(update(modelo).where(modelo.id == causa_id).values(sync_detalle=texto))
            await session.commit()
    except Exception:
        logger.exception("No se pudo registrar el progreso '%s'", texto)


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
            competencia = _competencia_job(job)
            causa = await session.get(COMPETENCIA_MODELO[competencia], _causa_id_job(job, competencia))
            if causa is not None and causa.estado_sync == "Sincronizando":
                causa.estado_sync = "Error"
                causa.sync_detalle = None
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
        competencia = _competencia_job(job)
        modelo = COMPETENCIA_MODELO[competencia]
        causa_id = _causa_id_job(job, competencia)
        causa = await session.get(modelo, causa_id)
        etiqueta = causa.rol_formateado if competencia == "civil" else causa.rit

        privada = job.rut_cifrado is not None
        sesion_privada: PjudSessionPrivada | None = None
        progreso = functools.partial(_reportar_progreso, causa_id, competencia)

        try:
            if competencia == "familia":
                # Familia es siempre privada (el endpoint exige credenciales).
                rut = descifrar(job.rut_cifrado)
                clave = descifrar(job.clave_cifrada)
                sesion_privada = PjudSessionFamiliaPrivada(
                    rut, clave, job.metodo_login or PjudSessionFamiliaPrivada.METODO_CLAVE_PJUD,
                    headless=settings.playwright_headless,
                )
                await progreso("Iniciando sesion en la Oficina Judicial Virtual")
                await sesion_privada.iniciar()
                await sincronizar_causa_familia(session, sesion_privada, causa, progreso=progreso)
            elif competencia == "laboral" and privada:
                rut = descifrar(job.rut_cifrado)
                clave = descifrar(job.clave_cifrada)
                sesion_privada = PjudSessionLaboralPrivada(
                    rut, clave, job.metodo_login or PjudSessionLaboralPrivada.METODO_CLAVE_PJUD,
                    headless=settings.playwright_headless,
                )
                await progreso("Iniciando sesion en la Oficina Judicial Virtual")
                await sesion_privada.iniciar()
                await sincronizar_causa_laboral(session, sesion_privada, causa, privada=True, progreso=progreso)
            elif competencia == "laboral":
                # A diferencia de civil (que reusa el `sesion_pjud` compartido y de
                # larga duracion de `run()`), la sync publica de laboral abre su propia
                # sesion por job: `sesion_pjud` es un `PjudSessionAsync` de clase fija
                # (ids de popup de civil) y los ids de Laboral son atributos de clase
                # de `PjudSessionLaboralAsync`, asi que no se puede reusar la instancia
                # sin cambiarle la clase en caliente. El costo (relanzar el navegador
                # por job) es el mismo que ya paga toda sync privada.
                sesion_laboral_publica = PjudSessionLaboralAsync(headless=settings.playwright_headless)
                await sesion_laboral_publica.iniciar()
                try:
                    await sincronizar_causa_laboral(session, sesion_laboral_publica, causa, progreso=progreso)
                finally:
                    await sesion_laboral_publica.cerrar()
            elif competencia == "cobranza" and privada:
                # NO CONFIRMADO en vivo (ver docstring de `PjudSessionCobranzaPrivada`):
                # ids de "Mis Causas" -> Cobranza extrapolados por analogia, sin ejemplo
                # real disponible.
                rut = descifrar(job.rut_cifrado)
                clave = descifrar(job.clave_cifrada)
                sesion_privada = PjudSessionCobranzaPrivada(
                    rut, clave, job.metodo_login or PjudSessionCobranzaPrivada.METODO_CLAVE_PJUD,
                    headless=settings.playwright_headless,
                )
                await progreso("Iniciando sesion en la Oficina Judicial Virtual")
                await sesion_privada.iniciar()
                await sincronizar_causa_cobranza(session, sesion_privada, causa, privada=True, progreso=progreso)
            elif competencia == "cobranza":
                # Misma razon que laboral publico: los ids de popup son atributos de
                # clase de `PjudSessionCobranzaAsync`, no se puede reusar `sesion_pjud`.
                sesion_cobranza_publica = PjudSessionCobranzaAsync(headless=settings.playwright_headless)
                await sesion_cobranza_publica.iniciar()
                try:
                    await sincronizar_causa_cobranza(session, sesion_cobranza_publica, causa, progreso=progreso)
                finally:
                    await sesion_cobranza_publica.cerrar()
            elif competencia == "penal" and privada:
                # NO CONFIRMADO en vivo (ver docstring de `PjudSessionPenalPrivada`).
                rut = descifrar(job.rut_cifrado)
                clave = descifrar(job.clave_cifrada)
                sesion_privada = PjudSessionPenalPrivada(
                    rut, clave, job.metodo_login or PjudSessionPenalPrivada.METODO_CLAVE_PJUD,
                    headless=settings.playwright_headless,
                )
                await progreso("Iniciando sesion en la Oficina Judicial Virtual")
                await sesion_privada.iniciar()
                await sincronizar_causa_penal(session, sesion_privada, causa, privada=True, progreso=progreso)
            elif competencia == "penal":
                # Misma razon que laboral/cobranza publicos: los ids de popup son
                # atributos de clase de `PjudSessionPenalAsync`.
                sesion_penal_publica = PjudSessionPenalAsync(headless=settings.playwright_headless)
                await sesion_penal_publica.iniciar()
                try:
                    await sincronizar_causa_penal(session, sesion_penal_publica, causa, progreso=progreso)
                finally:
                    await sesion_penal_publica.cerrar()
            elif privada:
                rut = descifrar(job.rut_cifrado)
                clave = descifrar(job.clave_cifrada)
                sesion_privada = PjudSessionPrivada(
                    rut, clave, job.metodo_login or PjudSessionPrivada.METODO_CLAVE_PJUD,
                    headless=settings.playwright_headless,
                )
                await progreso("Iniciando sesion en la Oficina Judicial Virtual")
                await sesion_privada.iniciar()
                await sincronizar_causa(session, sesion_privada, causa, privada=True, progreso=progreso)
            else:
                await sincronizar_causa(session, sesion_pjud, causa, progreso=progreso)

            causa.estado_sync = "Completo"
            causa.fecha_ultima_sincronizacion = datetime.now(timezone.utc)
            causa.ultimo_error = None
            # UPDATE explicito: `_reportar_progreso` escribio sync_detalle desde otra
            # sesion, asi que el ORM de esta no detecta el cambio a None.
            await session.execute(update(modelo).where(modelo.id == causa_id).values(sync_detalle=None))
            job.estado = "completo"
            job.finalizado_en = datetime.now(timezone.utc)
            _limpiar_credenciales(job)
            await session.commit()
            logger.info("Job %s (%s) completado", job.id, etiqueta)
        except (CausaNoEncontrada, LoginPrivadoError) as exc:
            await session.rollback()
            job = await session.get(SyncJob, job_id)
            causa = await session.get(modelo, causa_id)
            causa.estado_sync = "Error"
            causa.ultimo_error = str(exc)
            # UPDATE explicito: `_reportar_progreso` pudo escribir sync_detalle desde otra
            # sesion durante el intento; una asignacion ORM normal no lo detectaria si el
            # valor en memoria de `causa` ya era None (ver comentario en el camino exitoso).
            await session.execute(update(modelo).where(modelo.id == causa_id).values(sync_detalle=None))
            job.estado = "error"
            job.error_mensaje = str(exc)
            job.finalizado_en = datetime.now(timezone.utc)
            _limpiar_credenciales(job)
            await session.commit()
            logger.warning("Job %s: %s (%s)", job.id, type(exc).__name__, exc)
        except Exception as exc:
            await session.rollback()
            # `job.id` quedo expirado tras el flush fallido: leerlo aca dispararia un
            # lazy-load sincrono sobre la conexion rota (MissingGreenlet) y tumbaria
            # el worker entero. Usar el int que ya tenemos.
            logger.exception("Job %s fallo", job_id)
            job = await session.get(SyncJob, job_id)
            causa = await session.get(modelo, causa_id)
            if job.intentos < MAX_INTENTOS:
                job.estado = "pendiente"
                job.error_mensaje = str(exc)
            else:
                causa.estado_sync = "Error"
                causa.ultimo_error = str(exc)
                await session.execute(update(modelo).where(modelo.id == causa_id).values(sync_detalle=None))
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
