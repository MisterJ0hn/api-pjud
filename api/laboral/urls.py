from api.config import settings


def rit_formateado(tipo: str, rol: int, anio: int) -> str:
    return f"{tipo}-{rol}-{anio}"


def url_publica_documento_laboral(causa_laboral_id, nombre_archivo: str) -> str:
    # Prefijo `/public/laboral/<causa_laboral_id>/...` para no colisionar con las rutas
    # civiles/familia del router publico. Laboral es cuaderno unico, sin segmento de
    # cuaderno.
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/laboral/{causa_laboral_id}/{nombre_archivo}.pdf"


def url_publica_imagen_laboral(causa_laboral_id, documento_id, extension: str) -> str:
    # Imagenes del popup Georref.: sin nombre natural estable, se sirven por GUID (el
    # id del Documento) en vez de por `nombre_archivo` como el resto de los docs.
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/laboral/{causa_laboral_id}/img/{documento_id}{extension}"


def url_publica_audio_laboral(causa_laboral_id, documento_id, extension: str) -> str:
    # Audios de audiencia (mp3, no pdf): mismo esquema que las imagenes de Georref --
    # `url_publica_documento_laboral` no sirve porque fuerza `.pdf` (todo el resto de
    # documentos de Laboral SI son pdf, asi que esa funcion no cambia).
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/laboral/{causa_laboral_id}/audio/{documento_id}{extension}"
