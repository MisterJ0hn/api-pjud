class NoAutorizadoError(Exception):
    """401 -- x-client-key o bearer token ausente/invalido/expirado/no coincide."""


class CampoInvalidoError(Exception):
    """400 -- error en un campo especifico de la request (fuera de lo que valida Pydantic)."""

    def __init__(self, campo: str):
        self.campo = campo
        super().__init__(f"Error en campo [{campo}]")


class ConflictoSincronizacionError(Exception):
    """409 -- no se puede encolar la sincronizacion ahora. `motivo` distingue el caso
    (para poder identificarlo desde el cliente / los logs):

    - "intervalo_minimo": la causa se sincronizo hace muy poco (< SYNC_MIN_INTERVAL_MINUTES).
    - "sincronizacion_en_curso": ya hay una sincronizacion vigente (lock activo).
    """

    def __init__(self, motivo: str, detalle: str, reintentar_en: str | None = None):
        self.motivo = motivo
        self.detalle = detalle
        self.reintentar_en = reintentar_en
        super().__init__(detalle)


class NoEncontradoError(Exception):
    """404 -- la causa o el cuaderno solicitado no existe. Extension propia: no definida
    literalmente en Solicitud.md, pero necesaria (no hay otro codigo razonable para
    "consultar_civil sobre una causa nunca sincronizada")."""
