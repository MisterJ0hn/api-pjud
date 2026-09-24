"""Clientes Playwright (API async) para la Oficina Judicial Virtual (PJUD), usados por
el worker de sincronizacion. Dos modos:

- `PjudSessionAsync`: Consulta Unificada **publica** (sin login), navega por competencia
  + corte + tribunal. Es el equivalente async de `scraper/pjud_client.py` (que se
  mantiene intacto para la app Flask legacy).

- `PjudSessionPrivada`: causas **privadas**, visibles solo tras iniciar sesion (Clave
  Poder Judicial o Clave Unica). Navega "Mis Causas" -> pestana "Civil" -> filtros por
  Rit / Rol / Anio (no hay Corte ni Juzgado).

Ambos comparten, via `_PjudModalScraper`, toda la extraccion del modal de detalle de una
causa (cabecera + cuadernos + pestanas + sub-modales + descargas): una vez abierto el
modal, el DOM es identico en los dos modos.

Diferencias de fondo respecto al cliente sync (`scraper/pjud_client.py`):

1. Extraccion combinada por fila: por cada `<tr>` se devuelve tanto el texto de cada
   celda como los enlaces/descargas que contiene esa celda especifica, para poder
   vincular (p. ej.) el documento de un folio de Historia con ESE folio.

2. No decide nombres de archivo ni escribe en disco: solo entrega URLs de PJUD (validas
   solo dentro de la sesion actual) y expone `descargar_bytes()`. La idempotencia y el
   nombrado los decide el worker (`worker/sync_civil.py`).
"""

import base64
import json
import logging
import os
import re
import time

from playwright.async_api import async_playwright

logger = logging.getLogger("pjud.scraper.async")


def _jwt_expirado(url: str) -> tuple[bool, int | None]:
    """Los documentos de PJUD se piden con una URL que lleva un JWT (?dtaDoc= / ?dtaCert=
    / ...) con `exp` a 1 hora del scrape. Si el sync es largo, los tokens de las ultimas
    filas ya vencieron al momento de descargar. Devuelve (vencido, segundos_restantes)."""
    m = re.search(r"[?&]dta\w*=([^&]+)", url)
    if not m:
        return False, None
    try:
        payload = m.group(1).split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        if not exp:
            return False, None
        restante = int(exp - time.time())
        return restante <= 0, restante
    except Exception:
        return False, None

BASE_URL = "https://oficinajudicialvirtual.pjud.cl/includes/sesion-consultaunificada.php"
HOME_URL = "https://oficinajudicialvirtual.pjud.cl/home/"
INDEX_PRIVADO_URL = "https://oficinajudicialvirtual.pjud.cl/indexN.php"

COMPETENCIAS = {"civil": "3", "laboral": "4", "cobranza": "6"}

PAUSA_ENTRE_CONSULTAS_MS = 4000


def _normalizar_tribunal(nombre: str | None) -> str:
    """Normaliza el nombre de un tribunal para comparar ('18º Juzgado Civil de Santiago'
    del <select> vs. el de la cabecera del modal): minusculas, 'º'->'°', espacios
    colapsados."""
    return re.sub(r"\s+", " ", (nombre or "").lower().replace("º", "°")).strip()


# Selecciona la fila de la causa en la tabla de resultados por RIT. La Consulta Unificada
# puede devolver la misma RIT en varios tribunales (p. ej. C-5656-2021 existe en el 1º y
# en el 18º Juzgado Civil de Santiago); hay que elegir la del tribunal buscado y no la
# primera. La ultima columna de la tabla es "Tribunal".
JS_SELECCIONAR_FILA_RIT = """(args) => {
    const {objetivo, tribunal} = args;
    const norm = s => (s || '').toLowerCase().replace(/\\u00ba/g, '\\u00b0').replace(/\\s+/g, ' ').trim();
    const tribCol = tr => {
        const tds = Array.from(tr.querySelectorAll('td'));
        return tds.length ? tds[tds.length - 1].textContent.trim() : '';
    };
    const candidatas = Array.from(document.querySelectorAll('#busRit td'))
        .filter(td => td.textContent.trim() === objetivo)
        .map(td => td.closest('tr'))
        .filter(Boolean);
    if (!candidatas.length) return {estado: 'no_encontrada'};

    let fila = candidatas[0];
    const t = norm(tribunal);
    if (t && t !== 'todos') {
        // Igualdad exacta (ya normalizada): un 'includes' daria falsos positivos entre
        // ordinales ('2º' es substring de '22º').
        const match = candidatas.find(tr => norm(tribCol(tr)) === t);
        if (match) {
            fila = match;
        } else if (candidatas.length > 1) {
            // Varias RIT iguales y ninguna del tribunal buscado -> ambiguo, no adivinar.
            return {estado: 'tribunal_no_coincide', tribunales: candidatas.map(tribCol)};
        }
        // Un solo candidato: la busqueda ya venia filtrada por #conTribunal; una
        // diferencia de formato con el <option> no deberia descartarlo (la cabecera
        // del modal se verifica igual despues).
    }
    const firstTd = fila.querySelector('td');
    const clickable = firstTd.querySelector('a,button,i,span') || firstTd;
    clickable.click();
    return {estado: 'ok', tribunal: tribCol(fila)};
}"""

# Extrae, por cada tabla, sus headers y sus filas -- cada fila trae tanto el texto de
# cada celda (`valores`) como los enlaces/descargas resueltos DENTRO de esa celda
# especifica (`enlaces`). `targets` guarda el atributo `target` de los forms GET (p. ej.
# `<form name="formAnex" ... target="3">` en el popup "Anexo de la Causa"): es el unico
# indicador de orden real de PJUD para esa lista, mas confiable que el orden del DOM o
# la clave natural referencia+fecha (que se puede repetir).
JS_EXTRAER_FILAS_CON_ENLACES = """tables => tables.map(t => {
    // Color del icono <i title="Descargar Documento" style="color:#xxxxxx"> que va dentro
    // del <a>/<form> de cada documento. Se lee del atributo `style` crudo (no de
    // `el.style.color`, que el navegador normaliza a rgb()); si igual viniera como rgb()
    // se convierte a #rrggbb. Sin icono o sin color -> null.
    const colorDoc = el => {
        const i = el.querySelector('i[title*="Descargar"]');
        if (!i) return null;
        const m = /(?:^|;)\\s*color\\s*:\\s*([^;]+)/i.exec(i.getAttribute('style') || '');
        if (!m) return null;
        let c = m[1].trim().toLowerCase();
        const rgb = /^rgba?\\(\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)/.exec(c);
        if (rgb) c = '#' + [rgb[1], rgb[2], rgb[3]].map(n => (+n).toString(16).padStart(2, '0')).join('');
        return c || null;
    };
    const headerRow = t.querySelector('thead tr') || t.querySelector('tr:first-child');
    const headerCells = t.querySelectorAll('thead th');
    const headers = (headerCells.length ? Array.from(headerCells) : Array.from(t.querySelectorAll('tr:first-child th')))
        .map(h => h.textContent.trim());
    const bodyRows = t.querySelectorAll('tbody tr').length ? t.querySelectorAll('tbody tr') : t.querySelectorAll('tr');
    const filas = Array.from(bodyRows).map(tr => {
        // Confirmado en vivo (2026-09-21, popup "Listado de Archivos de Audios de
        // Audiencia" de Laboral): la primera celda de cada fila ("Nro") es <th>, no
        // <td> -- filtrar solo por <td> la saltaba y desalineaba TODAS las columnas
        // siguientes en 1 posicion contra `headers` (asi se explica el "swap"
        // Audio/Fecha/Referencia que se habia diagnosticado antes por sintoma en vez
        // de por causa). Se incluye <th> tambien, excluyendo explicitamente la fila
        // de headers por identidad (relevante solo cuando no hay <thead> propio y
        // `headerRow` termina siendo la primera fila del <tbody>).
        if (tr === headerRow) return null;
        const celdas = Array.from(tr.querySelectorAll('td, th'));
        if (celdas.length === 0) return null;
        const valores = {};
        const enlaces = {};
        const colores = {};
        const posts = {};
        const colores_posts = {};
        const popups = {};
        const targets = {};
        const iconos = {};
        celdas.forEach((td, i) => {
            const header = headers[i] || ('col' + i);
            valores[header] = td.textContent.trim();
            // Columnas de estado por icono sin texto propio (p. ej. "Est." de
            // Litigantes, "Doc. Demanda" del popup Texto Demanda de Laboral): el
            // icono decide 1/0, `textContent` siempre viene vacio. fa-check(-square-o)
            // = 1, fa-minus/fa-ban(-square-o) = 0; si no hay icono reconocible, se deja
            // sin marcar (undefined) en vez de asumir 0.
            const icono = td.querySelector('i[class*="fa-"]');
            if (icono) {
                const cls = icono.className;
                if (/fa-check/.test(cls)) iconos[header] = true;
                else if (/fa-minus|fa-ban/.test(cls)) iconos[header] = false;
            }
            const urls = [];
            const cols = [];
            Array.from(td.querySelectorAll('form')).forEach(form => {
                const input = form.querySelector('input[type="hidden"], input:not([type])') || form.querySelector('input');
                const action = form.getAttribute('action');
                if (!input || !action || !input.name) return;
                const metodo = (form.getAttribute('method') || 'get').toLowerCase();
                if (metodo === 'get') {
                    const url = new URL(action, location.href);
                    url.searchParams.set(input.name, input.value);
                    urls.push(url.toString());
                    cols.push(colorDoc(form));
                    const target = form.getAttribute('target');
                    if (target) (targets[header] = targets[header] || []).push(target);
                } else {
                    // Form POST (p. ej. docFamiliaSii.php): el documento se pide con el
                    // JWT en el body. Se guarda aparte para descargar_post_bytes().
                    (posts[header] = posts[header] || []).push({
                        url: new URL(action, location.href).toString(),
                        field: input.name, value: input.value,
                    });
                    (colores_posts[header] = colores_posts[header] || []).push(colorDoc(form));
                }
            });
            // El trigger de un popup no siempre es un <a> -- "Rol Destino" de Exhortos
            // usa un <label data-toggle="modal">. Los enlaces reales a documentos si son
            // siempre <a href> externo, asi que ese selector se mantiene aparte.
            Array.from(td.querySelectorAll('a[href], label[data-toggle="modal"][href]')).forEach(a => {
                const href = a.getAttribute('href');
                if (!href || href.toLowerCase().startsWith('javascript:')) return;
                if (href.startsWith('#')) {
                    // Carpeta que abre un popup (p. ej. #modalAnexoSolicitudCivil en Historia).
                    if (a.getAttribute('data-toggle') === 'modal') {
                        (popups[header] = popups[header] || []).push(href);
                    }
                    return;
                }
                if (a.tagName === 'A') {
                    urls.push(new URL(href, location.href).toString());
                    cols.push(colorDoc(a));
                }
            });
            if (urls.length) { enlaces[header] = urls; colores[header] = cols; }
        });
        return {valores, enlaces, colores, posts, colores_posts, popups, targets, iconos};
    }).filter(f => f !== null);
    return {headers, filas};
})"""

