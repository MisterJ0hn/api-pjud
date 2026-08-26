from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import Principal, obtener_principal
from api.catalogo.repository import listar_cortes_con_tribunales
from api.catalogo.schemas import CatalogoTribunalesResponse
from api.db.session_async import get_session
from api.errors.exceptions import CampoInvalidoError

router = APIRouter(tags=["catalogo"])

COMPETENCIAS_VALIDAS = ("civil", "laboral", "cobranza")


@router.get("/catalogo/tribunales", response_model=CatalogoTribunalesResponse)
async def catalogo_tribunales(
    competencia: str = Query(default="civil"),
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    if competencia not in COMPETENCIAS_VALIDAS:
        raise CampoInvalidoError("competencia")

    return await listar_cortes_con_tribunales(session, competencia)
