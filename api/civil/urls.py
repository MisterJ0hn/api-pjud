from api.config import settings


def rol_formateado(tipo: str, rol: int, anio: int) -> str:
    return f"{tipo}-{rol}-{anio}"


def url_publica_documento(causa_id, nombre_archivo: str, cuaderno_numero: int | None = None) -> str:
    # Se direcciona por id de causa (UUID), no por rol formateado: la misma RIT puede
    # existir en dos tribunales -> mismo rol_fmt -> URLs y archivos ambiguos.
    base = settings.public_base_url.rstrip("/")
    if cuaderno_numero is not None:
        return f"{base}/public/{causa_id}/{cuaderno_numero}/{nombre_archivo}.pdf"
    return f"{base}/public/{causa_id}/{nombre_archivo}.pdf"


def url_publica_imagen(causa_id, cuaderno_numero: int, documento_id, extension: str) -> str:
    # Imagenes del popup Georeferencia (Historia): sin nombre natural estable, se sirven
    # por GUID (el id del Documento) en vez de por `nombre_archivo` como el resto.
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/{causa_id}/{cuaderno_numero}/img/{documento_id}{extension}"
