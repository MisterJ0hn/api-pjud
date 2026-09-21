import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.causas import Causa, Cuaderno
from api.db.models.cobranza import CausaCobranza, DocumentoCobranza
from api.db.models.documentos import Documento
from api.db.models.familia import CausaFamilia, DocumentoFamilia
from api.db.models.laboral import CausaLaboral, DocumentoLaboral
from api.db.session_async import get_session

router = APIRouter(prefix="/public", tags=["documentos"])

_MIME_POR_EXTENSION = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".wma": "audio/x-ms-wma",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
}

# Extensiones que puede traer la columna "Doc." de Laboral (Movimientos, Diligencias,
# etc.) y de Cobranza (Historia, Documentos Laboral): la mayoria son pdf, pero PJUD
# mezcla .doc/.docx en la misma columna -- confirmado en vivo en Laboral (2026-09-18) y
# en Cobranza (popup "Detalle Documentos Laboral", forms POST docLaboralCobranza.php)
# (ver `extension_por_content_type`).
_MIME_DOCUMENTOS_MIXTOS = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


async def _resolver_y_servir(
    session: AsyncSession, causa_id: str, nombre_con_ext: str, cuaderno_numero: int | None
) -> FileResponse:
    if not nombre_con_ext.lower().endswith(".pdf"):
        raise HTTPException(status_code=404, detail="No encontrado")
    nombre_archivo = nombre_con_ext[: -len(".pdf")]

    try:
        cid = uuid.UUID(causa_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="No encontrado")

    causa = (await session.execute(select(Causa).where(Causa.id == cid))).scalar_one_or_none()
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


async def _resolver_y_servir_imagen(
    session: AsyncSession, causa_id: str, cuaderno_numero: int, nombre_con_ext: str
) -> FileResponse:
    nombre, ext = os.path.splitext(nombre_con_ext)
    media_type = _MIME_POR_EXTENSION.get(ext.lower())
    if media_type is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    try:
        cid = uuid.UUID(causa_id)
        documento_id = uuid.UUID(nombre)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="No encontrado")

    cuaderno = (
        await session.execute(select(Cuaderno).where(Cuaderno.causa_id == cid, Cuaderno.numero == cuaderno_numero))
    ).scalar_one_or_none()
    if cuaderno is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    documento = (
        await session.execute(
            select(Documento).where(
                Documento.id == documento_id,
                Documento.causa_id == cid,
                Documento.cuaderno_id == cuaderno.id,
            )
        )
    ).scalar_one_or_none()
    if documento is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    return FileResponse(documento.ruta_archivo, media_type=media_type, filename=nombre_con_ext)


async def _resolver_y_servir_familia(session: AsyncSession, causa_id: str, nombre_con_ext: str) -> FileResponse:
    if not nombre_con_ext.lower().endswith(".pdf"):
        raise HTTPException(status_code=404, detail="No encontrado")
    nombre_archivo = nombre_con_ext[: -len(".pdf")]

    try:
        cid = uuid.UUID(causa_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="No encontrado")

    causa = (await session.execute(select(CausaFamilia).where(CausaFamilia.id == cid))).scalar_one_or_none()
    if causa is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    documento = (
        await session.execute(
            select(DocumentoFamilia).where(
                DocumentoFamilia.causa_familia_id == causa.id,
                DocumentoFamilia.nombre_archivo == nombre_archivo,
            )
        )
    ).scalar_one_or_none()
    if documento is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    return FileResponse(documento.ruta_archivo, media_type="application/pdf", filename=nombre_con_ext)


async def _resolver_y_servir_imagen_familia(session: AsyncSession, causa_id: str, nombre_con_ext: str) -> FileResponse:
    nombre, ext = os.path.splitext(nombre_con_ext)
    media_type = _MIME_POR_EXTENSION.get(ext.lower())
    if media_type is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    try:
        cid = uuid.UUID(causa_id)
        documento_id = uuid.UUID(nombre)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="No encontrado")

    documento = (
        await session.execute(
            select(DocumentoFamilia).where(
                DocumentoFamilia.id == documento_id,
                DocumentoFamilia.causa_familia_id == cid,
            )
        )
    ).scalar_one_or_none()
    if documento is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    return FileResponse(documento.ruta_archivo, media_type=media_type, filename=nombre_con_ext)


