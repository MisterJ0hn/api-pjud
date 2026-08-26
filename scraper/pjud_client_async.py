"""Cliente Playwright (API async) para la Consulta Unificada publica de PJUD, usado por
el worker de sincronizacion. Es el equivalente async de `scraper/pjud_client.py` (que se
mantiene intacto y sin cambios para la app Flask legacy) con dos diferencias de fondo:

1. Extraccion combinada por fila: en vez de extraer el texto de las tablas y resolver los
   documentos descargables en dos recorridos DOM separados (como hace el cliente sync),
   aca se hace en un solo recorrido por `<tr>`, devolviendo por cada celda tanto su texto
   como los enlaces/descargas que contiene especificamente esa celda. Esto es necesario
   para poder vincular, por ejemplo, el documento de un folio de Historia con ESE folio
   (y no con la fila siguiente), que es algo que el cliente sync no garantiza hoy.

2. No decide nombres de archivo ni escribe en disco: solo entrega URLs de PJUD (validas
   solo dentro de la sesion actual) y expone `descargar_bytes()` para bajarlas bajo
   demanda. La decision de que' es idempotente, que' ya existe y con que' nombre se
   guarda es responsabilidad del worker (ve `worker/sync_civil.py`), que es quien conoce
   el estado ya persistido en Postgres.
"""

import logging
import re

from playwright.async_api import async_playwright

logger = logging.getLogger("pjud.scraper.async")

BASE_URL = "https://oficinajudicialvirtual.pjud.cl/includes/sesion-consultaunificada.php"

COMPETENCIAS = {"civil": "3", "laboral": "4", "cobranza": "6"}

PAUSA_ENTRE_CONSULTAS_MS = 4000

# Extrae, por cada tabla, sus headers y sus filas -- cada fila trae tanto el texto de
# cada celda (`valores`) como los enlaces/descargas resueltos DENTRO de esa celda
# especifica (`enlaces`). Reemplaza a JS_EXTRAER_TABLAS + JS_RESOLVER_DESCARGAS del
# cliente sync (que resolvian descargas a nivel de todo el contenedor, no por celda).
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
                if (!href || href.startsWith('#') || href.toLowerCase().startsWith('javascript:')) return;
                urls.push(new URL(href, location.href).toString());
            });
            if (urls.length) enlaces[header] = urls;
        });
        return {valores, enlaces};
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


class CausaNoEncontrada(Exception):
    pass


class PjudSessionAsync:
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

    async def descargar_bytes(self, url: str) -> tuple[str, bytes] | None:
        """Descarga una URL de PJUD y valida que sea realmente un documento (el sitio
        responde con placeholders HTML/texto o errores de Oracle cuando el tramite no
        tiene un documento real asociado). Devuelve (content_type, bytes) o None."""
        try:
            resp = await self._context.request.get(url)
            if not resp.ok:
                logger.warning("Descarga fallida (HTTP %s) para %s", resp.status, url)
                return None

            content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            cuerpo = await resp.body()

            if content_type in ("text/html", "text/plain", ""):
                return None
            if content_type == "application/pdf" and not cuerpo.startswith(b"%PDF"):
                return None
            if cuerpo[:200].lstrip().startswith(b"ORA-") or b"no data found" in cuerpo[:200]:
                return None

            return content_type, cuerpo
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
        await page.wait_for_timeout(900)
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

    async def _extraer_cuaderno_actual(self, modal_id: str) -> dict:
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
            try:
                await page.click(f'#{modal_id} a[href="{href}"]')
            except Exception:
                continue
            await page.wait_for_timeout(500)
            pane_id = href[1:]
            tablas = await self._extraer_filas_con_enlaces(f"#{pane_id}")
            secciones[tab["nombre"]] = tablas[0] if tablas else {"headers": [], "filas": []}
        return secciones

    async def get_tribunales(self, competencia: str, corte: str) -> list[dict]:
        await self._seleccionar_competencia_corte(competencia, corte)
        options = await self._page.eval_on_selector_all(
            "#conTribunal option", "els => els.map(e => ({value: e.value, label: e.textContent.trim()}))"
        )
        return [o for o in options if o["value"] not in ("", "0")]

    async def buscar_y_extraer(
        self, competencia: str, corte: str, tribunal: str, tipo: str, rol, anio
    ) -> dict:
        """Reproduce la busqueda humana de la causa y extrae cabecera + cuadernos. No
        descarga ningun documento (eso lo decide el worker, ver modulo docstring)."""
        page = self._page
        logger.info(
            "Buscando causa %s-%s-%s (competencia=%s, corte=%s, tribunal=%s)",
            tipo, rol, anio, competencia, corte, tribunal,
        )
        try:
            await self._seleccionar_competencia_corte(competencia, corte)
            await page.select_option("#conTribunal", tribunal)
            await page.wait_for_timeout(300)
            await page.select_option("#conTipoCausa", tipo)
            await page.fill("#conRolCausa", str(rol))
            await page.fill("#conEraCausa", str(anio))
            await page.click('#busRit button[type="submit"]')
            await page.wait_for_timeout(1500)

            objetivo = f"{tipo}-{rol}-{anio}"
            encontrada = await page.evaluate(
                """(objetivo) => {
                    const cell = Array.from(document.querySelectorAll('#busRit td'))
                        .find(td => td.textContent.trim() === objetivo);
                    if (!cell) return null;
                    const row = cell.closest('tr');
                    const firstTd = row.querySelector('td');
                    const clickable = firstTd.querySelector('a,button,i,span') || firstTd;
                    clickable.click();
                    return true;
                }""",
                objetivo,
            )

            if encontrada is None:
                logger.info("Causa %s-%s-%s no encontrada", tipo, rol, anio)
                return {"encontrada": False}

            await page.wait_for_timeout(700)
            modal_id = await page.evaluate(
                """() => {
                    const modals = Array.from(document.querySelectorAll('.modal.in'));
                    const visible = modals.find(m => m.offsetParent !== null);
                    return visible ? visible.id : (modals.length ? modals[modals.length - 1].id : null);
                }"""
            )
            if not modal_id:
                return {"encontrada": True, "error": "No se pudo abrir el detalle de la causa"}

            cabecera_info = await page.evaluate(JS_EXTRAER_CABECERA, modal_id)
            campos = cabecera_info.get("campos", {})
            descargas = cabecera_info.get("descargas", [])

            submodales = {}
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
                    secciones = await self._extraer_cuaderno_actual(modal_id)
                    nombre_limpio = re.sub(r"^\d+\s*-\s*", "", etiqueta).strip() or etiqueta
                    cuadernos.append({"numero": numero, "nombre": nombre_limpio, "secciones": secciones})
            else:
                secciones = await self._extraer_cuaderno_actual(modal_id)
                cuadernos.append({"numero": 1, "nombre": "Principal", "secciones": secciones})

            await page.evaluate(
                """(modalId) => {
                    const modal = document.getElementById(modalId);
                    const cerrar = modal.querySelector('.close, button.close, [data-dismiss="modal"]');
                    if (cerrar) cerrar.click();
                }""",
                modal_id,
            )
            await page.wait_for_timeout(300)

            return {
                "encontrada": True,
                "cabecera": {"campos": campos, "descargas": descargas, "submodales": submodales},
                "cuadernos": cuadernos,
            }
        finally:
            await page.wait_for_timeout(PAUSA_ENTRE_CONSULTAS_MS)
