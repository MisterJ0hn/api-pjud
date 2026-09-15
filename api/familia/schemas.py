from pydantic import BaseModel, Field

from api.civil.schemas import CausaRequest


class SincronizarFamiliaRequest(CausaRequest):
    """Request de sincronizar_familia. Las causas de Familia son SIEMPRE privadas (con
    login en la Oficina Judicial Virtual), asi que `rut` + `clave` + `metodo_login` son
    OBLIGATORIOS. `corte` y `tribunal` se siguen enviando pero solo forman parte de la
    clave de la causa (la busqueda privada filtra por Rit/Rol/Anio).

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
    # Indice secuencial (1, 2, ...) asignado al exponer la respuesta: el sub-modal
    # "Anexos de la causa" de PJUD no trae una columna Folio propia.
    folio: str | None = None
    fecha: str | None = None
    referencia: str | None = None
    nombre_doc: str | None = None
    doc: str | None = None


class CausaFamiliaDetalle(BaseModel):
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
    anexos_causa: list[AnexoCausaItem] = Field(default_factory=list)
    certificado_envio: DocumentoRef | None = None
    ebook: DocumentoRef | None = None


class ConsultarFamiliaResponse(BaseModel):
    exito: bool = True
    code: int = 200
    causa: CausaFamiliaDetalle


class MovimientosRequest(BaseModel):
    identificador: str
    # Nombre de campo preservado tal cual el contrato (typo "cuadeno"). Familia es
    # cuaderno unico: se valida == 1.
    cuadeno: int = 1


class HistoriaDocItem(BaseModel):
    doc: str | None = None


class HistoriaAnexoItem(BaseModel):
    folio: int | None = None
    doc: str | None = None
    fecha: str | None = None
    nombre_documento: str | None = None
    observacion: str | None = None


class GeoReferenciaMapa(BaseModel):
    latitud: str | None = None
    longitud: str | None = None
    corrector: str | None = None


class GeoReferenciaImagenItem(BaseModel):
    img: str | None = None


class GeoReferenciaItem(BaseModel):
    mapa: GeoReferenciaMapa | None = None
    imagenes: list[GeoReferenciaImagenItem] = Field(default_factory=list)
    # PJUD no trae ejemplos de video en el popup todavia; queda vacio hasta conocer su
    # estructura.
    videos: list = Field(default_factory=list)


class MovimientoFamiliaItem(BaseModel):
    folio: int | None = None
    folio_texto: str | None = None
    doc: list[HistoriaDocItem] = Field(default_factory=list)
    anexo: list[HistoriaAnexoItem] = Field(default_factory=list)
    etapa: str | None = None
    estado: str | None = None
    tramite: str | None = None
    descripcion_tramite: str | None = None
    fecha_tramite: str | None = None
    georeferencia: GeoReferenciaItem | None = None


class LitiganteFamiliaItem(BaseModel):
    sujeto: str | None = None
    rut: str | None = None
    persona: str | None = None
    razon_social: str | None = None


class MateriaItem(BaseModel):
    codigo: str | None = None
    glosa_de_materia: str | None = None
    estado: str | None = None
    fecha_termino: str | None = None


class PlazoItem(BaseModel):
    tipo_plazo: str | None = None
    ambito_afectado: str | None = None
    fecha_inicio: str | None = None
    fecha_termino: str | None = None
    duracion: str | None = None
    estado: str | None = None
    tramite: str | None = None
    fecha_suspension: str | None = None
    fecha_reactivacion: str | None = None


class NotificacionFamiliaItem(BaseModel):
    estado_fecha_notif: str | None = None
    tipo_notif: str | None = None
    ente_notif: str | None = None
    rit: str | None = None
    ruc: str | None = None
    fecha_tramite: str | None = None
    tipo_parte: str | None = None
    nombre: str | None = None
    tramite: str | None = None
    certificacion: str | None = None


class DiligenciaItem(BaseModel):
    doc_solicitud: str | None = None
    doc_respuesta: str | None = None
    estado_diligencia: str | None = None
    tipo_diligencia: str | None = None
    fecha_tramite: str | None = None


class MovimientosFamiliaResponse(BaseModel):
    exito: bool = True
    code: int = 200
    movimientos: list[MovimientoFamiliaItem] = Field(default_factory=list)
    litigantes: list[LitiganteFamiliaItem] = Field(default_factory=list)
    materias: list[MateriaItem] = Field(default_factory=list)
    plazos: list[PlazoItem] = Field(default_factory=list)
    notificaciones: list[NotificacionFamiliaItem] = Field(default_factory=list)
    diligencias: list[DiligenciaItem] = Field(default_factory=list)
