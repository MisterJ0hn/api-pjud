el tribunal es distinto al de civil, debemos scrapear antes todos los tribunales de laboral y luego puedo obtener desde el endpoint
url : /tribunal?competencia=laboral


el usuario se debe loguear con un metodo auth
luego de obtener el bearer token el usuario podra consumir el metodo de sincronizar_laboral Asincrono:
Request:
{
    "corte":44,
    "tribunal": 234, # el tribunal es distinto al de civil, debemos scrapear antes todos los tribunales de laboral
    "tipo": C,
    "rol": 11247,
    "anio": 2026
}

Causas privadas (con login en la Oficina Judicial Virtual): agregar al request de
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

Luego de sincronizar, el usuario podrá consultar causa con el método consultar_laboral:
Request:
{
    "corte": 11,
    "tribunal": 234,
    "tipo": C,
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
        "fecha_ultima_sincronizacion": "2026-08-10",
        "rit": "C-11247-2026", #RIT
        "caratula": "PROMOTORA CMR FALABELLA S", #nO TIENE TITULO EN EL MODAL, PERO ESTA AL LADO DEL RIT
        "fecha_ingreso":"30/01/2026", #F. Ing.
        "ruc": "26- 4-0801550-1", #RUC
        "proceso": "Ejecutivo Obligación de Dar", #Proc.
        "forma_inicio":"Demanda", #Forma Inicio
        "est_adm": "Sin archivar", #Est. Adm.
        "etapa":"1 Notificación demanda y su proveído", #Etapa
        "estado_proceso": "Tramitación", #Estado Proc.
        "tribunal":"1° Juzgado Civil de Valparaíso", #Tribunal
        "texto_demanda": #texto demanda tiene un icono de carpeta, este despliega un popup id=modalTextoDemandaLaboral. Manten el orden que tiene en pjud
        [
            {
                "doc_demanda":1, # el primer td tiene un class, si el class tiene un fa-minus = 0 si tiene un fa-check = 1
                "doc": "https://api-pjud.temposoft.cl/public/texto_demanda_1.pdf",
                "fecha":"19/05/2026",
                "referencia":"demanda"
            },
            {
                "doc_demanda":0, # el primer td tiene un class, si el class tiene un fa-minus = 0 si tiene un fa-check = 1
                "doc": "https://api-pjud.temposoft.cl/public/texto_demanda_1.pdf",
                "fecha":"19/05/2026",
                "referencia":"mandato" # puede estar vacio
            }

        ],
       
        "tramites":"",
        "ebook":{
            "nombre_archivo": "ebook", # debe ser un nombre IDEMPOTENTE
            "url": "https://api-pjud.temposoft.cl/public/ebook.pdf"
        },
        "certificado_envio":{
            "nombre_archivo": "certificado_envio", # debe ser un nombre IDEMPOTENTE
            "url": "https://api-pjud.temposoft.cl/public/certificado_envio.pdf"
        },
        "audio_laboral":
        [
            {
                "numero":1,
                "audio": "https://api-pjud.temposoft.cl/public/audio_1.mp3",
                "fecha":"", 
                "referencia":"2640792897-K-151-260727-00-01- Indiv Partes O102026.mp3"
            }
        ]
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

Luego de sincronizar, el usuario podrá consultar causa con el método consultar_movimientos_laboral:
Request:
{
    "identificador": [GUID]
}
Response 200:
{
    "exito": true,
    "code": 200,
    "movimiento":[
        {
            "folio": 1, 
            // "folio" = parte numerica. "folio_texto" = folio tal cual lo muestra PJUD:
            // "1" normalmente, o "[6E]" para los movimientos de un exhorto (numerados
            // aparte, intercalados por fecha; un mismo "[NE]" puede repetirse si la causa
            // tiene mas de un exhorto).
            "folio_texto": "1",
            // "doc" es un array: 0, 1 o varios documentos por folio (columna "Doc.").
            "doc":  #verifica si en vez de documento viene un modal, si es modal. analiza y dame una opcion para desolver este dilema
            [
                {"doc":"https://api-pjud.temposoft.cl/public/movimiento_folio1_.pdf"},
                {"doc":"https://api-pjud.temposoft.cl/public/movimiento_folio1_doc2_.pdf"}
            ],
            "anexo": [],
            "etapa":"Mandamiento",
            "tramite":"Actuación Receptor",
            "descripcion_tramite": "NOTIFICACIÓN DE DEMANDA (Exitosa) Diligencia:07/04/2026 17:10",
            "fecha_tramite": "10/04/2026 (07/04/2026)",
            "estado":"Firmado",
            "georreferencia":  { #en pjud es un link que abre un popup id=modalGeoReferenciaLaboral.
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
        },
        {
            "folio": 2,
            "doc":[
                {"doc":"https://api-pjud.temposoft.cl/public/historia_folio2_.pdf"},
                {"doc":"https://api-pjud.temposoft.cl/public/historia_folio2_doc2_.pdf"}
            ],
            "anexo": [
                {
                    "doc":"https://api-pjud.temposoft.cl/public/historia_anexo1_folio2_.pdf",
                    "fecha": "24/02/2025",
                    "referencia": "Mandato"
                },
                {
                    "doc":"https://api-pjud.temposoft.cl/public/historia_anexo2_folio2_.pdf",
                    "fecha": "24/02/2025",
                    "referencia": "Mandato"
                }
            ],
            "etapa":"Mandamiento",
            "tramite":"",
            "descripcion_tramite": "Mandamiento",
            "fecha_tramite": "05/02/2026",
            "estado":"Firmado",
            "georreferencia":  { #en pjud es un link que abre un popup id=modalGeoReferenciaLaboral.
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
        }
    ],
    "litigantes":[
        {
            "estado":1, # el primer td tiene un class, si el class tiene un fa-minus = 0 si tiene un fa-check = 1
            "defensor": "No",
            "sujeto": "T.EXC",
            "rut":"18101257-9",
            "persona": "JURIDICA",
            "razon_social":"LUIS ALBERTO VERA MAHUZIER (Poder Simple)"
        },
        {
            "estado":0, # el primer td tiene un class, si el class tiene un fa-minus = 0 si tiene un fa-check = 1
            "defensor": "No",
            "sujeto": "AB.DDO",
            "rut":"14066104-K",
            "persona": "NATURAL",
            "razon_social":"JORGE EDUARDO BECAR JARA (Poder Amplio)"
        }
    ],
    "notificaciones":[
        {
            
            "estado_notificacion": "Realizada",
            "fecha_tramite": "30/04/2025",
            "tipo_part": "AB.DTE",
            "nombre":"NICOLÁS ALEJANDRO MUÑOZ FERNÁNDEZ",
            "tramite":"resolución",
            "observacion_fallida": ""
        },
        {
         
            "estado_notificacion": "Realizada",
            "fecha_tramite": "30/04/2025",
            "tipo_part": "AB.DTE",
            "nombre":"GONZALO PATRICIO DROGUETT MARCUELLO",
            "tramite":"resolución",
            "observacion_fallida": ""
        }
    ],
    "diligencias":
    [
        {
            "doc_ida":"",
            "doc_vta":"",
            "estado_diligencia":"",
            "rit":"",
            "ruc":"",
            "tipo_diligencia":"",
            "referencia":"",
            "fecha_tramite":""
        }
    ],
    "liquidacion":
    [
        {
            "liquidacion":"",
            "rut":"",
            "nombre":"",
            "monto_liquido":""
        }
    ],
    "materias":
    [
        {
            "codigo":"L032",
            "glosa_materia":"despido injustificado",
            "estado":"",
            "fecha_termino":""
        },
        {
            "codigo":"L031",
            "glosa_materia":"despido injustificado",
            "estado":"",
            "fecha_termino":""
        }
    ],
    "escritos_pendientes":
    [
        {
            "doc":"",
            "anexo":"",
            "fecha_ing":"",
            "referencia":"",
            "solicitante":"",
            "tipo_ingreso":""
        },
        {
            "doc":"",
            "anexo":"",
            "fecha_ing":"",
            "referencia":"",
            "solicitante":"",
            "tipo_ingreso":""
        }
    ]
}
    


