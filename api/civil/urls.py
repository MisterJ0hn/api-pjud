from api.config import settings


def rol_formateado(tipo: str, rol: int, anio: int) -> str:
    return f"{tipo}-{rol}-{anio}"


def url_publica_documento(rol_fmt: str, nombre_archivo: str, cuaderno_numero: int | None = None) -> str:
    base = settings.public_base_url.rstrip("/")
    if cuaderno_numero is not None:
        return f"{base}/public/{rol_fmt}/{cuaderno_numero}/{nombre_archivo}.pdf"
    return f"{base}/public/{rol_fmt}/{nombre_archivo}.pdf"
