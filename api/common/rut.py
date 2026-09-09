"""Validacion / normalizacion de credenciales de PJUD (RUT + clave + metodo_login),
compartida por `sincronizar_civil` y `sincronizar_familia`.

- civil: las credenciales son OPCIONALES (si no vienen -> sync publica).
- familia: son OBLIGATORIAS (siempre privada).

`normalizar_credenciales` distingue los dos casos con `obligatorias`.
"""

import re

from api.errors.exceptions import CampoInvalidoError

_RUT_RE = re.compile(r"^(\d{7,8})(?:-([\dkK]))?$")


def digito_verificador(cuerpo: str) -> str:
    suma, factor = 0, 2
    for digito in reversed(cuerpo):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    return "0" if resto == 11 else "K" if resto == 10 else str(resto)


def normalizar_credenciales(
    rut: str | None, clave: str | None, metodo_login: int | None, *, obligatorias: bool
) -> tuple[str, str, int] | None:
    """Devuelve (rut_normalizado, clave, metodo_login) o None.

    None significa "sincronizacion publica" y solo puede pasar cuando `obligatorias` es
    False y los tres campos vienen vacios. Cualquier otro problema (campo faltante, RUT
    mal formado, DV incorrecto, metodo_login fuera de {1,2}) es un 400
    `Error en campo [...]`.

    El RUT se normaliza siempre a 'cuerpo-DV' (con o sin puntos, con o sin DV en la
    entrada); el DV se calcula si no vino y se valida si vino.
    """
    if not obligatorias and rut is None and clave is None and metodo_login is None:
        return None

    if not rut:
        raise CampoInvalidoError("rut")
    if not clave:
        raise CampoInvalidoError("clave")
    if metodo_login not in (1, 2):
        raise CampoInvalidoError("metodo_login")

    match = _RUT_RE.match(rut.strip().replace(".", "").replace(" ", "").upper())
    if match is None:
        raise CampoInvalidoError("rut")
    cuerpo, dv = match.group(1), match.group(2)
    esperado = digito_verificador(cuerpo)
    if dv is not None and dv != esperado:
        raise CampoInvalidoError("rut")

    return f"{cuerpo}-{esperado}", clave, metodo_login
