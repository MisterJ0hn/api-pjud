from api.config import settings


def rit_formateado(tipo: str, rol: int, anio: int) -> str:
    return f"{tipo}-{rol}-{anio}"


def url_publica_documento_laboral(causa_laboral_id, nombre_archivo: str, extension: str = ".pdf") -> str:
    # Prefijo `/public/laboral/<causa_laboral_id>/...` para no colisionar con las rutas
    # civiles/familia del router publico. Laboral es cuaderno unico, sin segmento de
    # cuaderno. `extension` viene del archivo real en disco (la mayoria son pdf, pero
    # la columna "Doc." de Movimientos/Diligencias mezcla .doc/.docx -- confirmado en
    # vivo 2026-09-18); default ".pdf" solo por compatibilidad con quien no la pase.
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/laboral/{causa_laboral_id}/{nombre_archivo}{extension}"


def url_publica_imagen_laboral(causa_laboral_id, documento_id, extension: str) -> str:
    # Imagenes del popup Georref.: sin nombre natural estable, se sirven por GUID (el
    # id del Documento) en vez de por `nombre_archivo` como el resto de los docs.
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/laboral/{causa_laboral_id}/img/{documento_id}{extension}"


def url_publica_audio_laboral(causa_laboral_id, documento_id, extension: str) -> str:
    # Audios de audiencia: sin nombre natural estable (a diferencia del resto de
    # documentos, que usan `clave_logica` como `nombre_archivo`), se sirven por GUID del
    # Documento -- mismo esquema que las imagenes de Georref.
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/laboral/{causa_laboral_id}/audio/{documento_id}{extension}"
