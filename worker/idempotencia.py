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


def ruta_documento(rol_fmt: str, clave_logica: str, cuaderno_numero: int | None, extension: str) -> str:
    if cuaderno_numero is not None:
        carpeta = os.path.join(settings.documentos_dir, rol_fmt, str(cuaderno_numero))
    else:
        carpeta = os.path.join(settings.documentos_dir, rol_fmt)
    os.makedirs(carpeta, exist_ok=True)
    return os.path.join(carpeta, f"{clave_logica}{extension}")


def extension_por_content_type(content_type: str) -> str:
    if "pdf" in content_type:
        return ".pdf"
    if "html" in content_type:
        return ".html"
    return ".bin"
