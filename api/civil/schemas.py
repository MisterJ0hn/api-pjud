from pydantic import BaseModel, Field


class CausaRequest(BaseModel):
    corte: int
    tribunal: int
    tipo: str = Field(min_length=1, max_length=4)
    rol: int
    anio: int


class SincronizarCivilRequest(CausaRequest):
    """Request de sincronizar_civil. Si trae `rut` + `clave` + `metodo_login`, la causa
    se sincroniza en modo privado (con login en la Oficina Judicial Virtual) en vez de
    la Consulta Unificada publica. `corte` y `tribunal` se siguen enviando: para causas
    privadas solo forman parte de la clave de la causa, no se usan para navegar.

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


class AnexoCausaItem(BaseModel):
    fecha: str | None = None
    referencia: str | None = None
    nombre_doc: str | None = None
    doc: str | None = None


class InformacionReceptorItem(BaseModel):
    cuaderno: str | None = None
    datos_retiro: str | None = None
    fecha_retiro: str | None = None
    estado: str | None = None


class CuadernoItem(BaseModel):
    id: int
    nombre: str


class CausaDetalle(BaseModel):
    identificador: str
    estado: str
    # Paso actual de una sincronizacion en curso (p. ej. "Obteniendo historia de
    # cuaderno Principal"). None cuando estado == "Completo".
    detalle_estado: str | None = None
    fecha_ultima_sincronizacion: str | None = None
    rol: str | None = None
    fecha_ingreso: str | None = None
    caratula: str | None = None
    est_adm: str | None = None
    proceso: str | None = None
    ubicacion: str | None = None
    estado_proceso: str | None = None
    etapa: str | None = None
    tribunal: str | None = None
    texto_demanda: DocumentoRef | None = None
    certificado_envio: DocumentoRef | None = None
    ebook: DocumentoRef | None = None
    anexos_causa: list[AnexoCausaItem] = Field(default_factory=list)
    informacion_receptor: list[InformacionReceptorItem] = Field(default_factory=list)
    cuadernos: list[CuadernoItem] = Field(default_factory=list)


class ConsultarCivilResponse(BaseModel):
    exito: bool = True
    code: int = 200
    causa: CausaDetalle


class MovimientosRequest(BaseModel):
    identificador: str
    # Nombre de campo preservado tal cual llego en Solicitud.md (con typo: "cuadeno").
    cuadeno: int


class HistoriaAnexoItem(BaseModel):
    doc: str | None = None
    fecha: str | None = None
    referencia: str | None = None


class HistoriaDocItem(BaseModel):
    doc: str | None = None


class HistoriaItem(BaseModel):
    # `folio`: parte numerica (para ordenar/compatibilidad). `folio_texto`: el folio tal
    # cual lo muestra PJUD -- "33" o "[6E]" para los movimientos de un exhorto.
    folio: int | None = None
    folio_texto: str | None = None
    # Un folio puede traer 0, 1 o varios documentos en la columna "Doc.".
    doc: list[HistoriaDocItem] = Field(default_factory=list)
    anexo: list[HistoriaAnexoItem] = Field(default_factory=list)
    etapa: str | None = None
    tramite: str | None = None
    descripcion_tramite: str | None = None
    fecha_tramite: str | None = None
    foja: int | None = None


class LitiganteItem(BaseModel):
    participante: str | None = None
    rut: str | None = None
    persona: str | None = None
    razon_social: str | None = None


class NotificacionItem(BaseModel):
    rol: str | None = None
    estado_notificacion: str | None = None
    tipo_notificacion: str | None = None
    fecha_tramite: str | None = None
    tipo_part: str | None = None
    nombre: str | None = None
    tramite: str | None = None
    observacion_fallida: str | None = None


class EscritoResolverItem(BaseModel):
    doc: str | None = None
    anexo: str | None = None
    fecha_ingreso: str | None = None
    tipo_escrito: str | None = None
    solicitante: str | None = None


class ExhortoRolItem(BaseModel):
    doc: str | None = None
    fecha: str | None = None
    referencia: str | None = None
    tramite: str | None = None


class ExhortoRolDestinoItem(BaseModel):
    nombre: str
    roles: list[ExhortoRolItem] = Field(default_factory=list)


class ExhortoItem(BaseModel):
    rol_origen: str | None = None
    tipo_exhorto: str | None = None
    rol_destino: list[ExhortoRolDestinoItem] = Field(default_factory=list)
    fecha_ordena_exhorto: str | None = None
    fecha_ingreso_exhorto: str | None = None
    tribunal_destino: str | None = None
    estado_exhorto: str | None = None


class MovimientosResponse(BaseModel):
    exito: bool = True
    code: int = 200
    historia: list[HistoriaItem] = Field(default_factory=list)
    litigantes: list[LitiganteItem] = Field(default_factory=list)
    notificaciones: list[NotificacionItem] = Field(default_factory=list)
    escritos_resolver: list[EscritoResolverItem] = Field(default_factory=list)
    exhortos: list[ExhortoItem] = Field(default_factory=list)
