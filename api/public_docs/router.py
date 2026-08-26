from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.causas import Causa, Cuaderno
from api.db.models.documentos import Documento
from api.db.session_async import get_session

router = APIRouter(prefix="/public", tags=["documentos"])


async def _resolver_y_servir(
    session: AsyncSession, rol_fmt: str, nombre_con_ext: str, cuaderno_numero: int | None
) -> FileResponse:
    if not nombre_con_ext.lower().endswith(".pdf"):
        raise HTTPException(status_code=404, detail="No encontrado")
    nombre_archivo = nombre_con_ext[: -len(".pdf")]

    causa = (await session.execute(select(Causa).where(Causa.rol_formateado == rol_fmt))).scalar_one_or_none()
    if causa is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    stmt = select(Documento).where(Documento.causa_id == causa.id, Documento.nombre_archivo == nombre_archivo)
    if cuaderno_numero is None:
        stmt = stmt.where(Documento.cuaderno_id.is_(None))
    else:
        cuaderno = (
            await session.execute(
                select(Cuaderno).where(Cuaderno.causa_id == causa.id, Cuaderno.numero == cuaderno_numero)
            )
        ).scalar_one_or_none()
        if cuaderno is None:
            raise HTTPException(status_code=404, detail="No encontrado")
        stmt = stmt.where(Documento.cuaderno_id == cuaderno.id)

    documento = (await session.execute(stmt)).scalar_one_or_none()
    if documento is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    return FileResponse(documento.ruta_archivo, media_type="application/pdf", filename=nombre_con_ext)


@router.get("/{rol_fmt}/{nombre_archivo}")
async def documento_cabecera(rol_fmt: str, nombre_archivo: str, session: AsyncSession = Depends(get_session)):
    return await _resolver_y_servir(session, rol_fmt, nombre_archivo, None)


@router.get("/{rol_fmt}/{cuaderno_numero}/{nombre_archivo}")
async def documento_cuaderno(
    rol_fmt: str, cuaderno_numero: int, nombre_archivo: str, session: AsyncSession = Depends(get_session)
):
    return await _resolver_y_servir(session, rol_fmt, nombre_archivo, cuaderno_numero)