async def _resolver_y_servir_laboral(session: AsyncSession, causa_id: str, nombre_con_ext: str) -> FileResponse:
    # A diferencia de civil/familia (donde todo documento generico ES pdf), Laboral
    # mezcla .doc/.docx en la misma columna "Doc." -- confirmado en vivo 2026-09-18 --
    # asi que aca no se puede asumir `.pdf` fijo como en `_resolver_y_servir_familia`.
    nombre_archivo, ext = os.path.splitext(nombre_con_ext)
    media_type = _MIME_DOCUMENTOS_MIXTOS.get(ext.lower())
    if media_type is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    try:
        cid = uuid.UUID(causa_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="No encontrado")

    causa = (await session.execute(select(CausaLaboral).where(CausaLaboral.id == cid))).scalar_one_or_none()
    if causa is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    documento = (
        await session.execute(
            select(DocumentoLaboral).where(
                DocumentoLaboral.causa_laboral_id == causa.id,
                DocumentoLaboral.nombre_archivo == nombre_archivo,
            )
        )
    ).scalar_one_or_none()
    if documento is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    return FileResponse(documento.ruta_archivo, media_type=media_type, filename=nombre_con_ext)


async def _resolver_y_servir_imagen_laboral(session: AsyncSession, causa_id: str, nombre_con_ext: str) -> FileResponse:
    nombre, ext = os.path.splitext(nombre_con_ext)
    media_type = _MIME_POR_EXTENSION.get(ext.lower())
    if media_type is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    try:
        cid = uuid.UUID(causa_id)
        documento_id = uuid.UUID(nombre)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="No encontrado")

    documento = (
        await session.execute(
            select(DocumentoLaboral).where(
                DocumentoLaboral.id == documento_id,
                DocumentoLaboral.causa_laboral_id == cid,
            )
        )
    ).scalar_one_or_none()
    if documento is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    return FileResponse(documento.ruta_archivo, media_type=media_type, filename=nombre_con_ext)


async def _resolver_y_servir_cobranza(session: AsyncSession, causa_id: str, nombre_con_ext: str) -> FileResponse:
    # Igual que Laboral: la columna "Doc." de Historia y el popup "Documentos Laboral"
    # mezclan pdf/doc/docx -- no se puede asumir `.pdf` fijo.
    nombre_archivo, ext = os.path.splitext(nombre_con_ext)
    media_type = _MIME_DOCUMENTOS_MIXTOS.get(ext.lower())
    if media_type is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    try:
        cid = uuid.UUID(causa_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="No encontrado")

    causa = (await session.execute(select(CausaCobranza).where(CausaCobranza.id == cid))).scalar_one_or_none()
    if causa is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    documento = (
        await session.execute(
            select(DocumentoCobranza).where(
                DocumentoCobranza.causa_cobranza_id == causa.id,
                DocumentoCobranza.nombre_archivo == nombre_archivo,
            )
        )
    ).scalar_one_or_none()
    if documento is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    return FileResponse(documento.ruta_archivo, media_type=media_type, filename=nombre_con_ext)


async def _resolver_y_servir_imagen_cobranza(session: AsyncSession, causa_id: str, nombre_con_ext: str) -> FileResponse:
    nombre, ext = os.path.splitext(nombre_con_ext)
    media_type = _MIME_POR_EXTENSION.get(ext.lower())
    if media_type is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    try:
        cid = uuid.UUID(causa_id)
        documento_id = uuid.UUID(nombre)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="No encontrado")

    documento = (
        await session.execute(
            select(DocumentoCobranza).where(
                DocumentoCobranza.id == documento_id,
                DocumentoCobranza.causa_cobranza_id == cid,
            )
        )
    ).scalar_one_or_none()
    if documento is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    return FileResponse(documento.ruta_archivo, media_type=media_type, filename=nombre_con_ext)


