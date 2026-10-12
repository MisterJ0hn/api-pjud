"""Control de acceso de `consultar_*` y `consultar_movimientos_*` a las causas almacenadas.

Reglas:
1. Causa marcada `publica` (obtenida de la Consulta Unificada) -> se entrega sin mas.
2. Cualquier otra (`privada` o sin marcar) solo se entrega a los usuarios (RUT) registrados en
   `usuario_<competencia>_permitido`. Si el RUT no viene o no esta registrado -> 403 "causa
   privada". Causa inexistente -> 404.

Quien escribe esa tabla es el worker, al sincronizar con credenciales (ver `worker/main.py`):
- sync exitoso y la causa solo aparece en "Mis Causas" -> `permitir_usuario`.
- sync con credenciales y la causa ya no aparece en "Mis Causas" -> `revocar_usuario`.
"""

import hashlib
import hmac
import time

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.common.rut import normalizar_rut
from api.config import settings
from api.db.models.acceso import (
    UsuarioCivilPermitido,
    UsuarioCobranzaPermitido,
    UsuarioFamiliaPermitido,
    UsuarioLaboralPermitido,
    UsuarioPenalPermitido,
)
from api.errors.exceptions import CausaPrivadaError, NoEncontradoError

VISIBILIDAD_PUBLICA = "publica"
VISIBILIDAD_PRIVADA = "privada"

MODELO_USUARIO_PERMITIDO = {
    "civil": UsuarioCivilPermitido,
    "familia": UsuarioFamiliaPermitido,
    "laboral": UsuarioLaboralPermitido,
    "cobranza": UsuarioCobranzaPermitido,
    "penal": UsuarioPenalPermitido,
}


async def permitir_usuario(session: AsyncSession, competencia: str, causa_id, rut: str) -> None:
    """Registra (idempotente) que `rut` ve la causa en Mis Causas. No hace commit."""
    modelo = MODELO_USUARIO_PERMITIDO[competencia]
    stmt = pg_insert(modelo).values(causa_id=causa_id, rut=rut).on_conflict_do_nothing()
    await session.execute(stmt)


async def revocar_usuario(session: AsyncSession, competencia: str, causa_id, rut: str) -> None:
    """Quita a `rut` de la causa (ya no aparece en su Mis Causas). No hace commit."""
    modelo = MODELO_USUARIO_PERMITIDO[competencia]
    await session.execute(delete(modelo).where(modelo.causa_id == causa_id, modelo.rut == rut))


async def _usuario_permitido(session: AsyncSession, competencia: str, causa_id, rut: str) -> bool:
    modelo = MODELO_USUARIO_PERMITIDO[competencia]
    fila = (
        await session.execute(select(modelo.id).where(modelo.causa_id == causa_id, modelo.rut == rut))
    ).first()
    return fila is not None


async def exigir_acceso(session: AsyncSession, competencia: str, causa, rut: str | None) -> None:
    """Lanza `NoEncontradoError` (404) si la causa no existe y `CausaPrivadaError` (403) si es
    privada y `rut` no esta registrado como usuario permitido. Un RUT mal formado es 400."""
    rut_normalizado = normalizar_rut(rut) if rut else None

    if causa is None:
        raise NoEncontradoError()
    if causa.visibilidad == VISIBILIDAD_PUBLICA:
        return
    if rut_normalizado is None or not await _usuario_permitido(session, competencia, causa.id, rut_normalizado):
        raise CausaPrivadaError()


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