JS_EXTRAER_CABECERA = """(modalId) => {
    const modal = document.getElementById(modalId);
    const tables = Array.from(modal.querySelectorAll('table.table-titulos'));
    const campos = {};
    const descargas = [];
    const submodales = [];
    tables.forEach(table => {
        Array.from(table.querySelectorAll('td')).forEach(td => {
            const strong = td.querySelector('strong');
            const label = strong ? strong.textContent.trim().replace(/\\s*:\\s*$/, '') : '';
            const form = td.querySelector('form');
            const modalLink = td.querySelector('a[data-toggle="modal"]');
            const select = td.querySelector('select');
            if (form && (form.getAttribute('method') || '').toLowerCase() === 'get') {
                const input = form.querySelector('input');
                if (input) {
                    const url = new URL(form.getAttribute('action'), location.href);
                    url.searchParams.set(input.name, input.value);
                    descargas.push({label, url: url.toString()});
                }
            } else if (modalLink) {
                // La mayoria de estos son iconos sin texto propio (Anexos de la causa,
                // Informacion notificaciones receptor: se abren en un submodal aparte).
                // "Causa Origen" es la excepcion: trae el rol como texto directo en la
                // MISMA celda junto al icono -- no hace falta abrir el popup para leerlo.
                const clone = td.cloneNode(true);
                const strongClone = clone.querySelector('strong');
                if (strongClone) strongClone.remove();
                const texto = clone.textContent.replace(/\\s+/g, ' ').trim();
                if (label && texto) {
                    campos[label] = texto;
                } else {
                    submodales.push({label, target: modalLink.getAttribute('href')});
                }
            } else if (select) {
                // el select de cuaderno se procesa aparte
            } else if (label) {
                const clone = td.cloneNode(true);
                const strongClone = clone.querySelector('strong');
                if (strongClone) strongClone.remove();
                campos[label] = clone.textContent.replace(/\\s+/g, ' ').trim();
            } else {
                // Celda sin <strong>: es la caratula, que va junto al F. Ing. y no
                // tiene etiqueta en el modal (p. ej. "GONZALEZ / RODRIGUEZ").
                const texto = td.textContent.replace(/\\s+/g, ' ').trim();
                if (texto && !campos['Carátula']) campos['Carátula'] = texto;
            }
        });
    });
    return {campos, descargas, submodales};
}"""

JS_MODAL_VISIBLE = """() => {
    const modals = Array.from(document.querySelectorAll('.modal.in'));
    const visible = modals.find(m => m.offsetParent !== null);
    return visible ? visible.id : (modals.length ? modals[modals.length - 1].id : null);
}"""

JS_CERRAR_MODAL = """(modalId) => {
    const modal = document.getElementById(modalId);
    const cerrar = modal.querySelector('.close, button.close, [data-dismiss="modal"]');
    if (cerrar) cerrar.click();
}"""


def _es_seccion_historia(nombre: str, prefijos: tuple[str, ...] = ("historia",)) -> bool:
    n = (nombre or "").strip().lower()
    return any(n.startswith(p) for p in prefijos)


class CausaNoEncontrada(Exception):
    pass


class LoginPrivadoError(Exception):
    """No se pudo iniciar sesion en la Oficina Judicial Virtual (credenciales invalidas,
    Clave Unica rechazada, o el sitio cambio el flujo de login). Error terminal: el
    worker no reintenta."""