async def _resolver_y_servir_audio_laboral(session: AsyncSession, causa_id: str, nombre_con_ext: str) -> FileResponse:
    nombre, ext = os.path.splitext(nombre_con_ext)
    media_type = _MIME_POR_EXTENSION.get(ext.lower())
    if media_type is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    try:
        cid = uuid.UUID(causa_id)
        documento_id = uuid.UUID(nombre)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="No encontrado")

    documento = (
        await session.execute(
            select(DocumentoLaboral).where(
                DocumentoLaboral.id == documento_id,
                DocumentoLaboral.causa_laboral_id == cid,
            )
        )
    ).scalar_one_or_none()
    if documento is None:
        raise HTTPException(status_code=404, detail="No encontrado")

    return FileResponse(documento.ruta_archivo, media_type=media_type, filename=nombre_con_ext)


# Declarada ANTES de `documento_familia` / `documento_laboral` / `documento_cobranza`
# (2 segmentos): estas tienen un segmento "img" de mas, asi que no colisionan por
# estructura de ruta, pero se dejan primero por legibilidad.
@router.get("/familia/{causa_id}/img/{nombre_con_ext}")
async def imagen_familia(causa_id: str, nombre_con_ext: str, session: AsyncSession = Depends(get_session)):
    return await _resolver_y_servir_imagen_familia(session, causa_id, nombre_con_ext)


@router.get("/laboral/{causa_id}/img/{nombre_con_ext}")
async def imagen_laboral(causa_id: str, nombre_con_ext: str, session: AsyncSession = Depends(get_session)):
    return await _resolver_y_servir_imagen_laboral(session, causa_id, nombre_con_ext)


@router.get("/laboral/{causa_id}/audio/{nombre_con_ext}")
async def audio_laboral(causa_id: str, nombre_con_ext: str, session: AsyncSession = Depends(get_session)):
    return await _resolver_y_servir_audio_laboral(session, causa_id, nombre_con_ext)


@router.get("/cobranza/{causa_id}/img/{nombre_con_ext}")
async def imagen_cobranza(causa_id: str, nombre_con_ext: str, session: AsyncSession = Depends(get_session)):
    return await _resolver_y_servir_imagen_cobranza(session, causa_id, nombre_con_ext)


# Declaradas ANTES de las rutas civiles de 2 segmentos para que `/public/familia/<uuid>/<name>`
# / `/public/laboral/<uuid>/<name>` / `/public/cobranza/<uuid>/<name>` no las agarre
# `documento_cuaderno` con causa_id="familia"/"laboral"/"cobranza".
@router.get("/familia/{causa_id}/{nombre_archivo}")
async def documento_familia(causa_id: str, nombre_archivo: str, session: AsyncSession = Depends(get_session)):
    return await _resolver_y_servir_familia(session, causa_id, nombre_archivo)


@router.get("/laboral/{causa_id}/{nombre_archivo}")
async def documento_laboral(causa_id: str, nombre_archivo: str, session: AsyncSession = Depends(get_session)):
    return await _resolver_y_servir_laboral(session, causa_id, nombre_archivo)


@router.get("/cobranza/{causa_id}/{nombre_archivo}")
async def documento_cobranza(causa_id: str, nombre_archivo: str, session: AsyncSession = Depends(get_session)):
    return await _resolver_y_servir_cobranza(session, causa_id, nombre_archivo)


@router.get("/{causa_id}/{nombre_archivo}")
async def documento_cabecera(causa_id: str, nombre_archivo: str, session: AsyncSession = Depends(get_session)):
    return await _resolver_y_servir(session, causa_id, nombre_archivo, None)


@router.get("/{causa_id}/{cuaderno_numero}/{nombre_archivo}")
async def documento_cuaderno(
    causa_id: str, cuaderno_numero: int, nombre_archivo: str, session: AsyncSession = Depends(get_session)
):
    return await _resolver_y_servir(session, causa_id, nombre_archivo, cuaderno_numero)


# 4 segmentos ("img" de mas): no colisiona con `documento_cuaderno` (3 segmentos).
@router.get("/{causa_id}/{cuaderno_numero}/img/{nombre_con_ext}")
async def imagen_cuaderno(
    causa_id: str, cuaderno_numero: int, nombre_con_ext: str, session: AsyncSession = Depends(get_session)
):
    return await _resolver_y_servir_imagen(session, causa_id, cuaderno_numero, nombre_con_ext)
