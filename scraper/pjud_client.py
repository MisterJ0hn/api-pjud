"""Cliente Playwright para la Consulta Unificada publica de la Oficina Judicial Virtual (PJUD).

No se llama a los endpoints internos (combosJSON/*.php) directamente: el sitio los
rechaza si no vienen acompanados del resto del contexto de la pagina (referer,
sesion, reCAPTCHA v3, etc.). En su lugar, este cliente mantiene una pagina real
abierta con Playwright y reproduce las mismas interacciones que haria una persona
(seleccionar combos, escribir Rol/Anio, hacer clic en Buscar y en la causa
encontrada), dejando que el propio JavaScript del sitio se ejecute con normalidad.
"""

import logging
import mimetypes
import os
import re
import threading

from playwright.sync_api import sync_playwright

logger = logging.getLogger("pjud.scraper")

BASE_URL = "https://oficinajudicialvirtual.pjud.cl/includes/sesion-consultaunificada.php"

COMPETENCIAS = {
    "civil": "3",
    "laboral": "4",
    "cobranza": "6",
}

LIBRO_TIPO = {
    "civil": ["C", "V", "E", "A", "F", "I"],
    "laboral": ["O", "T", "M", "E", "S", "U", "V", "I"],
    "cobranza": ["A", "C", "D", "E", "J", "L", "P", "R"],
}

# Cortes de Apelaciones: lista fija (no depende de la competencia), capturada en vivo.
CORTES = [
    {"value": "10", "label": "C.A. de Arica"},
    {"value": "11", "label": "C.A. de Iquique"},
    {"value": "15", "label": "C.A. de Antofagasta"},
    {"value": "20", "label": "C.A. de Copiapó"},
    {"value": "25", "label": "C.A. de La Serena"},
    {"value": "30", "label": "C.A. de Valparaíso"},
    {"value": "35", "label": "C.A. de Rancagua"},
    {"value": "40", "label": "C.A. de Talca"},
    {"value": "45", "label": "C.A. de Chillan"},
    {"value": "46", "label": "C.A. de Concepción"},
    {"value": "50", "label": "C.A. de Temuco"},
    {"value": "55", "label": "C.A. de Valdivia"},
    {"value": "56", "label": "C.A. de Puerto Montt"},
    {"value": "60", "label": "C.A. de Coyhaique"},
    {"value": "61", "label": "C.A. de Punta Arenas"},
    {"value": "90", "label": "C.A. de Santiago"},
    {"value": "91", "label": "C.A. de San Miguel"},
]

# Pausa minima entre consultas para no golpear el sitio con frecuencia alta
# (el robots.txt del sitio pide no ser rastreado; este cliente esta pensado
# para consultas puntuales, no para recorrer el sitio en volumen).
PAUSA_ENTRE_CONSULTAS_MS = 4000

# --- Fragmentos de JS reutilizados -----------------------------------------

# Convierte cada <table> encontrada en {headers, filas}.
JS_EXTRAER_TABLAS = """tables => tables.map(t => {
    const headerCells = t.querySelectorAll('thead th');
    const headers = (headerCells.length ? Array.from(headerCells) : Array.from(t.querySelectorAll('tr:first-child th')))
        .map(h => h.textContent.trim());
    const bodyRows = t.querySelectorAll('tbody tr').length
        ? t.querySelectorAll('tbody tr')
        : t.querySelectorAll('tr');
    const filas = Array.from(bodyRows)
        .map(tr => Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim()))
        .filter(fila => fila.length > 0);
    return {headers, filas};
})"""

