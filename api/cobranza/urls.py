from api.config import settings


def rit_formateado(tipo: str, rol: int, anio: int) -> str:
    return f"{tipo}-{rol}-{anio}"


def url_publica_documento_cobranza(causa_cobranza_id, nombre_archivo: str, extension: str = ".pdf") -> str:
    # Prefijo `/public/cobranza/<causa_cobranza_id>/...` para no colisionar con las
    # rutas de las demas competencias del router publico. Cobranza es causa-wide (sin
    # segmento de cuaderno), igual que Laboral. `extension` viene del archivo real en
    # disco; default ".pdf" solo por compatibilidad con quien no la pase.
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/cobranza/{causa_cobranza_id}/{nombre_archivo}{extension}"


def url_publica_imagen_cobranza(causa_cobranza_id, documento_id, extension: str) -> str:
    # Imagenes del popup Georref.: sin nombre natural estable, se sirven por GUID (el
    # id del Documento) en vez de por `nombre_archivo` como el resto de los docs.
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/cobranza/{causa_cobranza_id}/img/{documento_id}{extension}"
