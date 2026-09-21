from pydantic import BaseModel, Field

from api.civil.schemas import CausaRequest, GeoReferenciaItem


class SincronizarCobranzaRequest(CausaRequest):
    """Request de sincronizar_cobranza. Igual que Laboral/Civil: admite sincronizacion
    PUBLICA (sin credenciales) o PRIVADA (con login en la Oficina Judicial Virtual) si
    trae `rut` + `clave` + `metodo_login`. `corte` y `tribunal` se siguen enviando: para
    causas privadas solo forman parte de la clave de la causa, la busqueda privada
    filtra unicamente por Rit/Rol/Anio (ver Solicitud Cobranza.md).

    metodo_login: 1 = Clave Poder Judicial, 2 = Clave Unica.
    """

    rut: str | None = None
    clave: str | None = None
    metodo_login: int | None = None


class SincronizarResponse(BaseModel):
    exito: bool = True
    code: int = 200


class DocumentoRef(BaseModel):
    nombre_archivo: str
    url: str


class AnexoCausaCobranzaItem(BaseModel):
    fecha: str | None = None
    referencia: str | None = None
    nombre_doc: str | None = None
    doc: str | None = None


class InformacionReceptorCobranzaItem(BaseModel):
    cuaderno: str | None = None
    datos_retiro: str | None = None
    fecha_retiro: str | None = None
    estado: str | None = None


class CuadernoCobranzaItem(BaseModel):
    id: int
    nombre: str
    estado_proceso: str | None = None
    etapa: str | None = None


class CausaCobranzaDetalle(BaseModel):
    identificador: str
    # "Sincronizando" | "Completo" | "Error".
    estado: str
    detalle_estado: str | None = None
    ultimo_error: str | None = None
    fecha_ultima_sincronizacion: str | None = None
    rit: str | None = None
    caratula: str | None = None
    fecha_ingreso: str | None = None
    ruc: str | None = None
    proceso: str | None = None
    forma_inicio: str | None = None
    # No esta en el contrato original de Solicitud Cobranza.md, pero SI esta en la
    # cabecera real de PJUD (igual que civil/laboral, que tambien lo exponen).
    est_adm: str | None = None
    estado_proceso: str | None = None
    etapa: str | None = None
    titulo_ejec: DocumentoRef | None = None
    juez_asignado: str | None = None
    tribunal: str | None = None
    doc_demanda: DocumentoRef | None = None
    anexos_causa: list[AnexoCausaCobranzaItem] = Field(default_factory=list)
    ebook: DocumentoRef | None = None
    certificado_envio: DocumentoRef | None = None
    # Solicitud Cobranza.md lo mostraba como objeto vacio ("{}"), sin subcampos
    # definidos. Confirmado en vivo (popup "Detalle Documentos Laboral",
    # modalDocumentoLabCobranza): es una lista Doc./Fecha/Referencia, misma forma que
    # anexos_causa -- se expone asi en vez de mantenerlo como placeholder vacio.
    documentos_laboral: list[AnexoCausaCobranzaItem] = Field(default_factory=list)
    informacion_receptor: list[InformacionReceptorCobranzaItem] = Field(default_factory=list)
    cuadernos: list[CuadernoCobranzaItem] = Field(default_factory=list)


class ConsultarCobranzaResponse(BaseModel):
    exito: bool = True
    code: int = 200
    causa: CausaCobranzaDetalle


class MovimientosRequest(BaseModel):
    # Cobranza es causa-wide (no recibe "cuadeno"), a diferencia de civil -- ver
    # Solicitud Cobranza.md.
    identificador: str


class HistoriaDocItem(BaseModel):
    doc: str | None = None


class HistoriaAnexoItem(BaseModel):
    doc: str | None = None
    fecha: str | None = None
    referencia: str | None = None


class DescripcionTramiteDocItem(BaseModel):
    # Nombres de campo tal cual el ejemplo de Solicitud Cobranza.md ("nombre"/"ruta",
    # a diferencia de DocumentoRef que usa "nombre_archivo"/"url").
    nombre: str | None = None
    ruta: str | None = None


class DescripcionTramiteDetalle(BaseModel):
    descripcion: str | None = None
    doc: DescripcionTramiteDocItem | None = None


class HistoriaCobranzaItem(BaseModel):
    folio: int | None = None
    folio_texto: str | None = None
    doc: list[HistoriaDocItem] = Field(default_factory=list)
    anexo: list[HistoriaAnexoItem] = Field(default_factory=list)
    etapa: str | None = None
    tramite: str | None = None
    # Normalmente un string; para algunas filas PJUD trae un documento adjunto junto a
    # la descripcion (ver Solicitud Cobranza.md, segundo ejemplo de "historia").
    descripcion_tramite: str | DescripcionTramiteDetalle | None = None
    estado_firma: str | None = None
    fecha_tramite: str | None = None
    # Nombre de campo tal cual Solicitud Cobranza.md ("georref", a diferencia de
    # "georeferencia"/"georreferencia" en civil/laboral).
    georref: GeoReferenciaItem | None = None


class LitiganteCobranzaItem(BaseModel):
    sujeto: str | None = None
    rut: str | None = None
    persona: str | None = None
    razon_social: str | None = None


class NotificacionCobranzaItem(BaseModel):
    tipo_notificacion: str | None = None
    estado_notificacion: str | None = None
    fecha_notificacion: str | None = None
    fecha_tramite: str | None = None
    tramite: str | None = None
    tipo_part: str | None = None
    nombre: str | None = None


class DiligenciaCobranzaItem(BaseModel):
    doc_ida: str | None = None
    doc_vta: str | None = None
    estado_diligencia: str | None = None
    rit: str | None = None
    ruc: str | None = None
    tipo_diligencia: str | None = None
    fecha_tramite: str | None = None
    destinatario: str | None = None
    responsable: str | None = None


class LiquidacionCobranzaItem(BaseModel):
    # URL del documento (confirmado en vivo: form GET descargable, no texto).
    liquidacion: str | None = None
    fecha_liquidacion: str | None = None
    cuaderno: str | None = None
    estado: str | None = None
    monto_liquido: str | None = None


class MovimientosCobranzaResponse(BaseModel):
    exito: bool = True
    code: int = 200
    historia: list[HistoriaCobranzaItem] = Field(default_factory=list)
    litigantes: list[LitiganteCobranzaItem] = Field(default_factory=list)
    notificaciones: list[NotificacionCobranzaItem] = Field(default_factory=list)
    diligencias: list[DiligenciaCobranzaItem] = Field(default_factory=list)
    liquidacion: list[LiquidacionCobranzaItem] = Field(default_factory=list)