class _PjudModalScraper:
    """Extraccion del modal de detalle de una causa, comun a los modos publico y privado.
    Las subclases deben dejar `self._page` y `self._context` listos (sesion Playwright)
    antes de llamar a estos metodos."""

    _page = None
    _context = None
    # Callback opcional `async (texto: str) -> None` para reportar el paso actual de la
    # extraccion (lo setea el worker por job; ver worker/main.py).
    _progreso = None
    # Ids de los popups que puede abrir la columna "Anexo(s)" de Historia/Movimientos.
    # Civil: `modalAnexoSolicitudCivil` (Historia/Piezas Exhorto), `modalAnexoSolEscritoCivil`
    # (Escritos por Resolver, confirmado en vivo en C-1964-2026 -- 2026-09-16),
    # `modalExhortoCivil` ("Detalle de Tramite del Exhorto", columna "Rol Destino" de
    # Exhortos -- trigger es un <label>, no un <a>; forms POST `formTram`, confirmado en
    # vivo en C-1964-2026). Familia: `modalAnexoEscritoFamilia` (Anexo del Escrito, GET)
    # y `modalSIIFamilia` (Documentos SII, POST).
    MODALES_ANEXO_HISTORIA = ("modalAnexoSolicitudCivil", "modalAnexoSolEscritoCivil", "modalExhortoCivil")
    # Prefijos del nombre de la pestana que se trata como "Historia" (dispara la
    # extraccion de anexos por popup). Familia la llama "Movimientos".
    PREFIJOS_HISTORIA = ("historia",)
    # Id del popup de la columna "Georeferencia" de Historia/Movimientos (None = la
    # competencia no lo tiene). Default = Civil (columna "Georref." de Historia,
    # confirmado en vivo en E-1798-2026); Familia lo sobreescribe con su propio modal.
    MODAL_GEOREFERENCIA: str | None = "modalGeoReferenciaCivil"
    # Prefijos de pestanas, fuera de Historia/Movimientos, cuya columna "Anexo" tambien
    # abre un popup de `MODALES_ANEXO_HISTORIA` (misma extraccion generica). Civil:
    # "Piezas Exhorto" usa el mismo modalAnexoSolicitudCivil que Historia; "Escritos por
    # Resolver" usa su propio modalAnexoSolEscritoCivil (mismas columnas Fecha/Referencia);
    # "Exhortos" usa modalExhortoCivil en la columna "Rol Destino" (Doc./Fecha/Referencia/
    # Tramite).
    PREFIJOS_ANEXO_POPUP_EXTRA: tuple[str, ...] = ("piezas exhorto", "escritos por resolver", "exhortos")
    # Ids de sub-modales de CABECERA (no de Historia/Movimientos) cuyas descargas deben
    # dispararse con un click REAL de Playwright en vez de pedir la URL por fetch/HTTP
    # -- ver `_procesar_submodal_con_descarga_click`. Confirmado en vivo (2026-09-18,
    # Laboral): `audio/audioByPass.php` rechaza (pagina de WAF "Request Rejected", HTTP
    # 200) cualquier pedido que no venga de una activacion real del usuario, aunque la
    # sesion/cookies sean validas -- el link es un `<a href=... download="">`, que solo
    # dispara la descarga nativa del navegador con un click de verdad.
    MODALES_DESCARGA_CLICK: frozenset[str] = frozenset()

    async def _reportar(self, texto: str) -> None:
        if self._progreso is None:
            return
        try:
            await self._progreso(texto)
        except Exception:
            logger.exception("Error al reportar progreso '%s'", texto)

    # Baja la URL usando `fetch` DENTRO de la pagina: hereda cookies de sesion, el
    # `Referer`, el origin y los headers `Sec-Fetch-*` tal cual los manda el navegador.
    # Los endpoints de documentos de PJUD (docuN.php / docuS.php) devuelven 403 a un
    # request "pelado" desde el APIRequestContext de Playwright que no lleva esos headers.
    _JS_FETCH_DOC = """async (url) => {
        try {
            const r = await fetch(url, {credentials: 'include', redirect: 'follow'});
            const buf = await r.arrayBuffer();
            const bytes = new Uint8Array(buf);
            let bin = '';
            const CHUNK = 0x8000;
            for (let i = 0; i < bytes.length; i += CHUNK) {
                bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
            }
            return {ok: r.ok, status: r.status,
                    contentType: r.headers.get('content-type') || '', b64: btoa(bin)};
        } catch (e) {
            return {error: String(e)};
        }
    }"""

    # Igual que _JS_FETCH_DOC pero POST con el JWT en el body (form-urlencoded). Lo usan
    # los anexos SII de Familia (docFamiliaSii.php es method=POST).
    _JS_FETCH_DOC_POST = """async ([url, field, value]) => {
        try {
            const body = new URLSearchParams(); body.set(field, value);
            const r = await fetch(url, {method: 'POST', credentials: 'include', redirect: 'follow',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: body.toString()});
            const buf = await r.arrayBuffer();
            const bytes = new Uint8Array(buf);
            let bin = '';
            const CHUNK = 0x8000;
            for (let i = 0; i < bytes.length; i += CHUNK) {
                bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
            }
            return {ok: r.ok, status: r.status,
                    contentType: r.headers.get('content-type') || '', b64: btoa(bin)};
        } catch (e) {
            return {error: String(e)};
        }
    }"""

    def _validar_documento(self, content_type: str, cuerpo: bytes, url: str) -> bool:
        """PJUD responde con placeholders HTML/texto o errores de Oracle cuando el tramite
        no tiene documento real. Loguea el motivo para poder distinguir 'no hay documento'
        de 'PJUD nos bloqueo'."""
        ct = (content_type or "").split(";")[0].strip().lower()
        preview = cuerpo[:300].lstrip()
        if ct in ("text/html", "text/plain", ""):
            logger.warning(
                "Descarga %s: content-type '%s' (no es documento). Inicio del cuerpo: %r",
                url, ct or "(vacio)", preview[:200],
            )
            return False
        if ct == "application/pdf" and not cuerpo.startswith(b"%PDF"):
            logger.warning("Descarga %s: content-type PDF pero el cuerpo no empieza con %%PDF (%r)", url, preview[:60])
            return False
        if preview.startswith(b"ORA-") or b"no data found" in preview.lower():
            logger.warning("Descarga %s: respuesta de error de Oracle (%r)", url, preview[:120])
            return False
        return True

    async def descargar_bytes(self, url: str) -> tuple[str, bytes] | None:
        """Descarga una URL de PJUD y valida que sea realmente un documento. Devuelve
        (content_type, bytes) o None. Intenta primero via `fetch` en la pagina (con la
        sesion completa) y cae al APIRequestContext solo si eso falla."""
        vencido, restante = _jwt_expirado(url)
        if vencido:
            logger.warning(
                "Descarga %s: el token de la URL ya VENCIO hace %ss (el scrape tardo demasiado "
                "en llegar a esta descarga). Se intenta igual, pero PJUD probablemente rechace.",
                url, -restante,
            )
        elif restante is not None and restante < 120:
            logger.warning("Descarga %s: el token vence en %ss (al limite)", url, restante)

        # 1) fetch dentro de la pagina
        try:
            res = await self._page.evaluate(self._JS_FETCH_DOC, url)
        except Exception:
            logger.exception("Error evaluando fetch para %s", url)
            res = None

        if res and not res.get("error"):
            if not res.get("ok"):
                logger.warning("Descarga fallida (HTTP %s, via fetch) para %s", res.get("status"), url)
            else:
                cuerpo = base64.b64decode(res.get("b64") or "")
                ct = res.get("contentType") or ""
                if self._validar_documento(ct, cuerpo, url):
                    return ct.split(";")[0].strip().lower() or "application/octet-stream", cuerpo
                # Contenido invalido via fetch (p. ej. la pagina "Request Rejected" de
                # un WAF, servida con HTTP 200 -- confirmado en vivo 2026-09-18 en el
                # endpoint de audio de Laboral, audioByPass.php): antes se abandonaba
                # aca; ahora se prueba igual el fallback de abajo, que pega con la
                # sesion "pelada" (APIRequestContext) en vez del fetch dentro de la
                # pagina y puede evadir esa regla puntual del WAF.
                logger.info("fetch de %s no devolvio un documento valido; se intenta el fallback", url)
        elif res and res.get("error"):
            logger.warning("fetch de %s fallo en la pagina: %s", url, res["error"])

        # 2) fallback: APIRequestContext con Referer del navegador
        try:
            referer = self._page.url
            resp = await self._context.request.get(url, headers={"Referer": referer} if referer else None)
            if not resp.ok:
                logger.warning("Descarga fallida (HTTP %s, via request) para %s (referer=%s)", resp.status, url, referer)
                return None
            content_type = resp.headers.get("content-type") or ""
            cuerpo = await resp.body()
            if self._validar_documento(content_type, cuerpo, url):
                return content_type.split(";")[0].strip().lower() or "application/octet-stream", cuerpo
            return None
        except Exception:
            logger.exception("Error al descargar %s", url)
            return None

    async def descargar_post_bytes(self, url: str, field: str, value: str) -> tuple[str, bytes] | None:
        """Como `descargar_bytes` pero con POST (JWT en el body). Para los anexos SII de
        Familia (docFamiliaSii.php). Solo via fetch en la pagina (sin fallback)."""
        vencido, _ = _jwt_expirado(f"?{field}={value}")
        if vencido:
            logger.warning("Descarga POST %s: el token ya vencio; se intenta igual", url)
        try:
            res = await self._page.evaluate(self._JS_FETCH_DOC_POST, [url, field, value])
        except Exception:
            logger.exception("Error evaluando fetch POST para %s", url)
            return None
        if not res or res.get("error"):
            logger.warning("fetch POST de %s fallo: %s", url, res and res.get("error"))
            return None
        if not res.get("ok"):
            logger.warning("Descarga POST fallida (HTTP %s) para %s", res.get("status"), url)
            return None
        cuerpo = base64.b64decode(res.get("b64") or "")
        ct = res.get("contentType") or ""
        if self._validar_documento(ct, cuerpo, url):
            return ct.split(";")[0].strip().lower() or "application/octet-stream", cuerpo
        return None

    async def _extraer_filas_con_enlaces(self, selector: str) -> list[dict]:
        return await self._page.eval_on_selector_all(f"{selector} table", JS_EXTRAER_FILAS_CON_ENLACES)

    async def _procesar_submodal(self, modal_id: str, target: str) -> dict | None:
        page = self._page
        if not target or not target.startswith("#"):
            return None
        sub_id = target[1:]
        try:
            await page.click(f'#{modal_id} a[href="{target}"]')
        except Exception:
            logger.warning("No se pudo abrir el sub-modal %s", target)
            return None
        # En Mis Causas los sub-modales cargan su contenido por AJAX (onclick), asi que
        # se espera algo mas que en la Consulta Unificada (donde venian pre-renderizados).
        await page.wait_for_timeout(1600)
        if not await page.query_selector(f"#{sub_id}"):
            logger.warning("Sub-modal %s no aparecio en el DOM", target)
            return None

        tablas = await self._extraer_filas_con_enlaces(f"#{sub_id}")

        await page.evaluate(
            """(subId) => {
                const modal = document.getElementById(subId);
                const cerrar = modal.querySelector('.close, button.close, [data-dismiss="modal"]');
                if (cerrar) cerrar.click();
            }""",
            sub_id,
        )
        await page.wait_for_timeout(300)
        return tablas[0] if tablas else {"headers": [], "filas": []}

    async def _procesar_submodal_con_descarga_click(
        self, modal_id: str, target: str, pausa_entre_clicks_ms: int = 2500
    ) -> dict | None:
        """Como `_procesar_submodal`, pero para popups en `MODALES_DESCARGA_CLICK`:
        ademas de extraer las filas (igual que siempre, via `JS_EXTRAER_FILAS_CON_ENLACES`),
        dispara un click REAL de Playwright sobre el `<a download>` de cada fila y
        captura el archivo por el evento `download` nativo del navegador -- no por
        fetch/APIRequestContext, que este popup rechaza aunque la sesion sea valida
        (ver `MODALES_DESCARGA_CLICK`). Dispara los clicks con pausa (WAF sensible al
        volumen, confirmado en vivo) ANTES de cerrar el popup.

        Cada fila devuelta trae ademas `fila["descarga_click"] = {"ruta_temporal":str,
        "nombre_sugerido": str|None} | None` (None si esa fila no tenia link o la
        descarga fallo) -- el worker decide que hacer con el archivo temporal."""
        page = self._page
        if not target or not target.startswith("#"):
            return None
        sub_id = target[1:]
        try:
            await page.click(f'#{modal_id} a[href="{target}"]')
        except Exception:
            logger.warning("No se pudo abrir el sub-modal %s", target)
            return None
        await page.wait_for_timeout(1600)
        if not await page.query_selector(f"#{sub_id}"):
            logger.warning("Sub-modal %s no aparecio en el DOM", target)
            return None

        tablas = await self._extraer_filas_con_enlaces(f"#{sub_id}")
        seccion = tablas[0] if tablas else {"headers": [], "filas": []}

        filas_dom = page.locator(f"#{sub_id} table tr:has(td)")
        total_dom = await filas_dom.count()
        for idx, fila in enumerate(seccion.get("filas", [])):
            fila["descarga_click"] = None
            if idx >= total_dom:
                continue
            link = filas_dom.nth(idx).locator("a[download]")
            if await link.count() == 0:
                continue
            if idx > 0:
                await page.wait_for_timeout(pausa_entre_clicks_ms)
            try:
                async with page.expect_download(timeout=30000) as download_info:
                    await link.first.click()
                download = await download_info.value
                ruta = await download.path()
                if ruta:
                    fila["descarga_click"] = {
                        "ruta_temporal": ruta, "nombre_sugerido": download.suggested_filename,
                    }
                else:
                    logger.warning("Descarga por click (fila %d de %s): sin archivo temporal", idx, target)
            except Exception:
                logger.exception("Error al descargar por click la fila %d de %s", idx, target)

        await page.evaluate(
            """(subId) => {
                const modal = document.getElementById(subId);
                const cerrar = modal.querySelector('.close, button.close, [data-dismiss="modal"]');
                if (cerrar) cerrar.click();
            }""",
            sub_id,
        )
        await page.wait_for_timeout(300)
        return seccion

    async def _extraer_cuaderno_actual(self, modal_id: str, cuaderno_nombre: str = "Principal") -> dict:
        page = self._page
        tabs = await page.evaluate(
            """(modalId) => {
                const modal = document.getElementById(modalId);
                return Array.from(modal.querySelectorAll('a[data-toggle="tab"]')).map(a => ({
                    nombre: a.textContent.trim(),
                    href: a.getAttribute('href'),
                }));
            }""",
            modal_id,
        )

        secciones = {}
        for tab in tabs:
            href = tab["href"]
            if not href or not href.startswith("#"):
                continue
            await self._reportar(f"Obteniendo {tab['nombre'].strip().lower()} de cuaderno {cuaderno_nombre}")
            try:
                await page.click(f'#{modal_id} a[href="{href}"]')
            except Exception:
                continue
            await page.wait_for_timeout(500)
            pane_id = href[1:]
            tablas = await self._extraer_filas_con_enlaces(f"#{pane_id}")
            seccion = tablas[0] if tablas else {"headers": [], "filas": []}
            if _es_seccion_historia(tab["nombre"], self.PREFIJOS_HISTORIA):
                await self._extraer_anexos_popup_historia(pane_id, seccion)
                if self.MODAL_GEOREFERENCIA:
                    await self._extraer_georeferencia_popup_historia(pane_id, seccion)
            elif _es_seccion_historia(tab["nombre"], self.PREFIJOS_ANEXO_POPUP_EXTRA):
                await self._extraer_anexos_popup_historia(pane_id, seccion)
            secciones[tab["nombre"]] = seccion
        return secciones

    async def _extraer_anexos_popup_historia(self, pane_id: str, seccion: dict) -> None:
        """La columna "Anexo(s)" de Historia/Movimientos puede ser una carpeta que abre un
        popup por AJAX. Segun la competencia hay 1 o varios popups posibles
        (`MODALES_ANEXO_HISTORIA`); en Familia: `modalAnexoEscritoFamilia` (Anexo del
        Escrito) y `modalSIIFamilia` (Documentos SII, descargas por POST).

        Por cada fila con carpeta abre el popup que corresponda y vuelca sus filas en
        `fila["anexos_popup"] = [{"doc": url|None, "doc_post": {url,field,value}|None,
        "valores": {...}, "popup": <id>}, ...]`. Ademas resume el contenido en la celda de
        origen para que el hash de la fila (worker) detecte altas/bajas de anexos."""
        page = self._page
        ids_conocidos = set(self.MODALES_ANEXO_HISTORIA)
        filas = seccion.get("filas", [])
        for idx, fila in enumerate(filas):
            popups = fila.get("popups") or {}
            match = next(
                (
                    (col, href[1:])
                    for col, lst in popups.items()
                    for href in lst
                    if href.startswith("#") and href[1:] in ids_conocidos
                ),
                None,
            )
            if match is None:
                continue
            col_anexo, popup_id = match
            popup_href = f"#{popup_id}"
            # Localiza el trigger de ESTA fila (mismo criterio de filas que
            # JS_EXTRAER_FILAS_CON_ENLACES: filas de tbody con >= 1 <td>). El trigger no
            # siempre es un <a> -- "Rol Destino" de Exhortos usa un <label>.
            clicked = await page.evaluate(
                """([paneId, idx, popupHref]) => {
                    const cont = document.getElementById(paneId);
                    const t = cont && cont.querySelector('table');
                    if (!t) return false;
                    const rows = t.querySelectorAll('tbody tr').length
                        ? t.querySelectorAll('tbody tr') : t.querySelectorAll('tr');
                    const conCeldas = Array.from(rows).filter(tr => tr.querySelectorAll('td').length);
                    const tr = conCeldas[idx];
                    if (!tr) return false;
                    const a = tr.querySelector('[data-toggle="modal"][href="' + popupHref + '"]');
                    if (!a) return false;
                    a.click();
                    return true;
                }""",
                [pane_id, idx, popup_href],
            )
            if not clicked:
                continue
            await page.wait_for_timeout(1600)  # el contenido del popup carga por AJAX
            tablas = await self._extraer_filas_con_enlaces(f"#{popup_id}")
            popup = tablas[0] if tablas else {"filas": []}
            anexos = []
            for pf in popup.get("filas", []):
                v = pf.get("valores", {})
                docs = (pf.get("enlaces") or {}).get("Doc.") or []
                posts = (pf.get("posts") or {}).get("Doc.") or []
                cols = (pf.get("colores") or {}).get("Doc.") or []
                cols_post = (pf.get("colores_posts") or {}).get("Doc.") or []
                anexos.append(
                    {
                        "doc": docs[0] if docs else None,
                        "doc_post": posts[0] if posts else None,
                        # Color del icono "Descargar Documento" (None si no lo trae).
                        "color": (cols[0] if docs else (cols_post[0] if posts and cols_post else None)),
                        # Columnas crudas del popup: el worker las mapea segun `popup`.
                        "valores": v,
                        "popup": popup_id,
                    }
                )
            fila.setdefault("anexos_popup", []).extend(anexos)
            valores_fila = fila.setdefault("valores", {})
            # Normalmente esta celda solo tiene un icono/carpeta (texto vacio) y se
            # reemplaza por un resumen del contenido del popup para que el hash de la
            # fila detecte altas/bajas. "Rol Destino" de Exhortos es la excepcion: ya
            # trae el rol como texto util (p. ej. "E-1798-2026") que no hay que perder.
            if not (valores_fila.get(col_anexo) or "").strip():
                valores_fila[col_anexo] = " | ".join(
                    "~".join(str(x) for x in a.get("valores", {}).values()) for a in anexos
                )
            await page.evaluate(
                """(popupId) => {
                    const m = document.getElementById(popupId);
                    if (!m) return;
                    const c = m.querySelector('.close, button.close, [data-dismiss="modal"]');
                    if (c) c.click();
                }""",
                popup_id,
            )
            await page.wait_for_timeout(300)

    async def _extraer_georeferencia_popup_historia(self, pane_id: str, seccion: dict) -> None:
        """La columna "Georeferencia" de Historia/Movimientos (solo Familia por ahora,
        `self.MODAL_GEOREFERENCIA`) abre un popup con 3 pestanas: Mapas (`#mapasGeoRef`,
        inputs `#latitud`/`#longitud`/`#corrector`), Imagenes (`#imagenesGeoRef`, `<img
        src alt>`) y Videos (estructura desconocida, no se scrapea). Las 3 pestanas se
        renderizan de una sola vez en el mismo AJAX que abre el popup (a diferencia de
        las pestanas de cuaderno, que cargan cada una por su cuenta), asi que no hace
        falta clickearlas: se leen directo del DOM aunque no esten "activas".

        Por cada fila con el link vuelca `fila["georeferencia_popup"] = {"mapa":
        {...}|None, "imagenes": [{"src":.., "alt":..}], "videos": []}` y resume el
        contenido en la celda "Georeferencia" para que el hash de la fila (worker)
        detecte cambios."""
        page = self._page
        popup_id = self.MODAL_GEOREFERENCIA
        popup_href = f"#{popup_id}"
        filas = seccion.get("filas", [])
        for idx, fila in enumerate(filas):
            popups = fila.get("popups") or {}
            match = next(
                (col for col, lst in popups.items() if popup_href in lst),
                None,
            )
            if match is None:
                continue
            col_georef = match
            clicked = await page.evaluate(
                """([paneId, idx, popupHref]) => {
                    const cont = document.getElementById(paneId);
                    const t = cont && cont.querySelector('table');
                    if (!t) return false;
                    const rows = t.querySelectorAll('tbody tr').length
                        ? t.querySelectorAll('tbody tr') : t.querySelectorAll('tr');
                    const conCeldas = Array.from(rows).filter(tr => tr.querySelectorAll('td').length);
                    const tr = conCeldas[idx];
                    if (!tr) return false;
                    const a = tr.querySelector('a[data-toggle="modal"][href="' + popupHref + '"]');
                    if (!a) return false;
                    a.click();
                    return true;
                }""",
                [pane_id, idx, popup_href],
            )
            if not clicked:
                continue
            await page.wait_for_timeout(1600)  # el contenido del popup carga por AJAX
            datos = await page.evaluate(
                """(popupId) => {
                    const raiz = document.getElementById(popupId);
                    if (!raiz) return null;
                    const leer = (id) => {
                        const el = raiz.querySelector('#' + id);
                        if (!el) return null;
                        const v = ('value' in el) ? el.value : el.textContent;
                        const t = (v || '').trim();
                        return t || null;
                    };
                    const lat = leer('latitud'), lon = leer('longitud'), cor = leer('corrector');
                    const mapa = (lat || lon || cor) ? {latitud: lat, longitud: lon, corrector: cor} : null;
                    const imgs = Array.from(raiz.querySelectorAll('#imagenesGeoRef img')).map(img => ({
                        src: img.getAttribute('src') ? new URL(img.getAttribute('src'), location.href).toString() : null,
                        alt: (img.getAttribute('alt') || '').trim() || null,
                    })).filter(i => i.src);
                    return {mapa, imagenes: imgs};
                }""",
                popup_id,
            )
            datos = datos or {"mapa": None, "imagenes": []}
            datos["videos"] = []
            fila["georeferencia_popup"] = datos
            resumen_mapa = "~".join(str(v) for v in (datos["mapa"] or {}).values())
            resumen_imgs = " | ".join(f"{i.get('alt')}:{i.get('src')}" for i in datos["imagenes"])
            fila.setdefault("valores", {})[col_georef] = f"{resumen_mapa}#{resumen_imgs}"
            await page.evaluate(
                """(popupId) => {
                    const m = document.getElementById(popupId);
                    if (!m) return;
                    const c = m.querySelector('.close, button.close, [data-dismiss="modal"]');
                    if (c) c.click();
                }""",
                popup_id,
            )
            await page.wait_for_timeout(300)

    async def _extraer_detalle_de_modal(self, modal_id: str) -> dict:
        """Con el modal de detalle ya abierto (`modal_id`), extrae cabecera + cuadernos y
        cierra el modal. Devuelve {"cabecera": {...}, "cuadernos": [...]}. No descarga
        ningun documento (eso lo decide el worker)."""
        page = self._page

        await self._reportar("Obteniendo cabecera")
        cabecera_info = await page.evaluate(JS_EXTRAER_CABECERA, modal_id)
        campos = cabecera_info.get("campos", {})
        descargas = cabecera_info.get("descargas", [])

        submodales = {}
        if cabecera_info.get("submodales"):
            await self._reportar("Obteniendo anexos de la causa")
        for sub in cabecera_info.get("submodales", []):
            target = sub["target"] or ""
            sub_id = target[1:] if target.startswith("#") else None
            if sub_id in self.MODALES_DESCARGA_CLICK:
                tabla = await self._procesar_submodal_con_descarga_click(modal_id, target)
            else:
                tabla = await self._procesar_submodal(modal_id, target)
            if tabla is not None:
                submodales[sub["label"]] = tabla

        cuaderno_opciones = await page.evaluate(
            """(modalId) => {
                const modal = document.getElementById(modalId);
                const sel = modal.querySelector('select');
                if (!sel) return null;
                return Array.from(sel.options).map(o => ({value: o.value, label: o.textContent.trim()}));
            }""",
            modal_id,
        )

        cuadernos = []
        if cuaderno_opciones:
            select_selector = f"#{modal_id} select"
            etiquetas = [o["label"] for o in cuaderno_opciones]
            for numero, etiqueta in enumerate(etiquetas, start=1):
                if len(etiquetas) > 1:
                    valor_actual = await page.eval_on_selector(
                        select_selector,
                        """(sel, etiqueta) => {
                            const opt = Array.from(sel.options).find(o => o.textContent.trim() === etiqueta);
                            return opt ? opt.value : null;
                        }""",
                        etiqueta,
                    )
                    if valor_actual is None:
                        logger.warning("Cuaderno '%s' ya no aparece en el selector; se omite", etiqueta)
                        continue
                    try:
                        await page.select_option(select_selector, valor_actual)
                    except Exception:
                        logger.exception("No se pudo cambiar al cuaderno '%s'; se omite", etiqueta)
                        continue
                    await page.wait_for_timeout(900)
                nombre_limpio = re.sub(r"^\d+\s*-\s*", "", etiqueta).strip() or etiqueta
                # "Estado Proc."/"Etapa" cambian con el cuaderno seleccionado (confirmado
                # en vivo en C-1964-2026, 2026-09-16) -- se releen de la cabecera despues
                # de cada cambio, no del snapshot inicial (`campos`, que solo vale para el
                # cuaderno que estaba activo al abrir el modal).
                campos_cuaderno = (
                    (await page.evaluate(JS_EXTRAER_CABECERA, modal_id)).get("campos", {})
                    if len(etiquetas) > 1
                    else campos
                )
                secciones = await self._extraer_cuaderno_actual(modal_id, nombre_limpio)
                cuadernos.append({
                    "numero": numero,
                    "nombre": nombre_limpio,
                    "estado_proceso": campos_cuaderno.get("Estado Proc."),
                    "etapa": campos_cuaderno.get("Etapa"),
                    "secciones": secciones,
                })
        else:
            secciones = await self._extraer_cuaderno_actual(modal_id, "Principal")
            cuadernos.append({
                "numero": 1,
                "nombre": "Principal",
                "estado_proceso": campos.get("Estado Proc."),
                "etapa": campos.get("Etapa"),
                "secciones": secciones,
            })

        await page.evaluate(JS_CERRAR_MODAL, modal_id)
        await page.wait_for_timeout(300)

        return {
            "cabecera": {"campos": campos, "descargas": descargas, "submodales": submodales},
            "cuadernos": cuadernos,
        }


