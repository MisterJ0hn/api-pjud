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
