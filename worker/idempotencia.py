import hashlib
import json
import os
import re

from api.config import settings


def slug(texto: str | None, maximo: int = 60) -> str:
    texto = re.sub(r"[^\w\-]+", "_", (texto or "").strip().lower(), flags=re.UNICODE).strip("_")
    return (texto or "doc")[:maximo]


def hash_fila(valores: dict) -> str:
    """SHA-256 estable sobre el contenido completo de una fila extraida -- es lo que
    permite detectar 'sin cambios' entre dos sincronizaciones sin comparar campo por
    campo. `sort_keys=True` garantiza el mismo hash sin importar el orden de columnas."""
    payload = json.dumps(valores, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dir_causa(causa_id) -> str:
    """Carpeta raiz de los documentos de una causa. Se usa el id (UUID) y no el rol
    formateado porque la misma RIT (p. ej. C-5656-2021) puede existir en dos tribunales
    distintos -> mismo rol_fmt -> los archivos se pisaban entre si."""
    return os.path.join(settings.documentos_dir, str(causa_id))


def ruta_documento(causa_id, clave_logica: str, cuaderno_numero: int | None, extension: str) -> str:
    carpeta = dir_causa(causa_id)
    if cuaderno_numero is not None:
        carpeta = os.path.join(carpeta, str(cuaderno_numero))
    os.makedirs(carpeta, exist_ok=True)
    return os.path.join(carpeta, f"{clave_logica}{extension}")


def extension_por_content_type(content_type: str) -> str:
    if "pdf" in content_type:
        return ".pdf"
    # Word: PJUD mezcla .doc/.docx con .pdf en la misma columna "Doc." (confirmado en
    # vivo en Laboral, 2026-09-18) -- sin esto, cualquier Word caia al `.bin` generico.
    if "wordprocessingml" in content_type:
        return ".docx"
    if "msword" in content_type:
        return ".doc"
    if "html" in content_type:
        return ".html"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "png" in content_type:
        return ".png"
    if "gif" in content_type:
        return ".gif"
    return ".bin"


# --- Color del icono "Descargar Documento" ------------------------------------
# El scraper deja el color de cada link en `fila["colores"][columna]` (paralelo a
# `fila["enlaces"][columna]`) y el de cada anexo de popup en `anexos_popup[i]["color"]`.
# El color NO entra al hash de la fila (`hash_fila(valores)`), asi que una fila sin
# cambios de texto no se reprocesa: los workers lo refrescan aparte con estos helpers.


def color_en(lista, i: int) -> str | None:
    """Color del i-esimo link (0-based); None si no hay o viene vacio."""
    return (lista[i] or None) if lista and i < len(lista) else None


def colores_columna(fila: dict, *columnas: str) -> list[str | None]:
    c = fila.get("colores") or {}
    for col in columnas:
        if c.get(col):
            return c[col]
    return []


def colores_anexos_fila(fila: dict) -> list[str | None]:
    """Colores de los anexos en el mismo orden con que se persisten: los del popup si la
    fila los trae, si no los de la columna "Anexo(s)" con enlaces directos."""
    popup = fila.get("anexos_popup") or []
    if popup:
        return [a.get("color") for a in popup]
    return colores_columna(fila, "Anexo", "Anexos")


async def refrescar_colores_docs_anexos(session, movimiento_id, fila: dict, doc_model, anexo_model) -> None:
    """Actualiza `color` en las filas ya guardadas de docs/anexos de un movimiento sin
    tocar nada mas (ni re-descargar). Cubre (a) el backfill de filas creadas antes de que
    existiera la columna y (b) cambios de color en PJUD con el texto de la fila igual.
    Si el scraper no trajo links de un tipo (lista vacia) no se toca ese tipo."""
    from sqlalchemy import select

    for modelo, colores in (
        (doc_model, colores_columna(fila, "Doc.")),
        (anexo_model, colores_anexos_fila(fila)),
    ):
        if not colores:
            continue
        rows = (await session.execute(select(modelo).where(modelo.movimiento_id == movimiento_id))).scalars().all()
        for r in rows:
            nuevo = color_en(colores, r.orden - 1)
            if r.color != nuevo:
                r.color = nuevo
