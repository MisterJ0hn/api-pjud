from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import resolver_cliente
from api.auth.schemas import LoginRequest, LoginResponse
from api.auth.security import expiracion_token, generar_token, hash_secreto, verificar_password
from api.db.models.auth import TokenAcceso, Usuario
from api.db.session_async import get_session
from api.errors.exceptions import NoAutorizadoError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    x_client_key: str | None = Header(default=None, alias="x-client-key"),
    session: AsyncSession = Depends(get_session),
):
    cliente = await resolver_cliente(session, x_client_key)

    usuario = (
        await session.execute(
            select(Usuario).where(
                Usuario.email == body.email,
                Usuario.cliente_id == cliente.id,
                Usuario.activo.is_(True),
            )
        )
    ).scalar_one_or_none()

    if usuario is None or not verificar_password(body.password, usuario.password_hash):
        raise NoAutorizadoError()

    token = generar_token()
    expira_en = expiracion_token()
    session.add(
        TokenAcceso(
            usuario_id=usuario.id,
            token_hash=hash_secreto(token),
            expira_en=expira_en,
        )
    )
    await session.commit()

    return LoginResponse(token=token, expira_en=expira_en.isoformat())
