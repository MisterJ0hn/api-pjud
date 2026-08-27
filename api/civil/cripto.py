"""Cifrado simetrico de las credenciales de PJUD (RUT + clave) que viajan en el request
de sincronizar_civil y quedan en reposo en la fila `sync_job` hasta que el worker las
usa. Se usa Fernet (AES-128-CBC + HMAC) con una clave unica en `PJUD_CRED_SECRET_KEY`.

El worker borra `rut_cifrado` / `clave_cifrada` de la fila apenas el job llega a un
estado terminal (ver `worker/main.py`), asi que el texto cifrado vive en la BD solo
mientras el trabajo esta pendiente o en progreso.
"""

from functools import lru_cache

from cryptography.fernet import Fernet

from api.config import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    clave = settings.pjud_cred_secret_key
    if not clave:
        raise RuntimeError(
            "PJUD_CRED_SECRET_KEY no configurada: es obligatoria para sincronizar causas privadas"
        )
    return Fernet(clave.encode("utf-8"))


def cifrar(texto: str) -> str:
    return _fernet().encrypt(texto.encode("utf-8")).decode("ascii")


def descifrar(token: str) -> str:
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
