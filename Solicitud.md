Necesito llevar esto a un sistema en webapi.  
con un bearer token y con header x-client-key.
el sistema estara en Python con postgresql
Investiga como hacer para que cuando ya tienes escrapeado una causa, solo scrapear de forma incremental.

el usuario se debe loguear con un metodo auth
luego de obtener el bearer token el usuario podra consumir el metodo de sincronizar_civil Asincrono:
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
    "mensaje": "Conflicto"
    
}
Response 400
{
    "exito": false,
    "code": 409,
    "mensaje": "Error en campo [campo]"
    
}

Luego de sincronizar, el usuario podrá consultar causa con el método consultar_civil:
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
        "fecha_ultima_sincronizacion": "2026-08-10",
        "rol": "C-11247-2026", #ROL
        "fecha_ingreso":"30/01/2026", #F. Ing.
        "caratula": "PROMOTORA CMR FALABELLA S", #nO TIENE TITULO EN EL MODAL, PERO ESTA AL LADO DEL F. Ing.
        "est_adm": "Sin archivar", #Est. Adm.
        "proceso": "Ejecutivo Obligación de Dar", #Proc.
        "ubicacion": "Digital", #Ubicación
        "estado_proceso": "Tramitación", #Estado Proc.
        "etapa":"1 Notificación demanda y su proveído", #Etapa
        "tribunal":"1° Juzgado Civil de Valparaíso", #Tribunal
        "texto_demanda":{
            "nombre_archivo": "texto_demanda_", # debe ser un nombre IDEMPOTENTE
            "url": "https://api-pjud.temposoft.cl/public/texto_demanda_.pdf"
        }
        "certificado_envio":{
            "nombre_archivo": "certificado_envio", # debe ser un nombre IDEMPOTENTE
            "url": "https://api-pjud.temposoft.cl/public/certificado_envio.pdf"
        }
        "ebook":{
            "nombre_archivo": "ebook", # debe ser un nombre IDEMPOTENTE
            "url": "https://api-pjud.temposoft.cl/public/ebook.pdf"
        }
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
                "nombre":"1 - principal"
            },
            {
                "id":2,
                "nombre":"2 - Apremio Ejecutivo Obligación de Dar"
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

Luego de sincronizar, el usuario podrá consultar causa con el método consultar_movimientos_civil:
Request:
{
    "identificador": [GUID],
    "cuadeno": 1
}
Response 200:
{
    "exito": true,
    "code": 200,
    "historia":[
        {
            "folio": 1,
            "doc":"https://api-pjud.temposoft.cl/public/historia_folio1_.pdf",
            "anexo": [],
            "etapa":"Mandamiento",
            "tramite":"Actuación Receptor",
            "descripcion_tramite": "NOTIFICACIÓN DE DEMANDA (Exitosa) Diligencia:07/04/2026 17:10",
            "fecha_tramite": "10/04/2026 (07/04/2026)",
            "foja": 0
        },
        {
            "folio": 2,
            "doc":"https://api-pjud.temposoft.cl/public/historia_folio2_.pdf",
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
            "foja": 1
        }
    ],
    "litigantes":[
        {
            "participante": "AB.DDO",
            "rut":"18101257-9",
            "persona": "NATURAL",
            "razon_social":"LUIS ALBERTO VERA MAHUZIER (Poder Simple)"
        },
        {
            "participante": "AB.DTE",
            "rut":"18431792-3",
            "persona": "NATURAL",
            "razon_social":"NICOLÁS ALEJANDRO MUÑOZ FERNÁNDEZ (Sin Acreditacion)"
        },
        {
            "participante": "DTE",
            "rut":"97030000-7",
            "persona": "JURIDICA",
            "razon_social":"BANCO DEL ESTADO D E CHILE"
        }
    ],
    "notificaciones":[
        {
            "rol":"C-11247-2026",
            "estado_notificacion": "Realizada",
            "tipo_notificacion":"mail",
            "fecha_tramite": "30/04/2025",
            "tipo_part": "AB.DTE",
            "nombre":"NICOLÁS ALEJANDRO MUÑOZ FERNÁNDEZ",
            "tramite":"resolución",
            "observacion_fallida": ""
        },
        {
            "rol":"C-11247-2026",
            "estado_notificacion": "Realizada",
            "tipo_notificacion":"mail",
            "fecha_tramite": "30/04/2025",
            "tipo_part": "AB.DTE",
            "nombre":"GONZALO PATRICIO DROGUETT MARCUELLO",
            "tramite":"resolución",
            "observacion_fallida": ""
        },
        {
            "rol":"C-11247-2026",
            "estado_notificacion": "Realizada",
            "tipo_notificacion":"mail",
            "fecha_tramite": "30/04/2025",
            "tipo_part": "AB.DDO",
            "nombre":"LUIS ALBERTO VERA MAHUZIER",
            "tramite":"resolución",
            "observacion_fallida": ""
        }
    ],
    "escritos_resolver":[
        {
            "doc":"https://api-pjud.temposoft.cl/public/historia_escrito1_.pdf",
            "anexo":"",
            "fecha_ingreso":"18/08/2026",
            "tipo_escrito": "Curso progresivo a los autos",
            "solicitante": "Demandante"
        }
    ],
    "exhortos":[
        {
            "rol_origen":"C-11247-2026",
            "tipo_exhorto": "Exhorto",
            "rol_destino":[
                {
                    "nombre": "E-2417-2025",
                    "roles": [
                        {
                            "doc":"https://api-pjud.temposoft.cl/public/historia_escrito1_.pdf",
                            "fecha":"27/11/2025",
                            "referencia":"Folio:11 Devuelve con resultado negativo",
                            "tramite":"Resolución"
                        },
                        {
                            "doc":"https://api-pjud.temposoft.cl/public/historia_escrito2_.pdf",
                            "fecha":"04/09/2025",
                            "referencia":"Folio:8 Certificación búsquedas",
                            "tramite":"Actuación Receptor"
                        },
                        {
                            "doc":"https://api-pjud.temposoft.cl/public/historia_escrito3_.pdf",
                            "fecha":"04/09/2025",
                            "referencia":"Folio:9 Certificación búsquedas",
                            "tramite":"Actuación Receptor"
                        }
                    ]
                }
            ],
            "fecha_ordena_exhorto":"22/07/2025",
            "fecha_ingreso_exhorto": "22/07/2025",
            "tribunal_destino":"1º Juzgado Civil de Temuco",
            "estado_exhorto":"Recepcionado"
        }
    ]

}


