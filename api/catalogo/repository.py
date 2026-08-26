from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.catalogo.schemas import CatalogoTribunalesResponse, CorteItem, TribunalItem
from api.db.models.tribunales import TribunalCatalogo


async def listar_cortes_con_tribunales(session: AsyncSession, competencia: str) -> CatalogoTribunalesResponse:
    filas = (
        await session.execute(
            select(TribunalCatalogo)
            .where(TribunalCatalogo.competencia == competencia)
            .order_by(TribunalCatalogo.corte_nombre, TribunalCatalogo.tribunal_nombre)
        )
    ).scalars().all()

    cortes: dict[int, CorteItem] = {}
    for fila in filas:
        corte = cortes.get(fila.corte_id)
        if corte is None:
            corte = CorteItem(id=fila.corte_id, nombre=fila.corte_nombre, tribunales=[])
            cortes[fila.corte_id] = corte
        corte.tribunales.append(TribunalItem(id=fila.tribunal_id, nombre=fila.tribunal_nombre))

    return CatalogoTribunalesResponse(cortes=list(cortes.values()))
