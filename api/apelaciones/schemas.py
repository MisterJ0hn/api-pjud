from pydantic import BaseModel, Field

from api.common.callback import CallbackMixin

from api.civil.schemas import GeoReferenciaItem


class CausaApelacionesRequest(BaseModel):
    rol: int
    anio: int
    # Nombre ("C.A. de Santiago") o id (90) de la Corte; ver GET /catalogo/cortes.
    corte: str | int
    # Libro del recurso ("Civil", "Protección", "Amparo", ...). Opcional: el mismo rol/anio
    # puede existir en varios libros de la misma Corte; si hay mas de uno y no se indica,
    # la sincronizacion falla pidiendolo.
    libro: str | None = Field(default=None, max_length=80)


class ConsultarApelacionesRequest(CausaApelacionesRequest):
    """`rut` opcional, igual que las demas competencias (causas privadas)."""

    rut: str | None = None


class SincronizarApelacionesRequest(CallbackMixin, CausaApelacionesRequest):
    """PUBLICA (sin credenciales) o PRIVADA con `rut` + `clave` + `metodo_login` (1 = Clave
    Poder Judicial, 2 = Clave Unica)."""

    rut: str | None = None
    clave: str | None = None
    metodo_login: int | None = None


class SincronizarResponse(BaseModel):
    exito: bool = True
    code: int = 200
    # Id de la sincronizacion: es el que llega en el callback_url (si se pidio).
    job_id: int | None = None


class DocColorItem(BaseModel):
    doc: str | None = None
    color: str | None = None


class DocPrincipalItem(BaseModel):
    icono: str | None = None
    color: str | None = None


class TextoItem(BaseModel):
    id: int | None = None
    doc_principal: DocPrincipalItem | None = None
    doc: DocColorItem | None = None
    fecha: str | None = None
    referencia: str | None = None


class AnexoItem(BaseModel):
    id: int | None = None
    doc: DocColorItem | None = None
    codigo: str | None = None
    tipo_documento: str | None = None
    cantidad: str | None = None
    observacion_documento: str | None = None


class ExpedientePrimeraItem(BaseModel):
    causa_origen: str | None = None
    caratulado: str | None = None
    materia: str | None = None
    tribunal: str | None = None
    ruc: str | None = None
    fecha_ingreso: str | None = None
    # Causa origen ya existente en nuestro sistema (None si no se ha sincronizado).
    causa_origen_competencia: str | None = None
    causa_origen_identificador: str | None = None


class CausaApelacionesDetalle(BaseModel):
    identificador: str
    # "Sincronizando" | "Completo" | "Error".
    estado: str
    detalle_estado: str | None = None
    ultimo_error: str | None = None
    fecha_ultima_sincronizacion: str | None = None
    libro: str | None = None
    fecha: str | None = None
    estado_recurso: str | None = None
    estado_procesal: str | None = None
    ubicacion: str | None = None
    recurso: str | None = None
    corte: str | None = None
    certificado_envio: DocColorItem | None = None
    ebook: DocColorItem | None = None
    texto: list[TextoItem] = Field(default_factory=list)
    anexo: list[AnexoItem] = Field(default_factory=list)
    expediente_primera: ExpedientePrimeraItem | None = None


class ConsultarApelacionesResponse(BaseModel):
    exito: bool = True
    code: int = 200
    causa: CausaApelacionesDetalle


class MovimientosRequest(BaseModel):
    identificador: str
    rut: str | None = None


class MovimientoAnexoItem(BaseModel):
    doc: str | None = None
    color: str | None = None
    fecha: str | None = None
    referencia: str | None = None


class MovimientoApelacionesItem(BaseModel):
    folio: int | None = None
    doc: list[DocColorItem] = Field(default_factory=list)
    anexo: list[MovimientoAnexoItem] = Field(default_factory=list)
    tramite: str | None = None
    descripcion: str | None = None
    fecha: str | None = None
    sala: str | None = None
    estado: str | None = None
    georeferencia: GeoReferenciaItem | None = None


class LiquidanteItem(BaseModel):
    sujeto: str | None = None
    rut: str | None = None
    persona: str | None = None
    razon_social: str | None = None


class MovimientosApelacionesResponse(BaseModel):
    exito: bool = True
    code: int = 200
    movimientos: list[MovimientoApelacionesItem] = Field(default_factory=list)
    liquidantes: list[LiquidanteItem] = Field(default_factory=list)
    # Columnas no validadas (sin ejemplos con datos): filas crudas {columna: texto}.
    exhortos: list[dict] = Field(default_factory=list)
    incompentencia: list[dict] = Field(default_factory=list)
