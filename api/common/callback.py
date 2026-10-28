"""Callback opcional de los `sincronizar_*`: validacion de la URL (solo https hacia hosts
publicos, para no usar el worker como proxy hacia la red interna) y mixin de request."""

import asyncio
import ipaddress
import socket
from datetime import datetime, timezone
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from api.config import settings

MAX_LARGO_URL = 2000


def _ip_no_publica(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


def validar_url_callback(valor: str) -> str:
    """Chequeo sintactico (sin DNS): https, host presente, no localhost ni IP privada. El
    chequeo con resolucion DNS se repite al enviar (`host_es_publico`)."""
    partes = urlsplit(valor.strip())
    if partes.scheme != "https":
        raise ValueError("callback_url debe usar https")
    host = partes.hostname
    if not host or partes.username or partes.password:
        raise ValueError("callback_url invalida")
    if settings.callback_permitir_redes_privadas:
        return valor.strip()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("callback_url no puede apuntar a localhost")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return valor.strip()
    if _ip_no_publica(ip):
        raise ValueError("callback_url no puede apuntar a una IP privada")
    return valor.strip()


async def host_es_publico(host: str, puerto: int) -> bool:
    """True si TODAS las IPs a las que resuelve `host` son publicas."""
    if settings.callback_permitir_redes_privadas:
        return True
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, puerto, type=socket.SOCK_STREAM)
    except OSError:
        return False
    return bool(infos) and not any(_ip_no_publica(ipaddress.ip_address(i[4][0])) for i in infos)


class CallbackMixin(BaseModel):
    """`callback_url` opcional: al terminar la sincronizacion se le hace POST con el
    resultado (ver worker/callback.py)."""

    callback_url: str | None = Field(default=None, max_length=MAX_LARGO_URL)

    @field_validator("callback_url")
    @classmethod
    def _validar_callback_url(cls, valor):
        if valor is None or not valor.strip():
            return None
        return validar_url_callback(valor)


def preparar_callback(job, mensaje_error: str | None = None) -> None:
    """Deja el aviso del job en cola. Llamar cuando el job llega a un estado terminal
    (no en el camino de reintento de la sincronizacion). No-op si no hay `callback_url`."""
    if not job.callback_url:
        return
    job.callback_estado = "pendiente"
    job.callback_intentos = 0
    job.callback_proximo_intento = datetime.now(timezone.utc)
    job.callback_mensaje_error = mensaje_error


def marcar_completo_omitido(job) -> None:
    """Job de una sincronizacion omitida (la causa esta al dia): nace terminado, sin
    credenciales, y solo existe para entregar el callback con exito=true."""
    job.estado = "completo"
    job.finalizado_en = datetime.now(timezone.utc)
    job.rut_cifrado = job.clave_cifrada = job.metodo_login = None
    preparar_callback(job)
