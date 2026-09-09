from api.config import settings


def rit_formateado(tipo: str, rol: int, anio: int) -> str:
    return f"{tipo}-{rol}-{anio}"


def url_publica_documento_familia(causa_familia_id, nombre_archivo: str) -> str:
    # Prefijo `/public/familia/<causa_familia_id>/...` para no colisionar con las rutas
    # civiles del router publico (`/public/<causa_id>/...`), que resuelven contra otra
    # tabla. Familia es cuaderno unico, asi que no hay segmento de cuaderno.
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/familia/{causa_familia_id}/{nombre_archivo}.pdf"