# Dentro de un contenedor (pestana o sub-modal), encuentra archivos descargables:
# - formularios GET con un input oculto (patron usado por PJUD para documentos/PDFs)
# - enlaces directos a un archivo (href real, no "#" ni "javascript:")
# - <audio>/<video>/<source> con src (audiencias grabadas)
JS_RESOLVER_DESCARGAS = """(root) => {
    const resultados = [];
    const vistos = new Set();
    Array.from(root.querySelectorAll('form')).forEach(form => {
        if ((form.getAttribute('method') || '').toLowerCase() !== 'get') return;
        const input = form.querySelector('input');
        const action = form.getAttribute('action');
        if (!input || !action) return;
        const url = new URL(action, location.href);
        url.searchParams.set(input.name, input.value);
        const link = form.querySelector('a, button');
        const texto = link ? link.textContent.trim() : '';
        const row = form.closest('tr');
        const contexto = row ? row.innerText.replace(/\\s+/g, ' ').trim() : '';
        resultados.push({texto, contexto, url: url.toString()});
        if (link) vistos.add(link);
    });
    Array.from(root.querySelectorAll('a[href]')).forEach(a => {
        if (vistos.has(a)) return;
        const href = a.getAttribute('href');
        if (!href || href.startsWith('#') || href.toLowerCase().startsWith('javascript:')) return;
        const url = new URL(href, location.href);
        const row = a.closest('tr');
        const contexto = row ? row.innerText.replace(/\\s+/g, ' ').trim() : '';
        resultados.push({texto: a.textContent.trim(), contexto, url: url.toString()});
    });
    Array.from(root.querySelectorAll('audio[src], video[src], source[src]')).forEach(m => {
        const src = m.getAttribute('src');
        if (!src) return;
        const url = new URL(src, location.href);
        const row = m.closest('tr');
        const contexto = row ? row.innerText.replace(/\\s+/g, ' ').trim() : '';
        resultados.push({texto: 'audio', contexto, url: url.toString()});
    });
    return resultados;
}"""

# Cabecera del modal de detalle: son 2 o 3 tablas con clase "table-titulos".
# Cada celda trae un <strong>Etiqueta:</strong> y luego, segun el caso:
#   - texto plano (ROL, F. Ing., Tribunal, etc.)
#   - un <form method="get"> que descarga un documento (Texto Demanda, Ebook, ...)
#   - un enlace data-toggle="modal" que abre un sub-modal (Anexos de la causa,
#     Informacion notificaciones receptor, Listado de Audios de Audiencia, ...)
#   - el <select> de cuaderno, que se procesa aparte.
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
                // el select de cuaderno se procesa aparte (ver cuadernos)
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


def _sanitizar_nombre(texto: str, maximo: int = 60) -> str:
    texto = re.sub(r"[^\w\-]+", "_", texto or "", flags=re.UNICODE).strip("_")
    return (texto or "documento")[:maximo]


class CausaNoEncontrada(Exception):
    pass