class PjudSessionAsync(_PjudModalScraper):
    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def iniciar(self) -> None:
        logger.info("Iniciando sesion Playwright async (headless=%s)", self._headless)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        await self._goto_consulta_unificada()
        logger.info("Sesion Playwright async lista")

    async def cerrar(self) -> None:
        logger.info("Cerrando sesion Playwright async")
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _goto_consulta_unificada(self) -> None:
        await self._page.goto(BASE_URL, wait_until="networkidle")
        await self._ensure_rit_tab()

    async def _ensure_rit_tab(self) -> None:
        page = self._page
        if not await page.is_visible("#competencia"):
            await page.click('a[href="#busRit"]')
        await page.wait_for_selector("#competencia", state="visible")

    async def _seleccionar_competencia_corte(self, competencia: str, corte: str) -> None:
        page = self._page
        await self._ensure_rit_tab()
        await page.select_option("#competencia", COMPETENCIAS[competencia])
        await page.wait_for_timeout(400)
        await page.select_option("#conCorte", corte)
        await page.wait_for_function(
            "document.querySelectorAll('#conTribunal option').length > 1", timeout=15000
        )

    async def get_tribunales(self, competencia: str, corte: str) -> list[dict]:
        await self._seleccionar_competencia_corte(competencia, corte)
        options = await self._page.eval_on_selector_all(
            "#conTribunal option", "els => els.map(e => ({value: e.value, label: e.textContent.trim()}))"
        )
        return [o for o in options if o["value"] not in ("", "0")]

    async def _guardar_diagnostico_no_encontrada(self, tipo: str, rol, anio) -> None:
        """Guarda screenshot + HTML del formulario de busqueda cuando una causa que se
        sabe que existe en PJUD vuelve 'no encontrada'. No hay forma de distinguir desde
        el HTML si fue un bloqueo del WAF, una respuesta lenta que igual gano a los
        reintentos, o un estado de pagina corrupto por la sesion larga del worker -- esto
        deja evidencia real para la proxima vez en vez de seguir adivinando. Nunca debe
        tumbar la busqueda: cualquier fallo al capturar se ignora."""
        try:
            from api.config import settings

            carpeta = os.path.join(settings.log_dir, "diagnostico_no_encontrada")
            os.makedirs(carpeta, exist_ok=True)
            base = f"{tipo}-{rol}-{anio}_{int(time.time())}"
            await self._page.screenshot(path=os.path.join(carpeta, f"{base}.png"), full_page=True)
            html = await self._page.eval_on_selector(
                "#busRit", "el => el.outerHTML"
            ) if await self._page.query_selector("#busRit") else "(no existe #busRit)"
            with open(os.path.join(carpeta, f"{base}.html"), "w", encoding="utf-8") as f:
                f.write(f"<!-- url: {self._page.url} -->\n{html}")
            logger.info("Diagnostico de 'no encontrada' guardado en %s.{png,html}", base)
        except Exception:
            logger.exception("No se pudo guardar el diagnostico de 'no encontrada'")

    async def buscar_y_extraer(
        self, competencia: str, corte: str, tribunal: str, tipo: str, rol, anio, progreso=None
    ) -> dict:
        """Reproduce la busqueda humana de la causa en la Consulta Unificada publica y
        extrae cabecera + cuadernos."""
        page = self._page
        self._progreso = progreso
        logger.info(
            "Buscando causa %s-%s-%s (competencia=%s, corte=%s, tribunal=%s)",
            tipo, rol, anio, competencia, corte, tribunal,
        )
        try:
            await self._seleccionar_competencia_corte(competencia, corte)
            await page.select_option("#conTribunal", tribunal)
            await page.wait_for_timeout(300)
            tribunal_esperado = await page.eval_on_selector(
                "#conTribunal",
                "el => el.selectedOptions.length ? el.selectedOptions[0].textContent.trim() : ''",
            )
            await page.select_option("#conTipoCausa", tipo)
            await page.fill("#conRolCausa", str(rol))
            await page.fill("#conEraCausa", str(anio))
            await page.click('#busRit button[type="submit"]')

            # La tabla de resultados se llena por AJAX; una espera fija puede ganarle a una
            # respuesta lenta de PJUD (mas probable desde la IP del VPS que desde una red
            # residencial) y leerse "no encontrada" con la tabla todavia vacia. Se
            # reintenta la lectura varias veces antes de darla por buena (confirmado con
            # C-49-2026: no encontrada en produccion, encontrada de inmediato en un retest
            # manual).
            objetivo = f"{tipo}-{rol}-{anio}"
            seleccion = None
            for intento, espera_ms in enumerate((1500, 1500, 2000, 2000)):
                await page.wait_for_timeout(espera_ms)
                seleccion = await page.evaluate(
                    JS_SELECCIONAR_FILA_RIT, {"objetivo": objetivo, "tribunal": tribunal_esperado}
                )
                if seleccion["estado"] != "no_encontrada":
                    break
                logger.info(
                    "Causa %s-%s-%s: tabla de resultados vacia en el intento %d, reintentando",
                    tipo, rol, anio, intento + 1,
                )

            if seleccion["estado"] == "no_encontrada":
                logger.info("Causa %s-%s-%s no encontrada", tipo, rol, anio)
                await self._guardar_diagnostico_no_encontrada(tipo, rol, anio)
                return {"encontrada": False}
            if seleccion["estado"] == "tribunal_no_coincide":
                logger.warning(
                    "Causa %s: PJUD devolvio resultados pero ninguno del tribunal esperado %r "
                    "(tribunales en la busqueda: %s)",
                    objetivo, tribunal_esperado, seleccion.get("tribunales"),
                )
                return {"encontrada": False}

            await page.wait_for_timeout(700)
            modal_id = await page.evaluate(JS_MODAL_VISIBLE)
            if not modal_id:
                return {"encontrada": True, "error": "No se pudo abrir el detalle de la causa"}

            detalle = await self._extraer_detalle_de_modal(modal_id)

            # Verificacion final: el modal abierto debe ser del tribunal buscado.
            trib_detalle = (detalle.get("cabecera", {}).get("campos", {}) or {}).get("Tribunal", "")
            if tribunal_esperado and trib_detalle:
                if _normalizar_tribunal(tribunal_esperado) != _normalizar_tribunal(trib_detalle):
                    logger.error(
                        "Causa %s: el detalle abierto es del tribunal %r, se esperaba %r",
                        objetivo, trib_detalle, tribunal_esperado,
                    )
                    return {
                        "encontrada": True,
                        "error": (
                            f"El detalle corresponde al tribunal '{trib_detalle}', "
                            f"no a '{tribunal_esperado}'"
                        ),
                    }

            return {"encontrada": True, **detalle}
        finally:
            self._progreso = None
            await page.wait_for_timeout(PAUSA_ENTRE_CONSULTAS_MS)


