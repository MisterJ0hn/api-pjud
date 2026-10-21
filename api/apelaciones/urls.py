from api.config import settings


def url_publica_documento_apelaciones(causa_id, nombre_archivo: str, extension: str = ".pdf") -> str:
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/apelaciones/{causa_id}/{nombre_archivo}{extension}"


def url_publica_imagen_apelaciones(causa_id, documento_id, extension: str) -> str:
    # Imagenes de Georreferencia: se sirven por GUID (id del Documento).
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/apelaciones/{causa_id}/img/{documento_id}{extension}"