class PjudSession:
    """Mantiene abierta una unica pagina real de la Consulta Unificada y la reutiliza
    entre consultas (mas rapido y mas parecido a un uso humano normal que abrir un
    navegador nuevo por cada busqueda)."""

    def __init__(self, headless: bool = False):
        logger.info("Iniciando sesion Playwright (headless=%s)", headless)
        self._lock = threading.Lock()
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=headless)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._goto_consulta_unificada()
        logger.info("Sesion Playwright lista")

    def close(self):
        with self._lock:
            logger.info("Cerrando sesion Playwright")
            self._context.close()
            self._browser.close()
            self._playwright.stop()

    def _goto_consulta_unificada(self):
        logger.debug("Navegando a %s", BASE_URL)
        self._page.goto(BASE_URL, wait_until="networkidle")
        self._ensure_rit_tab()

    def _ensure_rit_tab(self):
        page = self._page
        if not page.is_visible("#competencia"):
            page.click('a[href="#busRit"]')
        page.wait_for_selector("#competencia", state="visible")

    def _seleccionar_competencia_corte(self, competencia: str, corte: str):
        page = self._page
        self._ensure_rit_tab()
        page.select_option("#competencia", COMPETENCIAS[competencia])
        page.wait_for_timeout(400)
        page.select_option("#conCorte", corte)
        page.wait_for_function(
            "document.querySelectorAll('#conTribunal option').length > 1",
            timeout=15000,
        )

    def get_cortes(self):
        return CORTES

    def get_tribunales(self, competencia: str, corte: str):
        """Consulta en vivo (a traves de la pagina real) los tribunales disponibles
        para una competencia + corte, tal como lo haria el combo del sitio."""
        with self._lock:
            logger.debug("Obteniendo tribunales (competencia=%s, corte=%s)", competencia, corte)
            try:
                self._seleccionar_competencia_corte(competencia, corte)
                options = self._page.eval_on_selector_all(
                    "#conTribunal option",
                    "els => els.map(e => ({value: e.value, label: e.textContent.trim()}))",
                )
                resultado = [o for o in options if o["value"] not in ("", "0")]
                logger.debug("Tribunales obtenidos: %d", len(resultado))
                return resultado
            except Exception:
                logger.exception(
                    "Error al obtener tribunales (competencia=%s, corte=%s)", competencia, corte
                )
                raise

    # --- Descarga de documentos ---------------------------------------

    def _descargar_archivo(self, url: str, carpeta: str, nombre_base: str) -> str | None:
        try:
            resp = self._context.request.get(url)
            if not resp.ok:
                logger.warning("Descarga fallida (HTTP %s) para %s", resp.status, nombre_base)
                return None

            content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            cuerpo = resp.body()

            # El sitio responde con placeholders (una pagina HTML con un
            # alert()+window.close(), o un error de Oracle en texto plano) cuando el
            # tramite no tiene realmente un documento asociado. Se descartan para no
            # guardar "documentos" vacios o con mensajes de error.
            if content_type in ("text/html", "text/plain", ""):
                logger.debug(
                    "Se omite descarga (%s): la respuesta no es un documento (content-type=%s)",
                    nombre_base, content_type or "vacio",
                )
                return None
            if content_type == "application/pdf" and not cuerpo.startswith(b"%PDF"):
                logger.debug("Se omite descarga (%s): la respuesta dice ser PDF pero no lo es", nombre_base)
                return None
            if cuerpo[:200].lstrip().startswith(b"ORA-") or b"no data found" in cuerpo[:200]:
                logger.debug("Se omite descarga (%s): el servidor devolvio un error de base de datos", nombre_base)
                return None

            extension = mimetypes.guess_extension(content_type) or ".bin"
            os.makedirs(carpeta, exist_ok=True)
            nombre_archivo = f"{nombre_base}{extension}"
            ruta = os.path.join(carpeta, nombre_archivo)
            with open(ruta, "wb") as f:
                f.write(cuerpo)
            logger.debug("Documento descargado: %s (%s)", nombre_archivo, content_type or "sin content-type")
            return ruta
        except Exception:
            logger.exception("Error al descargar documento (%s)", nombre_base)
            return None

    def _resolver_descargas_en(self, selector: str) -> list:
        try:
            return self._page.eval_on_selector(selector, JS_RESOLVER_DESCARGAS) or []
        except Exception:
            logger.exception("Error al resolver descargas en %s", selector)
            return []

    # --- Extraccion de tablas / pestanas / sub-modales ------------------

    def _extraer_tablas_en(self, selector: str) -> list:
        return self._page.eval_on_selector_all(f"{selector} table", JS_EXTRAER_TABLAS)

    def _extraer_tabs(self, modal_id: str):
        """Lee, para el cuaderno actualmente seleccionado, cada pestana del modal
        (Historia, Litigantes, Notificaciones, etc.), sus tablas y sus documentos
        descargables. Devuelve (secciones, documentos)."""
        page = self._page
        tabs = page.evaluate(
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
        documentos = []
        for tab in tabs:
            href = tab["href"]
            if not href or not href.startswith("#"):
                continue
            try:
                page.click(f'#{modal_id} a[href="{href}"]')
            except Exception:
                continue
            page.wait_for_timeout(500)
            pane_id = href[1:]
            secciones[tab["nombre"]] = self._extraer_tablas_en(f"#{pane_id}")
            for d in self._resolver_descargas_en(f"#{pane_id}"):
                d["seccion"] = tab["nombre"]
                documentos.append(d)
        return secciones, documentos

    def _procesar_submodal(self, modal_id: str, target: str):
        """Abre un sub-modal lanzado desde la cabecera (Anexos de la causa,
        Informacion notificaciones receptor, Listado de Audios, etc.), extrae sus
        tablas y documentos descargables, y lo cierra. Devuelve (tablas, documentos)."""
        page = self._page
        if not target or not target.startswith("#"):
            return [], []
        sub_id = target[1:]
        try:
            page.click(f'#{modal_id} a[href="{target}"]')
        except Exception:
            logger.warning("No se pudo abrir el sub-modal %s", target)
            return [], []
        page.wait_for_timeout(900)
        if not page.query_selector(f"#{sub_id}"):
            logger.warning("Sub-modal %s no aparecio en el DOM", target)
            return [], []

        tablas = self._extraer_tablas_en(f"#{sub_id}")
        documentos = self._resolver_descargas_en(f"#{sub_id}")

        page.evaluate(
            """(subId) => {
                const modal = document.getElementById(subId);
                const cerrar = modal.querySelector('.close, button.close, [data-dismiss="modal"]');
                if (cerrar) cerrar.click();
            }""",
            sub_id,
        )
        page.wait_for_timeout(300)
        return tablas, documentos

    def buscar_causa(
        self,
        competencia: str,
        corte: str,
        tribunal: str,
        libro_tipo: str,
        rol,
        anio,
        carpeta_documentos: str | None = None,
    ):
        """Busca una causa y extrae su detalle completo: cabecera (campos + secciones
        como Anexos de la causa / Informacion notificaciones receptor) y, por cada
        cuaderno, sus pestanas (Historia, Litigantes, Notificaciones, etc.).

        Si se entrega `carpeta_documentos`, ademas descarga a esa carpeta todo
        documento encontrado (Texto Demanda, Certificado de Envio, Ebook, anexos,
        documentos de Historia, audios de audiencia, etc.) y deja el listado en
        el resultado bajo la clave "documentos".
        """
        with self._lock:
            page = self._page
            logger.info(
                "Buscando causa %s-%s-%s (competencia=%s, corte=%s, tribunal=%s)",
                libro_tipo, rol, anio, competencia, corte, tribunal,
            )
            documentos = []

            def registrar_descarga(origen: str, url: str):
                if not carpeta_documentos:
                    return
                indice = len(documentos) + 1
                nombre_base = f"{indice:02d}_{_sanitizar_nombre(origen)}"
                ruta = self._descargar_archivo(url, carpeta_documentos, nombre_base)
                if ruta:
                    documentos.append({"origen": origen, "archivo": ruta})

            try:
                self._seleccionar_competencia_corte(competencia, corte)
                page.select_option("#conTribunal", tribunal)
                page.wait_for_timeout(300)
                page.select_option("#conTipoCausa", libro_tipo)
                page.fill("#conRolCausa", str(rol))
                page.fill("#conEraCausa", str(anio))
                page.click('#busRit button[type="submit"]')
                page.wait_for_timeout(1500)

                objetivo = f"{libro_tipo}-{rol}-{anio}"
                encontrada = page.evaluate(
                    """(objetivo) => {
                        const cell = Array.from(document.querySelectorAll('#busRit td'))
                            .find(td => td.textContent.trim() === objetivo);
                        if (!cell) return null;
                        const row = cell.closest('tr');
                        const resumen = Array.from(row.querySelectorAll('td')).map(td => td.textContent.trim());
                        const firstTd = row.querySelector('td');
                        const clickable = firstTd.querySelector('a,button,i,span') || firstTd;
                        clickable.click();
                        return resumen;
                    }""",
                    objetivo,
                )

                if encontrada is None:
                    logger.info("Causa %s-%s-%s no encontrada", libro_tipo, rol, anio)
                    return {"encontrada": False}

                page.wait_for_timeout(700)
                modal_id = page.evaluate(
                    """() => {
                        const modals = Array.from(document.querySelectorAll('.modal.in'));
                        const visible = modals.find(m => m.offsetParent !== null);
                        return visible ? visible.id : (modals.length ? modals[modals.length - 1].id : null);
                    }"""
                )

                if not modal_id:
                    logger.warning(
                        "Causa %s-%s-%s encontrada pero no se pudo abrir el modal de detalle",
                        libro_tipo, rol, anio,
                    )
                    return {"encontrada": True, "resumen": encontrada, "detalle_error": "No se pudo abrir el detalle de la causa"}

                logger.debug("Modal de detalle abierto: %s", modal_id)

                # --- Cabecera: campos (ROL, F.Ing., Estado Proc., Tribunal, ...),
                # documentos descargables (Texto Demanda, Certificado, Ebook, ...) y
                # sub-modales (Anexos de la causa, Informacion notificaciones receptor, ...)
                cabecera_info = page.evaluate(JS_EXTRAER_CABECERA, modal_id)
                campos = cabecera_info.get("campos", {})

                for d in cabecera_info.get("descargas", []):
                    registrar_descarga(f"Cabecera - {d['label']}", d["url"])

                secciones_cabecera = {}
                for sub in cabecera_info.get("submodales", []):
                    tablas, sub_docs = self._procesar_submodal(modal_id, sub["target"])
                    secciones_cabecera[sub["label"]] = tablas
                    for i, doc in enumerate(sub_docs, start=1):
                        contexto = doc.get("contexto") or doc.get("texto") or str(i)
                        registrar_descarga(f"Cabecera - {sub['label']} - {contexto}", doc["url"])

                # --- Cuadernos: algunas causas (tipicamente Civil y Cobranza) tienen
                # mas de un "cuaderno" (Principal, Incidente, Apremio, Compulsas, etc.),
                # cada uno con su propia Historia/Litigantes/Notificaciones/etc. El
                # selector de cuaderno (si existe) esta dentro del modal de detalle;
                # al cambiarlo, el sitio recarga el contenido de las pestanas.
                cuaderno_opciones = page.evaluate(
                    """(modalId) => {
                        const modal = document.getElementById(modalId);
                        const sel = modal.querySelector('select');
                        if (!sel) return null;
                        return Array.from(sel.options).map(o => ({value: o.value, label: o.textContent.trim()}));
                    }""",
                    modal_id,
                )

                cuadernos = {}
                if cuaderno_opciones:
                    select_selector = f"#{modal_id} select"
                    etiquetas = [o["label"] for o in cuaderno_opciones]
                    for etiqueta in etiquetas:
                        if len(etiquetas) > 1:
                            # El valor del <option> (un token firmado) puede haber
                            # quedado obsoleto si ya paso tiempo (p. ej. descargando
                            # documentos del cuaderno anterior), asi que se relee justo
                            # antes de seleccionarlo en vez de reusar el valor inicial.
                            valor_actual = page.eval_on_selector(
                                select_selector,
                                """(sel, etiqueta) => {
                                    const opt = Array.from(sel.options).find(o => o.textContent.trim() === etiqueta);
                                    return opt ? opt.value : null;
                                }""",
                                etiqueta,
                            )
                            if valor_actual is None:
                                logger.warning(
                                    "Cuaderno '%s' ya no aparece en el selector; se omite", etiqueta
                                )
                                continue
                            try:
                                page.select_option(select_selector, valor_actual)
                            except Exception:
                                logger.exception(
                                    "No se pudo cambiar al cuaderno '%s'; se omite y se conserva lo ya extraido",
                                    etiqueta,
                                )
                                continue
                            page.wait_for_timeout(900)
                        secciones, tab_docs = self._extraer_tabs(modal_id)
                        cuadernos[etiqueta] = secciones
                        for doc in tab_docs:
                            contexto = doc.get("contexto") or doc.get("texto") or ""
                            registrar_descarga(
                                f"{etiqueta} - {doc['seccion']} - {contexto}", doc["url"]
                            )
                else:
                    secciones, tab_docs = self._extraer_tabs(modal_id)
                    cuadernos["Principal"] = secciones
                    for doc in tab_docs:
                        contexto = doc.get("contexto") or doc.get("texto") or ""
                        registrar_descarga(f"{doc['seccion']} - {contexto}", doc["url"])

                # Cierra el modal para dejar la pagina lista para la siguiente consulta.
                page.evaluate(
                    """(modalId) => {
                        const modal = document.getElementById(modalId);
                        const cerrar = modal.querySelector('.close, button.close, [data-dismiss="modal"]');
                        if (cerrar) cerrar.click();
                    }""",
                    modal_id,
                )
                page.wait_for_timeout(300)

                logger.info(
                    "Causa %s-%s-%s encontrada. Cuadernos: %s. Documentos descargados: %d",
                    libro_tipo, rol, anio, list(cuadernos.keys()), len(documentos),
                )

                return {
                    "encontrada": True,
                    "resumen": encontrada,
                    "cabecera": {"campos": campos, "secciones": secciones_cabecera},
                    "cuadernos": cuadernos,
                    "documentos": documentos,
                }
            except Exception:
                logger.exception(
                    "Error al buscar la causa %s-%s-%s (competencia=%s, corte=%s, tribunal=%s)",
                    libro_tipo, rol, anio, competencia, corte, tribunal,
                )
                raise
            finally:
                # Pausa deliberada: evita encadenar consultas a alta frecuencia.
                page.wait_for_timeout(PAUSA_ENTRE_CONSULTAS_MS)
