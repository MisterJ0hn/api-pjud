el tribunal es distinto al de civil, debemos scrapear antes todos los tribunales de laboral y luego puedo obtener desde el endpoint
url : /catalogo/tribunales?competencia=penal


el usuario se debe loguear con un metodo auth
luego de obtener el bearer token el usuario podra consumir el metodo de sincronizar_penal Asincrono:
Request:
{
    "corte":90,
    "tribunal": 387, # el tribunal es distinto al de penal, debemos scrapear antes todos los tribunales de laboral
    "tipo": "A",
    "rol": 1,
    "anio": 2025
}

Causas privadas (con login en la Oficina Judicial Virtual): agregar al request de
sincronizar_penal los campos rut, clave y metodo_login (1 = Clave Poder Judicial,
2 = Clave Unica). corte y tribunal se siguen enviando (solo forman parte de la clave
de la causa; la busqueda privada filtra unicamente por Rit/Rol/Anio). Las credenciales
se guardan cifradas en la cola y se borran cuando el job termina.
{
    "corte":90,
    "tribunal": 387, 
    "tipo": "A",
    "rol": 1,
    "anio": 2025,
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

Luego de sincronizar, el usuario podrá consultar causa con el método consultar_penal:
Request:
{
    "corte":90,
    "tribunal": 387,
    "tipo": "A",
    "rol": 1,
    "anio": 2025
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
        "rit": "A-1-2025", #RIT
        "caratula": "A.F.P. HABITAT S.A. CON CO", #nO TIENE TITULO EN EL MODAL, PERO ESTA AL LADO DEL RIT
        "fecha_ingreso":"14/04/2025", #F. Ing.
        "ruc": "25- 3-0094727-4", #RUC
        "proceso": "Ejecutivo Obligación de Dar", #Proc.
        "forma_inicio":"Demanda", #Forma Inicio
        "estado_proceso": "Tramitación", #Estado Proc.
        "etapa":"1 Notificación demanda y su proveído", #Etapa
        "titulo_ejec":{
            "nombre_archivo":"xxx",
            "url": "https://api-pjud.temposoft.cl/public/titulo_ejec.pdf"
        },
        "juez_asignado":"AMERICA ANTONIA ROJAS ROJAS",
        "tribunal":"Jdo. de Letras de Colina", #Tribunal
        "doc_demanda":{
            "nombre_archivo":"xxxx",
            "ruta":"https://api-pjud.temposoft.cl/public/doc_demanda.pdf"
        },
        "anexos_causa": [
            {
                "fecha":"30/01/2026",
                "referencia": "PAGARE",
                "nombre_doc": "Anexos_causa", #nombre idenpotente
                "doc":"https://api-pjud.temposoft.cl/public/ANEXO_CAUSA_.pdf"
            },{
                "fecha":"30/01/2026",
                "referencia": "CONTRATO",
                "nombre_doc": "Anexos_causa", #nombre idenpotente
                "doc":"https://api-pjud.temposoft.cl/public/ANEXO_CAUSA_.pdf"
            }
        ],
        "ebook":{
            "nombre_archivo": "ebook", # debe ser un nombre IDEMPOTENTE
            "url": "https://api-pjud.temposoft.cl/public/ebook.pdf"
        },
         "certificado_envio":{
            "nombre_archivo": "certificado_envio", # debe ser un nombre IDEMPOTENTE
            "url": "https://api-pjud.temposoft.cl/public/certificado_envio.pdf"
        },
        "documentos_laboral":{

        },
        "informacion_receptor":[
            {
                "cuaderno":"Principal",
                "datos_retiro": "MARIA LORETO PIZARRO QUEZADA",
                "fecha_retiro": "23/03/2026",
                "estado":"Resuelta"
            },
            {
                "cuaderno":"Apremio Ejecutivo Obligación de Dar",
                "datos_retiro": "MARIA LORETO PIZARRO QUEZADA",
                "fecha_retiro": "23/03/2026",
                "estado":"Resuelta"
            }
        ],
        "cuadernos":[
            {
                "id":1,
                "nombre":"1 - principal",
                "estado_proceso": "Tramitación", #Estado Proc.
                "etapa":"1 Notificación demanda y su proveído", #Etapa
            },
            {
                "id":2,
                "nombre":"2 - Apremio Ejecutivo Obligación de Dar",
                "estado_proceso": "Tramitación", #Estado Proc.
                "etapa":"1 Notificación demanda y su proveído", #Etapa
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

Luego de sincronizar, el usuario podrá consultar causa con el método consultar_movimientos_penal:
Request:
{
    "identificador": [GUID]
}
Response 200:
{
    "exito": true,
    "code": 200,
    "historia":[
        {
            "folio": 1,
            // "folio" = parte numerica. "folio_texto" = folio tal cual lo muestra PJUD:
            // "1" normalmente, o "[6E]" para los movimientos de un exhorto (numerados
            // aparte, intercalados por fecha; un mismo "[NE]" puede repetirse si la causa
            // tiene mas de un exhorto).
            "folio_texto": "1",
            // "doc" es un array: 0, 1 o varios documentos por folio (columna "Doc.").
            "doc": [
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
            "tramite":"Actuación Receptor",
            "descripcion_tramite": "NOTIFICACIÓN DE DEMANDA (Exitosa) Diligencia:07/04/2026 17:10",
            "estado_firma":"Firmado",
            "fecha_tramite": "10/04/2026 (07/04/2026)",
            "georref": []
        },
        {
            "folio": 21,
            // "folio" = parte numerica. "folio_texto" = folio tal cual lo muestra PJUD:
            // "1" normalmente, o "[6E]" para los movimientos de un exhorto (numerados
            // aparte, intercalados por fecha; un mismo "[NE]" puede repetirse si la causa
            // tiene mas de un exhorto).
            "folio_texto": "1",
            // "doc" es un array: 0, 1 o varios documentos por folio (columna "Doc.").
            "doc": [],
            "anexo": [],
            "etapa":"Mandamiento",
            "tramite":"Actuación Receptor",
            "descripcion_tramite": {
                "descripcion":"Despachese",
                "doc":{
                    "nombre":"xxx",
                    "ruta":"https://api-pjud.temposoft.cl/public/historia_folio1_tramite_1.pdf"
                }
            },            
            "estado_firma":"Firmado",
            "fecha_tramite": "10/04/2026 (07/04/2026)",
            "georref": { #en pjud es un link que abre un popup id=modalGeoReferenciaFamilia.
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
    "notificaciones":[
        {
            "tipo_notificacion":"e-mail",
            "estado_notificacion": "Realizada",
            "fecha_notificacion":"25/04/2025",
            "fecha_tramite": "30/04/2025",
            "tramite":"resolución",
            "tipo_part": "AB.DTE",
            "nombre":"NICOLÁS ALEJANDRO MUÑOZ FERNÁNDEZ"
        },
        {
            "tipo_notificacion":"e-mail",
            "estado_notificacion": "Realizada",
            "fecha_notificacion":"25/04/2025",
            "fecha_tramite": "30/04/2025",
            "tramite":"resolución",
            "tipo_part": "AB.DTE",
            "nombre":"NICOLÁS ALEJANDRO MUÑOZ FERNÁNDEZ"
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
            "fecha_tramite":"",
            "destinatario":"",
            "responsable":""            
        }
    ],
    "liquidacion":
    [
        {
            "liquidacion":"",
            "fecha_liquidacion":"",
            "cuaderno":"",
            "estado":"",
            "monto_liquido":""
        }
    ],

}
    


