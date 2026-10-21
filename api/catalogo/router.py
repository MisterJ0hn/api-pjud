from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import Principal, obtener_principal
from api.apelaciones.cortes import CORTES
from api.catalogo.repository import listar_cortes_con_tribunales
from api.catalogo.schemas import CatalogoCortesResponse, CatalogoTribunalesResponse, CorteApelacionesItem
from api.db.session_async import get_session
from api.errors.exceptions import CampoInvalidoError

router = APIRouter(tags=["catalogo"])

COMPETENCIAS_VALIDAS = ("civil", "laboral", "cobranza", "penal")


@router.get("/catalogo/tribunales", response_model=CatalogoTribunalesResponse)
async def catalogo_tribunales(
    competencia: str = Query(default="civil"),
    principal: Principal = Depends(obtener_principal),
    session: AsyncSession = Depends(get_session),
):
    if competencia not in COMPETENCIAS_VALIDAS:
        raise CampoInvalidoError("competencia")

    return await listar_cortes_con_tribunales(session, competencia)


@router.get("/catalogo/cortes", response_model=CatalogoCortesResponse)
async def catalogo_cortes(principal: Principal = Depends(obtener_principal)):
    """Cortes de Apelaciones (valores de `corte` de sincronizar_apelaciones). Lista fija."""
    return CatalogoCortesResponse(cortes=[CorteApelacionesItem(id=i, nombre=n) for i, n in CORTES.items()])
