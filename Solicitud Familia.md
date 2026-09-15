

el usuario se debe loguear con un metodo auth
luego de obtener el bearer token el usuario podra consumir el metodo de sincronizar_familia Asincrono:
Estas son siempre Causas privadas (con login en la Oficina Judicial Virtual): agregar al request de
sincronizar_civil los campos rut, clave y metodo_login (1 = Clave Poder Judicial,
2 = Clave Unica). corte y tribunal se siguen enviando (solo forman parte de la clave
de la causa; la busqueda privada filtra unicamente por Rit/Rol/Anio). Las credenciales
se guardan cifradas en la cola y se borran cuando el job termina.
{
    "corte": 11,
    "tribunal": 234,
    "tipo": "C",
    "rol": 11247,
    "anio": 2026,
    "rut": "12345678-9",
    "clave": "****",
    "metodo_login": 1
}
Response 200:
{
    "exito": true,
    "code": 200

}
Response 401
{
    "exito": false,
    "code": 401,
    "mensaje": "No Autorizado"
    
}
Response 409
{
    "exito": false,
    "code": 409,
    "mensaje": "Conflicto",
    "motivo": "intervalo_minimo" | "sincronizacion_en_curso",
    "detalle": "texto explicando el conflicto",
    "reintentar_en": "2026-08-28T20:28:07.915709+00:00"  // ISO 8601, cuándo se puede reintentar
}
// motivo=intervalo_minimo: la causa se sincronizó hace menos de SYNC_MIN_INTERVAL_MINUTES (30 por defecto).
// motivo=sincronizacion_en_curso: ya hay una sincronización con lock vigente (SYNC_LOCK_TIMEOUT_MINUTES, 15 por defecto).
Response 400
{
    "exito": false,
    "code": 409,
    "mensaje": "Error en campo [campo]"
    
}

Luego de sincronizar, el usuario podrá consultar causa con el método consultar_familia. antes de obtener los datos, asegurarse que el usuario tenga acceso a esta causa por medio de la clave:
Request:
{
    "corte": 11,
    "tribunal": 234,
    "tipo": F,
    "rol": 11247,
    "anio": 2026
}
Response 200:
{
    "exito": true,
    "code": 200,
    {
        "identificador": [GUID],
        "estado": "Sincronizando"|"Completo",
        "detalle_estado": "Obteniendo historia de cuaderno Principal", // paso actual mientras estado=Sincronizando; null cuando estado=Completo
         "ultimo_error": null, //para cuando existe algún error al momento de la sincronización. ejemplo: clave incorrecta.
        "fecha_ultima_sincronizacion": "2026-08-10",
        "rit": "C-11247-2026", #RIT
        "caratula": "PROMOTORA CMR FALABELLA S", #nO TIENE TITULO EN EL MODAL, PERO ESTA AL LADO DEL F. Ing.
        "fecha_ingreso":"30/01/2026", #F. Ing.
        "Ruc":"23- 2-4049306-3",  #RUC
        "proceso": "Ejecutivo Obligación de Dar", #Proc.
        "forma_inicio": "Demanda" #Forma Inicio
        "est_adm": "Sin archivar", #Est. Adm.
        "etapa":"1 Notificación demanda y su proveído", #Etapa
        "estado_proceso": "Tramitación", #Estado Proc.
        "tribunal":"1° Juzgado Civil de Valparaíso", #Tribunal        
        "anexos_causa": [
            {
                "folio":"1",
                "fecha":"30/01/2026",
                "referencia": "PAGARE",
                "nombre_doc": "Anexos_causa", #nombre idenpotente
                "doc":"https://api-pjud.temposoft.cl/public/ANEXO_CAUSA_.pdf"
            },{
                "folio":"2",
                "fecha":"30/01/2026",
                "referencia": "CONTRATO",
                "nombre_doc": "Anexos_causa", #nombre idenpotente
                "doc":"https://api-pjud.temposoft.cl/public/ANEXO_CAUSA_.pdf"
            }
        ],
        
        "certificado_envio":{
            "nombre_archivo": "certificado_envio", # debe ser un nombre IDEMPOTENTE
            "url": "https://api-pjud.temposoft.cl/public/certificado_envio.pdf"
        },
        "ebook":{
            "nombre_archivo": "ebook", # debe ser un nombre IDEMPOTENTE
            "url": "https://api-pjud.temposoft.cl/public/ebook.pdf"
        } 
    }
}
Response 401
{
    "exito": false,
    "code": 401,
    "mensaje": "No Autorizado"
    
}
Response 409
{
    "exito": false,
    "code": 409,
    "mensaje": "Conflicto"
    
}
Response 400
{
    "exito": false,
    "code": 409,
    "mensaje": "Error en campo [campo]"
    
}