class PjudSessionPrivada(_PjudModalScraper):
    """Sesion autenticada en la Oficina Judicial Virtual para causas civiles privadas.

    Flujo (validado en vivo contra el sitio):
      home -> abrir modal de acceso -> Clave Poder Judicial (RUT sin DV + clave) o
      Clave Unica -> indexN.php -> Mis Causas -> pestana Civil (#civilTab / #tab3) ->
      activar el check "Filtros" (#filtroMisCauCiv) -> Rit (#tipoMisCauCiv) / Rol
      (#rolMisCauCiv) / Anio (#anhoMisCauCiv) -> Buscar (#btnConsultaMisCauCiv) ->
      abrir el detalle (lupa de la fila) -> modal #modalDetalleMisCauCivil.

    El modal de detalle tiene la MISMA estructura que el de la Consulta Unificada
    (table.table-titulos + select de cuaderno + pestanas Historia/Litigantes/
    Notificaciones/Escritos por Resolver/Exhortos), asi que la extraccion la hace
    `_extraer_detalle_de_modal`, igual que en el modo publico.

    Ambos metodos de login (Clave Poder Judicial y Clave Unica) estan validados
    end-to-end contra el sitio real.
    """

    METODO_CLAVE_PJUD = 1
    METODO_CLAVE_UNICA = 2

    MODAL_DETALLE = "modalDetalleMisCauCivil"

    # Selectores del area privada "Mis Causas" -> pestana de la competencia. La subclase
    # de Familia (`PjudSessionFamiliaPrivada`) los sobreescribe con los suyos; el resto
    # del flujo (login, filtros, apertura del detalle, extraccion del modal) es identico.
    NOMBRE_COMPETENCIA = "Civil"  # solo para logs
    TAB_COMPETENCIA = "civilTab"  # id del <a data-toggle="tab"> de la pestana
    PANE_COMPETENCIA = "tab3"  # id del <div> pane con la tabla de resultados
    CHECK_FILTROS = "filtroMisCauCiv"
    CAMPO_TIPO = "tipoMisCauCiv"
    CAMPO_ROL = "rolMisCauCiv"
    CAMPO_ANIO = "anhoMisCauCiv"
    CAMPO_ESTADO = "estadoCausaMisCauCiv"
    BTN_BUSCAR = "btnConsultaMisCauCiv"

    def __init__(self, rut: str, clave: str, metodo_login: int, headless: bool = False):
        self._rut = rut
        self._clave = clave
        self._metodo_login = metodo_login
        self._headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @property
    def _rut_sin_dv(self) -> str:
        return self._rut.split("-")[0].replace(".", "").strip()

    async def iniciar(self) -> None:
        logger.info(
            "Iniciando sesion Playwright privada (headless=%s, metodo_login=%s)",
            self._headless, self._metodo_login,
        )
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        await self._login()
        logger.info("Sesion Playwright privada lista")

    async def cerrar(self) -> None:
        logger.info("Cerrando sesion Playwright privada")
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # --- Login -----------------------------------------------------------------

    async def _login(self) -> None:
        page = self._page
        # `networkidle` no llega nunca (reCAPTCHA invisible mantiene la red ocupada).
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        if self._metodo_login == self.METODO_CLAVE_UNICA:
            await self._login_clave_unica()
        else:
            await self._login_clave_pjud()

        for _ in range(30):
            await page.wait_for_timeout(2000)
            if "indexN.php" in page.url:
                break

        if "indexN.php" not in page.url:
            raise LoginPrivadoError(
                f"Login no completado (URL actual: {page.url}); credenciales invalidas o flujo cambiado"
            )
        try:
            await page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
        # indexN.php sigue cargando su JS y secciones despues del redirect.
        await page.wait_for_timeout(4000)

    async def _login_clave_pjud(self) -> None:
        """Clave Poder Judicial: modal #segunda-clave-access en el mismo dominio. El RUT
        va SIN digito verificador (asi lo pide el campo). Los id de los inputs son
        aleatorios por carga, por eso se seleccionan por tipo dentro del modal."""
        page = self._page
        try:
            await page.evaluate("document.getElementById('btnSegClave').click()")
        except Exception as exc:
            raise LoginPrivadoError(f"No se pudo abrir el modal de Clave Poder Judicial: {exc}")
        await page.wait_for_selector("#segunda-clave-access.in", state="visible", timeout=15000)
        await page.locator("#segunda-clave-access input[type='text']:visible").first.fill(self._rut_sin_dv)
        await page.locator("#segunda-clave-access input[type='password']:visible").first.fill(self._clave)
        await page.click("#btnSegundaClaveIngresar")

    async def _login_clave_unica(self) -> None:
        """Clave Unica: el enlace dispara AutenticaCUnica() y redirige a
        accounts.claveunica.gob.cl (RUN con digito verificador)."""
        page = self._page
        try:
            await page.evaluate("AutenticaCUnica()")
        except Exception:
            try:
                await page.click("text=Clave Única", timeout=8000)
            except Exception as exc:
                raise LoginPrivadoError(f"No se pudo iniciar el flujo de Clave Unica: {exc}")
        try:
            await page.wait_for_url(re.compile(r"claveunica\.gob\.cl"), timeout=30000)
        except Exception:
            pass
        try:
            await page.wait_for_selector("#uname", state="visible", timeout=20000)
        except Exception:
            raise LoginPrivadoError("No aparecio el formulario de Clave Unica")
        await page.wait_for_timeout(1200)
        # ClaveUnica valida y codifica los campos con eventos por tecla: `fill()` no los
        # dispara (la clave queda sin codificar y el submit no avanza), hay que teclear.
        uname = page.locator("#uname")
        await uname.click()
        await uname.press_sequentially(self._rut, delay=60)
        pword = page.locator("#pword")
        await pword.click()
        await pword.press_sequentially(self._clave, delay=60)
        await page.wait_for_timeout(800)
        await page.click("#login-submit")

    # --- Busqueda en "Mis Causas" / pestana de la competencia -----------------

    async def _ir_a_mis_causas(self) -> None:
        page = self._page
        tab_sel = f"#{self.TAB_COMPETENCIA}"
        # La seccion "Mis Causas" (y con ella la pestana) carga por AJAX; se reintenta un
        # par de veces porque a veces el indexN todavia esta inicializando.
        for _ in range(4):
            if await page.query_selector(tab_sel):
                break
            try:
                await page.click("text=Mis Causas", timeout=6000)
            except Exception:
                try:
                    await page.evaluate("typeof misCausas === 'function' && misCausas()")
                except Exception:
                    pass
            await page.wait_for_timeout(4000)
        await page.wait_for_selector(tab_sel, timeout=15000)
        await page.click(tab_sel)
        await page.wait_for_timeout(2500)

    async def _activar_filtros(self) -> None:
        page = self._page
        # El checkbox de filtros (data-toggle="collapse") queda fuera de viewport; se
        # activa por JS si no esta ya marcado.
        try:
            ya = await page.evaluate(
                """(checkId) => {
                    const c = document.getElementById(checkId);
                    if (!c) return null;
                    if (!c.checked) c.click();
                    return true;
                }""",
                self.CHECK_FILTROS,
            )
            if ya is None:
                logger.warning(
                    "No se encontro el check #%s en la pestana %s", self.CHECK_FILTROS, self.NOMBRE_COMPETENCIA
                )
        except Exception:
            logger.exception("Error al activar el check de filtros")
        await page.wait_for_timeout(1200)

    async def buscar_y_extraer_privada(
        self, tipo: str, rol, anio, progreso=None, tribunal_nombre: str | None = None
    ) -> dict:
        """Busca la causa privada por Rit / Rol / Anio dentro de Mis Causas -> pestana de
        la competencia y extrae cabecera + cuadernos (mismo modal que la Consulta
        Unificada).

        `tribunal_nombre` (opcional): si se entrega, se verifica que el detalle abierto
        sea de ese tribunal. Mis Causas no permite filtrar por tribunal, asi que si la
        misma RIT existe en dos tribunales del usuario esta es la unica salvaguarda."""
        page = self._page
        self._progreso = progreso
        logger.info("Buscando causa privada %s %s-%s-%s", self.NOMBRE_COMPETENCIA, tipo, rol, anio)
        try:
            await self._reportar("Buscando la causa en Mis Causas")
            await self._ir_a_mis_causas()
            await self._activar_filtros()

            try:
                await page.select_option(f"#{self.CAMPO_TIPO}", value=tipo)
            except Exception:
                logger.warning("No se pudo seleccionar el tipo '%s' en #%s", tipo, self.CAMPO_TIPO)
            await page.fill(f"#{self.CAMPO_ROL}", str(rol))
            await page.fill(f"#{self.CAMPO_ANIO}", str(anio))
            # El filtro de Estado (multiple) viene por defecto solo en "Tramitacion".
            # Limpiarlo no basta: hay estados que igual quedan fuera del resultado
            # (p. ej. "Tramitacion pend." en Familia). Se seleccionan TODAS las
            # opciones para no excluir ninguna causa.
            try:
                valores_estado = await page.eval_on_selector_all(
                    f"#{self.CAMPO_ESTADO} option",
                    "els => els.map(o => o.value)",
                )
                if valores_estado:
                    await page.select_option(f"#{self.CAMPO_ESTADO}", valores_estado)
                else:
                    await page.select_option(f"#{self.CAMPO_ESTADO}", [])
            except Exception:
                pass

            await page.click(f"#{self.BTN_BUSCAR}")
            await page.wait_for_timeout(3500)

            objetivo = f"{tipo}-{rol}-{anio}"
            abierta = await page.evaluate(
                """([objetivo, paneId]) => {
                    const norm = s => (s || '').replace(/\\s+/g, '').toUpperCase();
                    const cell = Array.from(document.querySelectorAll('#' + paneId + ' td'))
                        .find(td => norm(td.textContent).includes(norm(objetivo)));
                    if (!cell) return null;
                    const row = cell.closest('tr');
                    const clickable = row.querySelector('a,button,i,img,span') || row.querySelector('td');
                    clickable.click();
                    return true;
                }""",
                [objetivo, self.PANE_COMPETENCIA],
            )
            if abierta is None:
                logger.info("Causa privada %s no encontrada en Mis Causas", objetivo)
                return {"encontrada": False}

            try:
                await page.wait_for_selector(f"#{self.MODAL_DETALLE}.in", state="visible", timeout=15000)
            except Exception:
                return {"encontrada": True, "error": "No se pudo abrir el detalle de la causa privada"}
            await page.wait_for_timeout(800)

            detalle = await self._extraer_detalle_de_modal(self.MODAL_DETALLE)

            # En Mis Causas la lista ya viene acotada a las causas del usuario y no se
            # puede filtrar por tribunal. Si el nombre no coincide con el del catalogo se
            # avisa fuerte, pero NO se aborta: el catalogo puede tener otro formato de
            # nombre y un falso positivo bloquearia el sync de la causa por completo.
            trib_detalle = (detalle.get("cabecera", {}).get("campos", {}) or {}).get("Tribunal", "")
            if tribunal_nombre and trib_detalle and (
                _normalizar_tribunal(tribunal_nombre) != _normalizar_tribunal(trib_detalle)
            ):
                logger.warning(
                    "Causa privada %s: el detalle abierto dice tribunal %r y el catalogo %r "
                    "(se continua igual; revisar si la RIT existe en dos tribunales del usuario)",
                    objetivo, trib_detalle, tribunal_nombre,
                )

            return {"encontrada": True, **detalle}
        finally:
            self._progreso = None
            await page.wait_for_timeout(PAUSA_ENTRE_CONSULTAS_MS)


