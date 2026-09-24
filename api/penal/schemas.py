from pydantic import BaseModel, Field

from api.civil.schemas import GeoReferenciaItem


class CausaPenalRequest(BaseModel):
    corte: int
    tribunal: int
    # "Ordinaria" | "Exhorto" | "Administrativa" | "Extradición" | "Militar" (se valida
    # y normaliza en el router).
    tipo: str = Field(min_length=1, max_length=20)
    rol: int
    anio: int


class SincronizarPenalRequest(CausaPenalRequest):
    """Request de sincronizar_penal. Admite sincronizacion PUBLICA (sin credenciales) o
    PRIVADA si trae `rut` + `clave` + `metodo_login` (1 = Clave Poder Judicial, 2 =
    Clave Unica). `corte` y `tribunal` solo forman parte de la clave de la causa en el
    modo privado (la busqueda filtra por Rit/Rol/Anio)."""

    rut: str | None = None
    clave: str | None = None
    metodo_login: int | None = None


class SincronizarResponse(BaseModel):
    exito: bool = True
    code: int = 200


class CuadernoPenalItem(BaseModel):
    id: int
    nombre: str
    estado_proceso: str | None = None
    etapa: str | None = None


class CausaPenalDetalle(BaseModel):
    identificador: str
    # "Sincronizando" | "Completo" | "Error".
    estado: str
    detalle_estado: str | None = None
    ultimo_error: str | None = None
    fecha_ultima_sincronizacion: str | None = None
    rol: str | None = None
    fecha_ingreso: str | None = None
    caratula: str | None = None
    ruc: str | None = None
    estado_adm: str | None = None
    procedimiento: str | None = None
    ubicacion: str | None = None
    proceso: str | None = None
    forma_inicio: str | None = None
    estado_proceso: str | None = None
    etapa: str | None = None
    tribunal: str | None = None
    # URLs directas (Solicitud Penal.md las define como string, no como objeto).
    acumulada: str | None = None
    certificado_envio: str | None = None
    cuadernos: list[CuadernoPenalItem] = Field(default_factory=list)


class ConsultarPenalResponse(BaseModel):
    exito: bool = True
    code: int = 200
    causa: CausaPenalDetalle


class MovimientosRequest(BaseModel):
    identificador: str


class HistoriaDocItem(BaseModel):
    doc: str | None = None
    color: str | None = None


class HistoriaAnexoItem(BaseModel):
    doc: str | None = None
    color: str | None = None
    fecha: str | None = None
    referencia: str | None = None


class DescripcionTramiteDocItem(BaseModel):
    nombre: str | None = None
    ruta: str | None = None
    color: str | None = None


class DescripcionTramiteDetalle(BaseModel):
    descripcion: str | None = None
    doc: DescripcionTramiteDocItem | None = None


class HistoriaPenalItem(BaseModel):
    folio: int | None = None
    folio_texto: str | None = None
    doc: list[HistoriaDocItem] = Field(default_factory=list)
    anexo: list[HistoriaAnexoItem] = Field(default_factory=list)
    tramite: str | None = None
    # Normalmente string; con documento adjunto es {descripcion, doc:{nombre, ruta}}.
    descripcion_tramite: str | DescripcionTramiteDetalle | None = None
    fecha_tramite: str | None = None
    fecha_firma: str | None = None
    estado: str | None = None


class LitiganteItem(BaseModel):
    participantes: str | None = None
    persona: str | None = None
    razon_social: str | None = None


class NotificacionPenalItem(BaseModel):
    tipo_notificacion: str | None = None
    estado_notificacion: str | None = None
    fecha_notificacion: str | None = None
    nombre: str | None = None
    estampado: str | None = None
    geo: GeoReferenciaItem | None = None


class RelacionItem(BaseModel):
    nombre: str | None = None
    materia: str | None = None
    estado_causa: str | None = None
    fecha_cambio_estado: str | None = None


class MovimientosPenalResponse(BaseModel):
    exito: bool = True
    code: int = 200
    historia: list[HistoriaPenalItem] = Field(default_factory=list)
    litigantes: list[LitiganteItem] = Field(default_factory=list)
    notificaciones: list[NotificacionPenalItem] = Field(default_factory=list)
    # Clave con mayuscula inicial tal cual Solicitud Penal.md ("Relaciones").
    Relaciones: list[RelacionItem] = Field(default_factory=list)