Luego de sincronizar, el usuario podrá consultar causa con el método consultar_movimientos_familia:
Request:
{
    "identificador": [GUID],
    "cuadeno": 1
}
Response 200:
{
    "exito": true,
    "code": 200,
    "movimientos":[
        {
            "folio": 1,
            // "folio" = parte numerica. "folio_texto" = folio tal cual lo muestra PJUD:
            // "1" normalmente, o "[6E]" para los movimientos de un exhorto (numerados
            // aparte, intercalados por fecha; un mismo "[NE]" puede repetirse si la causa
            // tiene mas de un exhorto).
            "folio_texto": "1",
            // "doc" es un array: 0, 1 o varios documentos por folio (columna "Doc.").
            "doc": [],
            "anexo": [],
            "etapa":"Mandamiento",
            "estado":"Firmado",
            "tramite":"Actuación Receptor",
            "descripcion_tramite": "NOTIFICACIÓN DE DEMANDA (Exitosa) Diligencia:07/04/2026 17:10",
            "fecha_tramite": "10/04/2026 (07/04/2026)",
            # Inicio Actualizacion 14-09-2026
            "georeferencia": { #en pjud es un link que abre un popup id=modalGeoReferenciaFamilia.
                "mapa" : { #se encuentra en la pestaña Mapas href="#mapasGeoRef"
                    "latitud":"3", #id="latitud"
                    "longitud":"33",#id="longitud"
                    "corrector":"10" #id="corrector"
                },
                "imagenes":[ #se encuentra en la pestaña Imagenes href="#imagenesGeoRef"
                    {
                        "img":"https://api-pjud.temposoft.cl/public/GUID.[jpg|png|gif]" # en base de datos, para que no graba el nombre del archivo que esta en alt de img del popup, para que despues lo compares. La url quiero que sea un guid en vez del nombre.
                    },
                    {
                        "img":"https://api-pjud.temposoft.cl/public/GUID.[jpg|png|gif]"
                    } 
                ],
                "videos":[] # por el momento estará vacío. no encuentro ejemplos de que es lo que llega.
            }
            # Fin Actualizacion 14-09-2026
        },
        {
            "folio": 2,
            "doc":[
                {"doc":"https://api-pjud.temposoft.cl/public/movimientos_folio2_.pdf"},
                {"doc":"https://api-pjud.temposoft.cl/public/movimientos_folio2_doc2_.pdf"}
            ],
            "anexo": [
                {
                    "folio":14,
                    "doc":"https://api-pjud.temposoft.cl/public/movimientos_anexo1_folio14_.pdf",
                    "fecha": "24/02/2025",
                    "nombre_documento": "Mandato",
                    "observacion":"certifiado"
                },
                {
                    "folio":15,
                    "doc":"https://api-pjud.temposoft.cl/public/movimientos_anexo1_folio15_.pdf",
                    "fecha": "24/02/2025",
                    "nombre_documento": "Mandato",
                    "observacion":"certifiado"
                }
            ],
            "etapa":"Aud. Prep.",
            "estado":"Firmado",
            "tramite":"Resolución",
            "descripcion_tramite": "Estese al mérito de autos",
            "fecha_tramite": "31/01/2024"
        }
    ],
    "litigantes":[
        {
            "sujeto": "AB.DDO",
            "rut":"18101257-9",
            "persona": "NATURAL",
            "razon_social":"LUIS ALBERTO VERA MAHUZIER (Poder Simple)"
        },
        {
            "sujeto": "AB.DTE",
            "rut":"18431792-3",
            "persona": "NATURAL",
            "razon_social":"NICOLÁS ALEJANDRO MUÑOZ FERNÁNDEZ (Sin Acreditacion)"
        },
        {
            "sujeto": "DTE",
            "rut":"97030000-7",
            "persona": "JURIDICA",
            "razon_social":"BANCO DEL ESTADO D E CHILE"
        }
    ],
    "materias":[
        {
            "codigo":"22005",
            "glosa_de_materia":"DIVORCIO DE COMUN ACUERDO",
            "estado":"Sentencia",
            "fecha_termino":"22/01/2024"
        }
    ],
    "plazos":[
        {
            "tipo_plazo":"",
            "ambito_afectado":"",
            "fecha_inicio":"",
            "fecha_termino":"",
            "duracion":"",
            "estado":"",
            "tramite":"",
            "fecha_suspension":"",
            "fecha_reactivacion":""
        }
    ],
    "notificaciones":[
        {
            "estado_fecha_notif":"Realizada",
            "tipo_notif":"e-mail",
            "ente_notif":"",
            "rit":"C-31-2023",
            "ruc":"23- 2- 4049306-3",
            "fecha_tramite":"22/01/2024",
            "tipo_parte":"AB.DDO.",
            "nombre":"YARELA NATALIA FUICA ALFARO",
            "tramite":"resolución",
            "certificacion":""
        },
        {
            "estado_fecha_notif":"Realizada",
            "tipo_notif":"e-mail",
            "ente_notif":"",
            "rit":"C-31-2023",
            "ruc":"23- 2- 4049306-3",
            "fecha_tramite":"22/01/2024",
            "tipo_parte":"AB.DTE.",
            "nombre":"SCARLYN VALESKA MORALES DÍAZ",
            "tramite":"resolución",
            "certificacion":""
        },
        {
            "estado_fecha_notif":"Realizada",
            "tipo_notif":"e-mail",
            "ente_notif":"",
            "rit":"C-31-2023",
            "ruc":"23- 2- 4049306-3",
            "fecha_tramite":"22/01/2024",
            "tipo_parte":"AB.DTE.",
            "nombre":"YARELA NATALIA FUICA ALFARO",
            "tramite":"resolución",
            "certificacion":""
        }
    ],
    "diligencias":[
        {
            "doc_solicitud":"https://api-pjud.temposoft.cl/public/diligencia_solicitud_1_.pdf",
            "doc_respuesta":"https://api-pjud.temposoft.cl/public/diligencia_respuesta_1_.pdf",
            "estado_diligencia":"",
            "tipo_diligencia":"",
            "fecha_tramite": ""
        }
    ]
}