class PjudSessionFamiliaPrivada(PjudSessionPrivada):
    """Igual que `PjudSessionPrivada` pero para la pestana "Familia" de Mis Causas.

    Login (`_login` / Clave PJ / Clave Unica), activacion de filtros, apertura del
    detalle y extraccion del modal (`_extraer_detalle_de_modal`) son identicos: solo
    cambian los ids de la pestana, los campos de filtro y el modal de detalle. Familia
    es SIEMPRE cuaderno unico, asi que `_extraer_detalle_de_modal` cae en la rama
    "Principal" (no hay <select> de cuadernos).

    Selectores confirmados contra `ejemplos/causa familia/*.html` (Mis Causas -> pestana
    "Familia" #tab7). La pestana de secciones "Movimientos" hace de "Historia".
    """

    NOMBRE_COMPETENCIA = "Familia"
    TAB_COMPETENCIA = "familiaTab"
    PANE_COMPETENCIA = "tab7"
    CHECK_FILTROS = "filtroMisCauFam"
    CAMPO_TIPO = "tipoMisCauFam"
    CAMPO_ROL = "rolMisCauFam"
    CAMPO_ANIO = "anhoMisCauFam"
    CAMPO_ESTADO = "estadoCausaMisCauFam"
    BTN_BUSCAR = "btnConsultaMisCauFam"
    MODAL_DETALLE = "modalDetalleMisCauFamilia"
    # Carpetas de la columna "Anexos" de Movimientos: `modalAnexoEscritoFamilia`
    # (Anexo del Escrito -- cols Folio/Doc./Fecha/Nombre Documento/Observación, descarga
    # GET docAnexoEscritoFamilia.php) y `modalSIIFamilia` (Documentos SII -- cols
    # Formulario/Rut Litigante/Nombre Litigante/Fecha Recepción, descarga POST
    # docFamiliaSii.php). Validado en vivo con C-2973-2025.
    MODALES_ANEXO_HISTORIA = ("modalAnexoEscritoFamilia", "modalSIIFamilia")
    PREFIJOS_HISTORIA = ("historia", "movimiento")
    # Popup de la columna "Georeferencia" de Movimientos: pestanas Mapas/Imagenes/Videos
    # (Videos aun sin ejemplos, no se scrapea). No verificado en vivo en este repo.
    MODAL_GEOREFERENCIA = "modalGeoReferenciaFamilia"


