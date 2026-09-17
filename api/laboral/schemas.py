from pydantic import BaseModel, Field

from api.civil.schemas import CausaRequest, GeoReferenciaItem


class SincronizarLaboralRequest(CausaRequest):
    """Request de sincronizar_laboral. A diferencia de Familia (siempre privada), Laboral
    admite sincronizacion PUBLICA (Consulta Unificada) o PRIVADA -- igual que Civil: si
    trae `rut` + `clave` + `metodo_login` se sincroniza con login en la Oficina Judicial
    Virtual, si no se usa la Consulta Unificada publica. `corte` y `tribunal` se siguen
    enviando: para causas privadas solo forman parte de la clave de la causa, la
    busqueda privada filtra por Rit/Rol/Anio.

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


class TextoDemandaItem(BaseModel):
    # 0/1 segun el icono de la primera columna del popup (fa-minus/fa-check).
    doc_demanda: int | None = None
    doc: str | None = None
    fecha: str | None = None
    referencia: str | None = None


class AudioItem(BaseModel):
    numero: int | None = None
    audio: str | None = None
    fecha: str | None = None
    referencia: str | None = None


class CausaLaboralDetalle(BaseModel):
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
    est_adm: str | None = None
    etapa: str | None = None
    estado_proceso: str | None = None
    tribunal: str | None = None
    texto_demanda: list[TextoDemandaItem] = Field(default_factory=list)
    tramites: str | None = None
    ebook: DocumentoRef | None = None
    certificado_envio: DocumentoRef | None = None
    audio_laboral: list[AudioItem] = Field(default_factory=list)


class ConsultarLaboralResponse(BaseModel):
    exito: bool = True
    code: int = 200
    causa: CausaLaboralDetalle


class MovimientosRequest(BaseModel):
    # Laboral es cuaderno unico: a diferencia de civil/familia, Solicitud Laboral.md no
    # trae "cuadeno" en este request.
    identificador: str


class MovimientoDocItem(BaseModel):
    doc: str | None = None


class MovimientoAnexoItem(BaseModel):
    folio: int | None = None
    doc: str | None = None
    fecha: str | None = None
    nombre_documento: str | None = None
    observacion: str | None = None


class MovimientoLaboralItem(BaseModel):
    folio: int | None = None
    folio_texto: str | None = None
    doc: list[MovimientoDocItem] = Field(default_factory=list)
    anexo: list[MovimientoAnexoItem] = Field(default_factory=list)
    etapa: str | None = None
    tramite: str | None = None
    descripcion_tramite: str | None = None
    fecha_tramite: str | None = None
    estado: str | None = None
    # Nombre de campo tal cual Solicitud Laboral.md (con doble r, a diferencia de
    # civil/familia que usan "georeferencia").
    georreferencia: GeoReferenciaItem | None = None


class LitiganteLaboralItem(BaseModel):
    estado: int | None = None
    defensor: str | None = None
    sujeto: str | None = None
    rut: str | None = None
    persona: str | None = None
    razon_social: str | None = None


class NotificacionLaboralItem(BaseModel):
    estado_notificacion: str | None = None
    fecha_tramite: str | None = None
    tipo_part: str | None = None
    nombre: str | None = None
    tramite: str | None = None
    observacion_fallida: str | None = None


class DiligenciaLaboralItem(BaseModel):
    doc_ida: str | None = None
    doc_vta: str | None = None
    estado_diligencia: str | None = None
    rit: str | None = None
    ruc: str | None = None
    tipo_diligencia: str | None = None
    referencia: str | None = None
    fecha_tramite: str | None = None


class MateriaLaboralItem(BaseModel):
    codigo: str | None = None
    glosa_materia: str | None = None
    estado: str | None = None
    fecha_termino: str | None = None


class LiquidacionItem(BaseModel):
    liquidacion: str | None = None
    rut: str | None = None
    nombre: str | None = None
    monto_liquido: str | None = None


class EscritoPendienteItem(BaseModel):
    doc: str | None = None
    anexo: str | None = None
    fecha_ing: str | None = None
    referencia: str | None = None
    solicitante: str | None = None
    tipo_ingreso: str | None = None


class MovimientosLaboralResponse(BaseModel):
    exito: bool = True
    code: int = 200
    movimiento: list[MovimientoLaboralItem] = Field(default_factory=list)
    litigantes: list[LitiganteLaboralItem] = Field(default_factory=list)
    notificaciones: list[NotificacionLaboralItem] = Field(default_factory=list)
    diligencias: list[DiligenciaLaboralItem] = Field(default_factory=list)
    liquidacion: list[LiquidacionItem] = Field(default_factory=list)
    materias: list[MateriaLaboralItem] = Field(default_factory=list)
    escritos_pendientes: list[EscritoPendienteItem] = Field(default_factory=list)
