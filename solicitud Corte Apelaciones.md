el tribunal es distinto al de civil, debemos scrapear antes todos los tribunales de penal y luego puedo obtener desde el endpoint
url : /catalogo/tribunales?competencia=penal


el usuario se debe loguear con un metodo auth
luego de obtener el bearer token el usuario podra consumir el metodo de sincronizar_apelaciones Asincrono
Request: 
{
    "rol":23414,
    "anio":2026,
    "corte":"C.A. de Santiago"
}

Causas privadas (con login en la Oficina Judicial Virtual): agregar al request de
sincronizar_penal los campos rut, clave y metodo_login (1 = Clave Poder Judicial,
2 = Clave Unica). Las credenciales
se guardan cifradas en la cola y se borran cuando el job termina.
Request:
{
    "rol":23414,
    "anio":2026,
    "corte":"C.A. de Santiago",
    "rut": "12345678-9",
    "clave": "****",
    "metodo_login": 1
}

// motivo=intervalo_minimo: la causa se sincronizó hace menos de SYNC_MIN_INTERVAL_MINUTES (30 por defecto).
// motivo=sincronizacion_en_curso: ya hay una sincronización con lock vigente (SYNC_LOCK_TIMEOUT_MINUTES, 15 por defecto).
Response 400
{
    "exito": false,
    "code": 409,
    "mensaje": "Error en campo [campo]"
    
}

Luego de sincronizar, el usuario podrá consultar causa con el método consultar_apelaciones:
Request:
Request:
{
    "rol":23414,
    "anio":2026,
    "corte":"C.A. de Santiago",
    "rut": "12345678-9",
    "clave": "****",
    "metodo_login": 1
}

Response:
{
    "exito": true,
    "code": 200,
    {
        "identificador": [GUID],
        "estado": "Sincronizando"|"Completo",
        "detalle_estado": "Obteniendo historia de cuaderno Principal", // paso actual mientras estado=Sincronizando; null cuando estado=Completo
        "fecha_ultima_sincronizacion": "2026-08-10",
        "libro": "Civil - 23414 - 2026",
        "fecha": "13/10/2026",
        "estado_recurso": "Vigente",
        "estado_procesal":"Ingresada",
        "ubicacion":"Corte apelaciones",
        "recurso": "CI02-Civil-apelacion sentencia definitiva",
        "corte": "C.A. de Santiago",
        "certificado_envio": {
            "doc":"https://api-pjud.temposoft.cl/public/apelaciones_cert_envio_.pdf", 
            "color":"#ffddee"
        },
        "ebook": {
            "doc":"https://api-pjud.temposoft.cl/public/apelaciones_ebook_.pdf", 
            "color":"#ffddee"
        },
        "texto":[
            {
                "id": 1 , #obtener del target= en formAnexRecurso
                "doc_principal":{"fa-times-circle","#AD5454"},
                "doc":{
                    "doc":"https://api-pjud.temposoft.cl/public/apelaciones_doc_texto_.pdf", 
                    "color":"#ffddee"
                },
                "fecha": "13/10/2026",
                "referencia":"Recurso",
            },
            {
                "id": 2 , #obtener del target= en formAnexRecurso
                "doc_principal":{"fa-check","#AD5454"},
                "doc":{
                    "doc":"https://api-pjud.temposoft.cl/public/apelaciones_doc_texto_.pdf", 
                    "color":"#ffddee"
                },
                "fecha": "13/10/2026",
                "referencia":"Recurso",
            }
        ],
        "anexo":[
            {
                "id": 1,  #obtener del target= en formAnexRecurso
                "doc":{
                    "doc":"https://api-pjud.temposoft.cl/public/apelaciones_doc_anexo_.pdf", 
                    "color":"#ffddee"
                },
                "codigo": "12",
                "tipo_documento": "	Expedientes o sus partes",
                "cantidad":"1",
                "observacion_documento"
            },
            {
                "id": 2,
                "doc":{
                    "doc":"https://api-pjud.temposoft.cl/public/apelaciones_doc_anexo_.pdf", 
                    "color":"#ffddee"
                },
                "codigo": "12",
                "tipo_documento": "	Expedientes o sus partes",
                "cantidad":"1",
                "observacion_documento"
            }
        ],
        "expediente_primera":{ #al obtener estos datos, necesitamos relacionar esta causa con la causa origen en nuestro sistema. 
            "causa_origen": "C - 711 - 2026",
            "caratulado": "TESORERÍA GENERAL DE LA REPUBLICA DE CHILE/CONTRERAS",
            "materia":"Pagaré, Cobro De",
            "tribunal": "3º JUZGADO CIVIL DE SANTIAGO"
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
Luego de sincronizar, el usuario podrá consultar causa con el método consultar_movimientos_apelaciones:
Request:
{
    "identificador": [GUID]
}
Response 200:
{
    "exito": true,
    "code": 200,
    "movimientos":[
        {
            "folio": 5,
            "doc":[                
                {"doc":"https://api-pjud.temposoft.cl/public/historiamovimiento_folio2_.pdf", "color":"#ffddee"},
                {"doc":"https://api-pjud.temposoft.cl/public/movimiento_folio2_doc2_.pdf", "color":"#ffdd44"}               
            ],
            "anexo": [],
            "tramite": "Resolución",
            "descripcion": "	Dec inh Sr. Andrade-Sra. Silva",
            "fecha":"19/10/2026",
            "sala":"tercera",
            "estado":"Bloqueado",
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
        }
    ],
    "liquidantes":[
        {
            "sujeto": "recurrente",
            "rut":"76671201-0",
            "persona":"Juridica",
            "razon_social": "CARLOS RIFO GUZMÁN CONTRATISTA EN OBRAS CIVILES E.I.R.L."
        },
        {
            "sujeto": "Ab.Recurrente",
            "rut":"17314741-4",
            "persona":"Natural",
            "razon_social": "EDUARDO MAURICIO LARA QUIROZ"
        }
    ],
    "exhortos":[
        {

        }
    ],
    "incompentencia":[
        {

        }
    ]

}
    