class PjudSessionLaboralAsync(PjudSessionAsync):
    """Igual que `PjudSessionAsync` (Consulta Unificada publica) pero con los ids de
    popup propios de Laboral en vez de los de Civil (default de `_PjudModalScraper`).

    Selectores confirmados contra `ejemplos/causa laboral/*.html` (Consulta Unificada
    publica, causa O-200-2025 del Juzgado de Letras del Trabajo de Castro): modal de
    detalle `modalDetalleLaboral`, pestanas Movimientos (`movimientoLab`) / Litigantes
    (`litigantesLab`) / Notificaciones (`notificacionesLab`) / Diligencias
    (`diligenciasLab`) / Liquidacion (`liquidacionLab`) / Materias (`materiasLab`) /
    Escritos Pendientes (`EscPendLab`). La cabecera (`table.table-titulos`) ya la
    extrae generico `JS_EXTRAER_CABECERA`: "Texto Demanda" y "Listado de Archivos de
    Audios de Audiencia" caen solas en `cabecera.submodales` (icono con `<strong>` +
    `data-toggle="modal"` sin texto propio), "Ebook" y "Certificado de Envío" en
    `cabecera.descargas` (forms GET) -- ver `worker/sync_laboral.py`.
    """

    # `modalAnexoEscritoLaboral` ("Anexo escrito", columna "Anexos" de Movimientos) y
    # `modalAnexoEscritoPend` (columna "Anexo" de Escritos Pendientes, mismo patron que
    # "Escritos por Resolver" de Civil). CONFIRMADO en vivo (2026-09-21, causa O-692-2019,
    # `modalAnexoEscritoLaboral`): columnas reales Doc./Folio/Fecha/Referencia, todas
    # <td> (sin Observación) -- `modalAnexoEscritoPend` se asume igual por analogia (no
    # confirmado, la causa de prueba no tenia escritos pendientes). Aca el bug real era
    # solo de nombre de columna ("Referencia", no "Nombre Documento" como en Familia).
    # Ver mas abajo (`Listado de Archivos de Audios de Audiencia`) por un bug DISTINTO
    # y mas grave en el extractor generico: ese popup tiene la primera celda ("Nro")
    # como <th>, lo que desalineaba TODAS las columnas siguientes en 1 posicion.
    MODALES_ANEXO_HISTORIA = ("modalAnexoEscritoLaboral", "modalAnexoEscritoPend")
    PREFIJOS_HISTORIA = ("movimiento",)
    MODAL_GEOREFERENCIA = "modalGeoReferenciaLaboral"
    PREFIJOS_ANEXO_POPUP_EXTRA = ("escritos pendientes",)
    MODALES_DESCARGA_CLICK = frozenset({"modalListadoAudioLaboral"})


