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
# especifica (`enlaces`).
JS_EXTRAER_FILAS_CON_ENLACES = """tables => tables.map(t => {
    const headerCells = t.querySelectorAll('thead th');
    const headers = (headerCells.length ? Array.from(headerCells) : Array.from(t.querySelectorAll('tr:first-child th')))
        .map(h => h.textContent.trim());
    const bodyRows = t.querySelectorAll('tbody tr').length ? t.querySelectorAll('tbody tr') : t.querySelectorAll('tr');
    const filas = Array.from(bodyRows).map(tr => {
        const celdas = Array.from(tr.querySelectorAll('td'));
        if (celdas.length === 0) return null;
        const valores = {};
        const enlaces = {};
        const popups = {};
        celdas.forEach((td, i) => {
            const header = headers[i] || ('col' + i);
            valores[header] = td.textContent.trim();
            const urls = [];
            Array.from(td.querySelectorAll('form')).forEach(form => {
                if ((form.getAttribute('method') || '').toLowerCase() !== 'get') return;
                const input = form.querySelector('input');
                const action = form.getAttribute('action');
                if (!input || !action) return;
                const url = new URL(action, location.href);
                url.searchParams.set(input.name, input.value);
                urls.push(url.toString());
            });
            Array.from(td.querySelectorAll('a[href]')).forEach(a => {
                const href = a.getAttribute('href');
                if (!href || href.toLowerCase().startsWith('javascript:')) return;
                if (href.startsWith('#')) {
                    // Carpeta que abre un popup (p. ej. #modalAnexoSolicitudCivil en Historia).
                    if (a.getAttribute('data-toggle') === 'modal') {
                        (popups[header] = popups[header] || []).push(href);
                    }
                    return;
                }
                urls.push(new URL(href, location.href).toString());
            });
            if (urls.length) enlaces[header] = urls;
        });
        return {valores, enlaces, popups};
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
                submodales.push({label, target: modalLink.getAttribute('href')});
            } else if (select) {
                // el select de cuaderno se procesa aparte
            } else if (label) {
                const clone = td.cloneNode(true);
                const strongClone = clone.querySelector('strong');
                if (strongClone) strongClone.remove();
                campos[label] = clone.textContent.replace(/\\s+/g, ' ').trim();
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


def _es_seccion_historia(nombre: str) -> bool:
    return (nombre or "").strip().lower().startswith("historia")


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
                return None
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
            if _es_seccion_historia(tab["nombre"]):
                await self._extraer_anexos_popup_historia(pane_id, seccion)
            secciones[tab["nombre"]] = seccion
        return secciones

    async def _extraer_anexos_popup_historia(self, pane_id: str, seccion: dict) -> None:
        """En Historia la columna "Anexo" puede ser una carpeta que abre el popup
        `#modalAnexoSolicitudCivil` (carga por AJAX una tabla Doc./Fecha/Referencia).
        Por cada fila que la tenga, abre el popup, vuelca sus filas en
        `fila["anexos_popup"] = [{"doc": url|None, "fecha": str, "referencia": str}, ...]`
        y resume el contenido en `valores["Anexo"]` para que el hash de la fila (worker)
        sea sensible a cambios en los anexos."""
        page = self._page
        filas = seccion.get("filas", [])
        for idx, fila in enumerate(filas):
            popups = fila.get("popups") or {}
            col_anexo = next(
                (col for col, lst in popups.items() if "#modalAnexoSolicitudCivil" in lst), None
            )
            if col_anexo is None:
                continue
            # Localiza el <a> de ESTA fila (mismo criterio de filas que
            # JS_EXTRAER_FILAS_CON_ENLACES: filas de tbody con >= 1 <td>).
            clicked = await page.evaluate(
                """([paneId, idx]) => {
                    const cont = document.getElementById(paneId);
                    const t = cont && cont.querySelector('table');
                    if (!t) return false;
                    const rows = t.querySelectorAll('tbody tr').length
                        ? t.querySelectorAll('tbody tr') : t.querySelectorAll('tr');
                    const conCeldas = Array.from(rows).filter(tr => tr.querySelectorAll('td').length);
                    const tr = conCeldas[idx];
                    if (!tr) return false;
                    const a = tr.querySelector('a[data-toggle="modal"][href="#modalAnexoSolicitudCivil"]');
                    if (!a) return false;
                    a.click();
                    return true;
                }""",
                [pane_id, idx],
            )
            if not clicked:
                continue
            await page.wait_for_timeout(1600)  # el contenido del popup carga por AJAX
            tablas = await self._extraer_filas_con_enlaces("#modalAnexoSolicitudCivil")
            popup = tablas[0] if tablas else {"filas": []}
            anexos = []
            for pf in popup.get("filas", []):
                v = pf.get("valores", {})
                docs = (pf.get("enlaces") or {}).get("Doc.") or []
                anexos.append(
                    {
                        "doc": docs[0] if docs else None,
                        "fecha": v.get("Fecha"),
                        "referencia": v.get("Referencia"),
                    }
                )
            fila["anexos_popup"] = anexos
            # Resume el popup en la celda de origen para que el hash de la fila (worker)
            # detecte altas/bajas de anexos en re-sincronizaciones.
            fila.setdefault("valores", {})[col_anexo] = " | ".join(
                f"{a.get('fecha') or ''}~{a.get('referencia') or ''}" for a in anexos
            )
            await page.evaluate(
                """() => {
                    const m = document.getElementById('modalAnexoSolicitudCivil');
                    if (!m) return;
                    const c = m.querySelector('.close, button.close, [data-dismiss="modal"]');
                    if (c) c.click();
                }"""
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
            tabla = await self._procesar_submodal(modal_id, sub["target"])
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
                secciones = await self._extraer_cuaderno_actual(modal_id, nombre_limpio)
                cuadernos.append({"numero": numero, "nombre": nombre_limpio, "secciones": secciones})
        else:
            secciones = await self._extraer_cuaderno_actual(modal_id, "Principal")
            cuadernos.append({"numero": 1, "nombre": "Principal", "secciones": secciones})

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
            await page.wait_for_timeout(1500)

            objetivo = f"{tipo}-{rol}-{anio}"
            seleccion = await page.evaluate(
                JS_SELECCIONAR_FILA_RIT, {"objetivo": objetivo, "tribunal": tribunal_esperado}
            )

            if seleccion["estado"] == "no_encontrada":
                logger.info("Causa %s-%s-%s no encontrada", tipo, rol, anio)
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

    # --- Busqueda en "Mis Causas" / pestana "Civil" ---------------------------

    async def _ir_a_mis_causas_civil(self) -> None:
        page = self._page
        # La seccion "Mis Causas" (y con ella la pestana #civilTab) carga por AJAX; se
        # reintenta un par de veces porque a veces el indexN todavia esta inicializando.
        for intento in range(4):
            if await page.query_selector("#civilTab"):
                break
            try:
                await page.click("text=Mis Causas", timeout=6000)
            except Exception:
                try:
                    await page.evaluate("typeof misCausas === 'function' && misCausas()")
                except Exception:
                    pass
            await page.wait_for_timeout(4000)
        await page.wait_for_selector("#civilTab", timeout=15000)
        await page.click("#civilTab")
        await page.wait_for_timeout(2500)

    async def _activar_filtros(self) -> None:
        page = self._page
        # #filtroMisCauCiv es un checkbox (data-toggle="collapse" -> #collFiltrosCiv) que
        # queda fuera de viewport; se activa por JS si no esta ya marcado.
        try:
            ya = await page.evaluate(
                """() => {
                    const c = document.getElementById('filtroMisCauCiv');
                    if (!c) return null;
                    if (!c.checked) c.click();
                    return true;
                }"""
            )
            if ya is None:
                logger.warning("No se encontro el check #filtroMisCauCiv en la pestana Civil")
        except Exception:
            logger.exception("Error al activar el check de filtros")
        await page.wait_for_timeout(1200)

    async def buscar_y_extraer_privada(
        self, tipo: str, rol, anio, progreso=None, tribunal_nombre: str | None = None
    ) -> dict:
        """Busca la causa privada por Rit / Rol / Anio dentro de Mis Causas -> Civil y
        extrae cabecera + cuadernos (mismo modal que la Consulta Unificada).

        `tribunal_nombre` (opcional): si se entrega, se verifica que el detalle abierto
        sea de ese tribunal. Mis Causas no permite filtrar por tribunal, asi que si la
        misma RIT existe en dos tribunales del usuario esta es la unica salvaguarda."""
        page = self._page
        self._progreso = progreso
        logger.info("Buscando causa privada %s-%s-%s", tipo, rol, anio)
        try:
            await self._reportar("Buscando la causa en Mis Causas")
            await self._ir_a_mis_causas_civil()
            await self._activar_filtros()

            try:
                await page.select_option("#tipoMisCauCiv", value=tipo)
            except Exception:
                logger.warning("No se pudo seleccionar el tipo '%s' en #tipoMisCauCiv", tipo)
            await page.fill("#rolMisCauCiv", str(rol))
            await page.fill("#anhoMisCauCiv", str(anio))
            # El filtro de Estado viene por defecto en "Tramitacion"; se limpia para no
            # excluir causas en otros estados (archivadas, concluidas, etc.).
            try:
                await page.select_option("#estadoCausaMisCauCiv", [])
            except Exception:
                pass

            await page.click("#btnConsultaMisCauCiv")
            await page.wait_for_timeout(3500)

            objetivo = f"{tipo}-{rol}-{anio}"
            abierta = await page.evaluate(
                """(objetivo) => {
                    const norm = s => (s || '').replace(/\\s+/g, '').toUpperCase();
                    const cell = Array.from(document.querySelectorAll('#tab3 td'))
                        .find(td => norm(td.textContent).includes(norm(objetivo)));
                    if (!cell) return null;
                    const row = cell.closest('tr');
                    const clickable = row.querySelector('a,button,i,img,span') || row.querySelector('td');
                    clickable.click();
                    return true;
                }""",
                objetivo,
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
