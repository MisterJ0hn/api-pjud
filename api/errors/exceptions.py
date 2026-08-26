class NoAutorizadoError(Exception):
    """401 -- x-client-key o bearer token ausente/invalido/expirado/no coincide."""


class CampoInvalidoError(Exception):
    """400 -- error en un campo especifico de la request (fuera de lo que valida Pydantic)."""

    def __init__(self, campo: str):
        self.campo = campo
        super().__init__(f"Error en campo [{campo}]")


class ConflictoSincronizacionError(Exception):
    """409 -- ya hay una sincronizacion en curso (vigente) para esa causa."""


class NoEncontradoError(Exception):
    """404 -- la causa o el cuaderno solicitado no existe. Extension propia: no definida
    literalmente en Solicitud.md, pero necesaria (no hay otro codigo razonable para
    "consultar_civil sobre una causa nunca sincronizada")."""