class PjudSessionLaboralPrivada(PjudSessionPrivada):
    """Igual que `PjudSessionPrivada` pero para la pestana "Laboral" de Mis Causas.

    A diferencia de Familia, Laboral NO es siempre privada (ver
    `api/laboral/router.py`): este modo solo se usa cuando el request de
    sincronizar_laboral trae rut/clave/metodo_login.

    CONFIRMADO en vivo (2026-09-18 y 2026-09-21, causa O-692-2019, login Clave Unica):
    todos los ids de abajo son correctos EXCEPTO `CAMPO_TIPO`, que tenia un typo de
    mayuscula -- el select real es `tipoMisCaulab` ("lab" en minuscula), no
    `tipoMisCauLab` como el resto de los campos (`rolMisCauLab`/`anhoMisCauLab`/etc. si
    usan "Lab" con mayuscula). `select_option` sobre un id inexistente solo logueaba un
    warning y seguia sin aplicar el filtro de tipo -- no rompia la busqueda pero
    devolvia resultados sin filtrar por tipo de causa. La extraccion del modal una vez
    abierto (`_extraer_detalle_de_modal`) reusa el mismo DOM que la Consulta Unificada,
    asi que los ids de popups de `PjudSessionLaboralAsync` (Anexos/Georeferencia)
    tambien estan confirmados.
    """

    NOMBRE_COMPETENCIA = "Laboral"
    TAB_COMPETENCIA = "laboralTab"
    PANE_COMPETENCIA = "tab4"
    CHECK_FILTROS = "filtroMisCauLab"
    CAMPO_TIPO = "tipoMisCaulab"
    CAMPO_ROL = "rolMisCauLab"
    CAMPO_ANIO = "anhoMisCauLab"
    CAMPO_ESTADO = "estadoCausaMisCauLab"
    BTN_BUSCAR = "btnConsultaMisCauLab"
    MODAL_DETALLE = "modalDetalleMisCauLaboral"

    MODALES_ANEXO_HISTORIA = ("modalAnexoEscritoLaboral", "modalAnexoEscritoPend")
    PREFIJOS_HISTORIA = ("movimiento",)
    MODAL_GEOREFERENCIA = "modalGeoReferenciaLaboral"
    PREFIJOS_ANEXO_POPUP_EXTRA = ("escritos pendientes",)
    MODALES_DESCARGA_CLICK = frozenset({"modalListadoAudioLaboral"})


class PjudSessionCobranzaAsync(PjudSessionAsync):
    """Igual que `PjudSessionAsync` (Consulta Unificada publica) pero con los ids de
    popup propios de Cobranza en vez de los de Civil (default de `_PjudModalScraper`).

    Selectores CONFIRMADOS en vivo contra `ejemplos/causa cobranza/*.html` (Consulta
    Unificada publica, causas A-1-2025 del 1o Juzgado de Letras de Quillota y C-10-2025
    del Jdo. de Letras de San Vicente): modal de detalle `modalDetalleCobranza`,
    pestanas Historia (`historiaCob`) / Litigantes (`litigantesCob`) / Notificaciones
    (`notificacionCob`) / Diligencias (`diligenciaCob`) / Liquidacion (`liquidacionCob`).
    Hay ademas una pestana "Deuda Act." (`deudaCob`) deshabilitada en el UI (su `<li>`
    esta comentado) y sin contraparte en Solicitud Cobranza.md -- no se scrapea.

    La cabecera (`table.table-titulos`) la extrae generico `JS_EXTRAER_CABECERA`: "Doc.
    Demanda" y "Ebook" caen en `cabecera.descargas` (forms GET); "Titulo Ejec." y
    "Certificado de Envío" son iconos deshabilitados cuando no hay documento (mismo
    patron, forms GET cuando si lo hay -- no confirmado en vivo con dato real, solo por
    analogia con doc_demanda/ebook); "Anexos de la causa", "Información notificaciones
    receptor" y "Documentos Laboral" caen en `cabecera.submodales` (icono con `<strong>`
    + `data-toggle="modal"` sin texto propio) -- ver `worker/sync_cobranza.py`.
    "Documentos Exhorto" y "Causas Acumuladas" tambien son campos de cabecera (icono
    deshabilitado en los 2 ejemplos disponibles, sin Documentos/Causas asociados) pero
    no estan en Solicitud Cobranza.md y no se scrapean -- estructura desconocida.

    Cobranza puede tener varios cuadernos (selector "Historia Causa Cuaderno",
    `#selCuadernoCob` -- ej. "1 - principal" / "2 - Apremio Ejecutivo Obligación de
    Dar", solo confirmado con 1 opcion en los ejemplos disponibles): lo detecta el
    mismo mecanismo generico de `_extraer_detalle_de_modal` (busca el `<select>` del
    modal), sin cambios propios.
    """

    # `modalAnexoEscritoCobranza` ("Anexo excrito" [sic], columna "Anexo" de Historia):
    # confirmado que existe y su trigger (icono con `data-toggle="modal"`), pero su
    # contenido no aparecio abierto en ningun ejemplo disponible -- se asume la misma
    # forma Doc./Fecha/Referencia que "Anexo de la Causa" y "Documentos Laboral"
    # (confirmadas ambas en vivo), no confirmada punto por punto.
    MODALES_ANEXO_HISTORIA = ("modalAnexoEscritoCobranza",)
    PREFIJOS_HISTORIA = ("historia",)
    MODAL_GEOREFERENCIA = "modalGeoReferenciaCobranza"
    # Cobranza no tiene Exhortos/Escritos por Resolver como Civil ni Escritos Pendientes
    # como Laboral -- solo Historia usa columna "Anexo" con popup.
    PREFIJOS_ANEXO_POPUP_EXTRA = ()


class PjudSessionCobranzaPrivada(PjudSessionPrivada):
    """Igual que `PjudSessionPrivada` pero para la pestana "Cobranza" de Mis Causas.

    NO CONFIRMADO EN VIVO (a diferencia de `PjudSessionCobranzaAsync`): no hay ejemplo
    disponible de "Mis Causas" -> Cobranza (`ejemplos/causa cobranza/*.html` son todos
    de la Consulta Unificada publica). Los ids de abajo son una extrapolacion por
    analogia con Civil/Laboral/Familia (mismo patron "Mis Causas..." + sufijo de
    competencia) y con el propio DOM publico de Cobranza (sufijo "Cob" -- ver
    `selCuadernoCob`/`historiaCob`/etc. en `PjudSessionCobranzaAsync`):

    - `PANE_COMPETENCIA = "tab6"`: en Civil/Laboral el numero de tab coincide con el
      codigo de competencia de la Consulta Unificada (civil=3->tab3, laboral=4->tab4;
      `COMPETENCIAS` en este modulo); Cobranza es codigo 6 -> tab6.
    - El resto sigue el patron "Mis Causas..." + "Cob" (mismo sufijo que el DOM publico).

    Revisar contra el sitio real (como se hizo con Laboral, que tenia un typo de
    mayuscula en `CAMPO_TIPO`) antes de confiar en sincronizaciones privadas de Cobranza.
    """

    NOMBRE_COMPETENCIA = "Cobranza"
    TAB_COMPETENCIA = "cobranzaTab"
    PANE_COMPETENCIA = "tab6"
    CHECK_FILTROS = "filtroMisCauCob"
    CAMPO_TIPO = "tipoMisCauCob"
    CAMPO_ROL = "rolMisCauCob"
    CAMPO_ANIO = "anhoMisCauCob"
    CAMPO_ESTADO = "estadoCausaMisCauCob"
    BTN_BUSCAR = "btnConsultaMisCauCob"
    MODAL_DETALLE = "modalDetalleMisCauCobranza"

    MODALES_ANEXO_HISTORIA = ("modalAnexoEscritoCobranza",)
    PREFIJOS_HISTORIA = ("historia",)
    MODAL_GEOREFERENCIA = "modalGeoReferenciaCobranza"
    PREFIJOS_ANEXO_POPUP_EXTRA = ()
