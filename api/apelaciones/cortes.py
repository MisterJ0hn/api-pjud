"""Catalogo de Cortes de Apelaciones: value del select `#conCorte` de la Consulta
Unificada con competencia "Corte Apelaciones" (=2). Confirmado en vivo 2026-10-21. A
diferencia de los tribunales (que cambian y se pre-cargan en BD), las 17 cortes son fijas
-> constante en codigo, sin tabla."""

import unicodedata

CORTES: dict[int, str] = {
    10: "C.A. de Arica",
    11: "C.A. de Iquique",
    15: "C.A. de Antofagasta",
    20: "C.A. de Copiapó",
    25: "C.A. de La Serena",
    30: "C.A. de Valparaíso",
    35: "C.A. de Rancagua",
    40: "C.A. de Talca",
    45: "C.A. de Chillan",
    46: "C.A. de Concepción",
    50: "C.A. de Temuco",
    55: "C.A. de Valdivia",
    56: "C.A. de Puerto Montt",
    60: "C.A. de Coyhaique",
    61: "C.A. de Punta Arenas",
    90: "C.A. de Santiago",
    91: "C.A. de San Miguel",
}


def clave_texto(texto: str | None) -> str:
    """Minusculas, sin acentos, sin puntos y con espacios colapsados ('C.A. de Santiago' ==
    'ca de santiago'). Sirve para comparar nombres de corte y de libro."""
    sin_acentos = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sin_acentos.lower().replace(".", "").split())


_POR_NOMBRE = {clave_texto(nombre): id_ for id_, nombre in CORTES.items()}


def resolver_corte(valor: str | int | None) -> int | None:
    """Acepta el nombre ('C.A. de Santiago', tolerante a acentos/mayusculas) o el id (90 /
    '90'). None si no es una corte conocida."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if texto.isdigit():
        return int(texto) if int(texto) in CORTES else None
    return _POR_NOMBRE.get(clave_texto(texto))
