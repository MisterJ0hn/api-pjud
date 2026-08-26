from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from api.auth.security import hash_secreto
from api.db.models.auth import ClienteApi, TokenAcceso, Usuario
from api.db.session_async import get_session
from api.errors.exceptions import NoAutorizadoError


@dataclass
class Principal:
    cliente: ClienteApi
    usuario: Usuario


async def resolver_cliente(session: AsyncSession, x_client_key: str | None) -> ClienteApi:
    if not x_client_key:
        raise NoAutorizadoError()
    cliente = (
        await session.execute(
            select(ClienteApi).where(
                ClienteApi.client_key_hash == hash_secreto(x_client_key),
                ClienteApi.activo.is_(True),
            )
        )
    ).scalar_one_or_none()
    if cliente is None:
        raise NoAutorizadoError()
    return cliente


async def _resolver_usuario_por_token(session: AsyncSession, authorization: str | None) -> Usuario:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise NoAutorizadoError()
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise NoAutorizadoError()

    ahora = datetime.now(timezone.utc)
    token_row = (
        await session.execute(
            select(TokenAcceso).where(
                TokenAcceso.token_hash == hash_secreto(token),
                TokenAcceso.revocado_en.is_(None),
                TokenAcceso.expira_en > ahora,
            )
        )
    ).scalar_one_or_none()
    if token_row is None:
        raise NoAutorizadoError()

    usuario = (
        await session.execute(select(Usuario).where(Usuario.id == token_row.usuario_id, Usuario.activo.is_(True)))
    ).scalar_one_or_none()
    if usuario is None:
        raise NoAutorizadoError()
    return usuario


async def obtener_principal(
    x_client_key: str | None = Header(default=None, alias="x-client-key"),
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    """Valida x-client-key + Bearer token, y exige ademas que el usuario del token
    pertenezca al mismo cliente resuelto por x-client-key (defensa en profundidad).
    Cualquier fallo de las 3 validaciones cae en el mismo 401 generico "No Autorizado",
    sin distinguir la causa exacta en la respuesta (si en logs, para debugging propio)."""
    cliente = await resolver_cliente(session, x_client_key)
    usuario = await _resolver_usuario_por_token(session, authorization)

    if usuario.cliente_id != cliente.id:
        raise NoAutorizadoError()

    return Principal(cliente=cliente, usuario=usuario)
