import unicodedata

from api.config import settings

# Tipos de causa de la competencia Penal (select `#conTipoCausa` de la Consulta
# Unificada: value 1..5, confirmado en vivo 2026-09-24). La API los recibe por nombre.
TIPOS_PENAL = {
    "ordinaria": ("Ordinaria", "1", "O"),
    "exhorto": ("Exhorto", "2", "E"),
    "administrativa": ("Administrativa", "3", "A"),
    "extradicion": ("Extradición", "4", "X"),
    "militar": ("Militar", "5", "M"),
}


def _clave_tipo(tipo: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", tipo or "").encode("ascii", "ignore").decode()
    return sin_acentos.strip().lower()


def normalizar_tipo_penal(tipo: str) -> str | None:
    """Nombre canonico del tipo ('ordinaria' / 'ORDINARIA' -> 'Ordinaria') o None."""
    datos = TIPOS_PENAL.get(_clave_tipo(tipo))
    return datos[0] if datos else None


def valor_select_tipo_penal(tipo: str) -> str | None:
    datos = TIPOS_PENAL.get(_clave_tipo(tipo))
    return datos[1] if datos else None


def rit_formateado(tipo: str, rol: int, anio: int) -> str:
    # Provisorio hasta el primer sync (el worker lo reemplaza con el ROL real de la
    # cabecera de PJUD).
    datos = TIPOS_PENAL.get(_clave_tipo(tipo))
    letra = datos[2] if datos else tipo[:1].upper()
    return f"{letra}-{rol}-{anio}"


def url_publica_documento_penal(causa_penal_id, nombre_archivo: str, extension: str = ".pdf") -> str:
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/penal/{causa_penal_id}/{nombre_archivo}{extension}"


def url_publica_imagen_penal(causa_penal_id, documento_id, extension: str) -> str:
    # Imagenes de Georreferencia: se sirven por GUID (id del Documento).
    base = settings.public_base_url.rstrip("/")
    return f"{base}/public/penal/{causa_penal_id}/img/{documento_id}{extension}"
