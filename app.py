"""Exportar Plan de Trabajo a Google Calendar — aplicación Streamlit.

Sube el plan de trabajo (CSV o Excel), revisa lo que se detectó y manda las
actividades y las videoconferencias a tu Google Calendar de un botón.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time
from html import escape
from pathlib import Path
# `time` aquí ya es `datetime.time`; para medir la espera de OAuth basta con
# esto, que además no se descuadra si cambia la hora del sistema.
from time import monotonic, sleep
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
import streamlit as st

from tabla_calendar import deteccion, exportar, tablas
from tabla_calendar import google_calendar as gcal
from tabla_calendar import pdf as planpdf
from tabla_calendar.modelo import (
    MODO_DIA,
    MODO_HORA,
    PLANTILLAS,
    Evento,
    construir_eventos,
)

RAIZ = Path(__file__).parent
ANIO_ACTUAL = date.today().year

ZONAS = [
    "America/Mexico_City", "America/Tijuana", "America/Mazatlan", "America/Cancun",
    "America/Bogota", "America/Lima", "America/Santiago", "America/Argentina/Buenos_Aires",
    "Europe/Madrid", "UTC",
]

RECORDATORIOS = {
    "Sin recordatorio": None,
    "1 hora antes": 60,
    "3 horas antes": 180,
    "1 día antes": 1440,
    "2 días antes": 2880,
    "1 semana antes": 10080,
}

# Todo lo que cambia entre los dos tipos de importación, en un solo lugar.
TIPOS = {
    MODO_DIA: {
        "icono": "📝",
        "etiqueta": "📝  Actividades y entregas",
        "descripcion": "Tareas con fecha límite. Se crean como eventos de **todo el día**.",
    },
    MODO_HORA: {
        "icono": "🎥",
        "etiqueta": "🎥  Videoconferencias y asesorías",
        "descripcion": "Sesiones con horario. Se crean como eventos **con hora de inicio y fin**.",
    },
}

st.set_page_config(
    page_title="Exportar Plan de Trabajo a Google Calendar",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --------------------------------------------------------------------------- #
# Estilo
# --------------------------------------------------------------------------- #

def estilos() -> None:
    st.markdown(
        """
        <style>
          .bloque-titulo {
            background: linear-gradient(115deg, #4F46E5 0%, #7C3AED 55%, #DB2777 100%);
            color: #fff; border-radius: 18px; padding: 26px 30px; margin-bottom: 20px;
          }
          .bloque-titulo h1 { margin: 0; font-size: 2rem; font-weight: 700; letter-spacing: -.5px; }
          .bloque-titulo p  { margin: 8px 0 0; font-size: 1rem; opacity: .92; max-width: 62ch; }
          .paso {
            display: flex; align-items: center; gap: 12px;
            margin: 30px 0 12px; padding-bottom: 10px; border-bottom: 2px solid #EEF0F6;
          }
          .paso-num {
            flex: 0 0 auto; width: 30px; height: 30px; border-radius: 50%;
            background: #4F46E5; color: #fff; font-weight: 700; font-size: .95rem;
            display: flex; align-items: center; justify-content: center;
          }
          .paso-num.gris { background: #C7CBD9; }
          .paso h3 { margin: 0; font-size: 1.18rem; font-weight: 650; color: #1F2430; }
          .paso small { color: #767C8F; font-weight: 400; }
          .nota {
            background: #F5F6FA; border-left: 4px solid #4F46E5; border-radius: 8px;
            padding: 12px 16px; font-size: .9rem; color: #3A4055; margin: 6px 0 14px;
          }
          .marca { font-size: .78rem; color: #767C8F; text-align: center; margin-top: 10px; }
          /* «Conectar con Google» lo pinta HTML propio y no `st.link_button`
             porque el clic tiene que abrir la ventana emergente por JavaScript
             dentro del mismo gesto del usuario, que es la única forma de que el
             navegador no la bloquee. Ver `panel_google`. */
          a.boton-google {
            display: block; width: 100%; box-sizing: border-box;
            background: #4F46E5; color: #fff !important; text-decoration: none !important;
            border-radius: 8px; padding: 11px 16px; text-align: center;
            font-weight: 600; font-size: .95rem; border: 1px solid #4F46E5;
          }
          a.boton-google:hover { background: #4338CA; border-color: #4338CA; }
          /* El botón puente sólo existe para que ese mismo script pueda
             pulsarlo y avisar al servidor; al usuario no le dice nada. */
          .st-key-oauth_espera { display: none; }
          /* Streamlit escribe «Press Enter to apply» y no es configurable;
             se oculta y se sustituye por la versión en español. */
          div[data-testid="InputInstructions"] { visibility: hidden; position: relative; }
          div[data-testid="InputInstructions"]::after {
            content: "Pulsa Enter o haz clic fuera para aplicarlo";
            visibility: visible; position: absolute; left: 0; top: 0; white-space: nowrap;
          }
          .aviso-google {
            background: #FFF7E6; border: 1px solid #F0B429; border-left: 4px solid #F0B429;
            border-radius: 8px; padding: 11px 13px; margin: 12px 0 18px;
            font-size: .82rem; line-height: 1.5; color: #6B4A0B;
          }
          .aviso-google b { color: #7A2E0E; }
          div[data-testid="stMetricValue"] { font-size: 1.7rem; }
          /* El selector de tipo del paso 1 manda sobre todo lo demás: que se
             vea así. */
          div[data-testid="stSegmentedControl"] button { font-size: 1rem; padding: 10px 22px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def paso(numero: int, titulo: str, sub: str = "", activo: bool = True) -> None:
    clase = "paso-num" if activo else "paso-num gris"
    extra = f" <small>· {sub}</small>" if sub else ""
    st.markdown(
        f'<div class="paso"><div class="{clase}">{numero}</div>'
        f"<h3>{titulo}{extra}</h3></div>",
        unsafe_allow_html=True,
    )


def nota(texto: str) -> None:
    st.markdown(f'<div class="nota">{texto}</div>', unsafe_allow_html=True)


def pie_lateral() -> None:
    """Crédito y mascota, al fondo de la barra lateral."""
    st.markdown(
        '<div class="marca">Creado por '
        '<a href="https://github.com/AmiyaMihari" target="_blank">AmiyaMihari</a>'
        '</div>',
        unsafe_allow_html=True,
    )
    mascota = RAIZ / "assets" / "gato.jpeg"
    if mascota.exists():
        st.image(str(mascota), width="stretch")


# --------------------------------------------------------------------------- #
# Estado
# --------------------------------------------------------------------------- #

def arrancar_estado() -> None:
    # `guardados` son los eventos de tablas anteriores; los de la tabla que está
    # abierta ahora se calculan al vuelo y se suman al exportar. Así no hay que
    # pulsar ningún botón de «confirmar» para que cuenten.
    st.session_state.setdefault("guardados", [])
    st.session_state.setdefault("archivo", None)
    # Cambiar este número le da una clave nueva al file_uploader, que es la
    # única forma de vaciarlo: si no, el widget conserva el archivo y lo vuelve
    # a cargar en el siguiente ciclo (y los eventos se duplicaban).
    st.session_state.setdefault("ronda_subida", 0)
    st.session_state.setdefault("credenciales", None)
    st.session_state.setdefault("hoja", None)
    st.session_state.setdefault("fila_encabezado", None)
    st.session_state.setdefault("firma_archivo", "")
    # De qué archivo ya sacamos el nombre de la materia (para sugerirlo una vez).
    st.session_state.setdefault("materia_sugerida", None)


def firma(*partes) -> str:
    return hashlib.md5("|".join(str(p) for p in partes).encode()).hexdigest()[:12]


# Lo único que sobrevive a «Empezar de nuevo»: volver a pasar por Google cuesta
# salir de la página, aceptar permisos y volver, y es justo lo que se quiere
# evitar cuando sólo se va a cargar el plan de otra materia.
CLAVES_QUE_SOBREVIVEN = ("credenciales", "correo_google")


def reiniciar_sesion() -> None:
    """Deja la app como recién abierta, pero sin soltar la sesión de Google.

    Se llama al principio de `main()`, antes de crear ningún widget: Streamlit
    no deja tocar la clave de un widget ya instanciado, y aquí se borran todas.
    """
    conservado = {c: st.session_state[c] for c in CLAVES_QUE_SOBREVIVEN
                  if c in st.session_state}
    # El `file_uploader` sólo se vacía dándole una clave nueva; si se reiniciara
    # el contador a cero, el widget recuperaría el archivo anterior.
    ronda = st.session_state.get("ronda_subida", 0) + 1

    st.session_state.clear()
    st.session_state.update(conservado)
    arrancar_estado()
    st.session_state.ronda_subida = ronda


def url_base() -> str:
    """URL pública de la app, sin parámetros: sirve como redirect_uri de OAuth.

    La ruta vacía se fuerza a «/» porque Google compara el redirect_uri carácter
    por carácter: en Streamlit Cloud `st.context.url` llega sin diagonal final y
    dejaba de coincidir con el URI registrado, que sí la lleva.
    """
    try:
        partes = urlsplit(st.context.url)
        return urlunsplit((partes.scheme, partes.netloc, partes.path or "/", "", ""))
    except Exception:
        return ""


def config_google() -> dict | None:
    """Credenciales de OAuth: primero los Secrets, si no el JSON de Google Cloud.

    En Streamlit Cloud sólo existen los Secrets; en local basta con dejar el
    JSON descargado en `env/` (esa carpeta está en .gitignore).
    """
    if not gcal.DISPONIBLE:
        return None
    url = url_base()
    return (
        gcal.leer_config(st.secrets, url_defecto=url)
        or gcal.buscar_config_local(RAIZ, url_defecto=url)
    )


# --------------------------------------------------------------------------- #
# Las tablas activas — qué se está pasando al calendario ahora mismo
# --------------------------------------------------------------------------- #

@dataclass
class TablaActiva:
    """Una tabla en curso: la del CSV o el Excel, o cada tabla marcada del PDF.

    Es la unidad de trabajo de los pasos 2, 3 y 4: cada una trae su tipo, su
    mapeo de columnas y su editor, y al exportar se suman todas.

    **No vive en `session_state`.** Se reconstruye entera en cada ciclo a partir
    del archivo —el PDF pasa por `_tablas_del_pdf`, que está cacheado—, y en la
    sesión sólo quedan las claves de los widgets que deciden qué tablas están
    marcadas y de qué tipo es cada una. Un DataFrame guardado aparte sería una
    copia que envejece a espaldas del archivo y de la fila de encabezado.
    """

    df: pd.DataFrame
    modo: str
    # Cómo se llama esta tabla para el usuario: la hoja del Excel, el nombre del
    # archivo, o el que le puso `pdf.py` («Videoconferencias · grupo 8396 · …»).
    nombre: str
    # De dónde salió cada evento; viaja dentro del `Evento` hasta el paso 4.
    origen: str
    # Firma estable de la tabla: raíz de todas sus claves de widget. Lleva
    # dentro la firma del archivo, así que al cambiar de archivo Streamlit poda
    # solo las claves viejas y ninguna elección se arrastra a la tabla nueva.
    clave: str
    # Sólo CSV y Excel: en qué fila están los títulos, que el paso 2 deja
    # corregir. En el PDF los reconstruye `pdf.py` y no hay nada que ajustar.
    fila_encabezado: int | None = None
    # Sólo PDF: el tipo que propuso `Candidata.modo`. Que no sea None es lo que
    # hace que el paso 2 dibuje el corrector — en CSV y Excel el tipo ya se
    # preguntó arriba, en el paso 1, y preguntarlo dos veces sobraría.
    tipo_propuesto: str | None = None

    @property
    def etiqueta(self) -> str:
        """Nombre con icono, para la pestaña de los pasos 2 y 3."""
        return f"{TIPOS[self.modo]['icono']} {self.nombre}"


def modo_de(clave: str, propuesto: str) -> str:
    """El tipo que rige para una tabla: el que corrigió el usuario, o el propuesto.

    La corrección vive en la clave de un widget (`tipo_<clave>`), que Streamlit
    poda en cuanto ese widget deja de dibujarse: al desmarcar una tabla del PDF
    o cambiar de archivo, la corrección se va con ella y la siguiente vuelve a
    partir de la propuesta. Es justo lo que se quiere.
    """
    return st.session_state.get(f"tipo_{clave}") or propuesto


def plantilla_de(modo: str) -> str:
    """La plantilla del título vigente para un tipo de evento.

    Vive en la clave del `text_input` que dibuja el paso 2 (`plantilla_<modo>`),
    una por tipo y no una por tabla: dos tablas de videoconferencias son el
    mismo tipo de evento y titularlas distinto no tendría sentido.
    """
    return st.session_state.get(f"plantilla_{modo}") or PLANTILLAS[modo]


def adivinar_tipo(df: pd.DataFrame) -> str:
    """Qué parece traer esta tabla: entregas o sesiones con horario.

    Se reutiliza la detección de columnas del paso 2 —no hay una segunda
    heurística que mantener— pidiéndola en modo hora: si de ahí sale una columna
    de horario **con horas de verdad** en al menos una de cada tres filas
    (`deteccion.hay_horarios`), la tabla es de videoconferencias. Mirar sólo el
    nombre no basta, porque «Inicio» también titula columnas de fecha; el puntaje
    por contenido es justo lo que las separa.

    `dayfirst=True` da igual aquí: sólo decide cómo leer una fecha ambigua, y lo
    que se mide es si la columna trae horas. El ajuste del usuario vive en la
    barra lateral, que en este punto del ciclo todavía no se ha dibujado.
    """
    mapeo = deteccion.detectar_columnas(df, True, MODO_HORA)
    return MODO_HORA if deteccion.hay_horarios(df, mapeo["hora"]) else MODO_DIA


def selector_de_tipo_de_tabla(df: pd.DataFrame, clave: str) -> str:
    """La pregunta del paso 1 para CSV y Excel, ya con una respuesta puesta.

    Con un PDF no se dibuja: allí cada tabla trae su tipo escrito
    (`Candidata.modo`), y quien quiera desmentirlo tiene el corrector del paso 2.
    """
    # La propuesta se calcula una sola vez por tabla y se guarda: `adivinar_tipo`
    # recorre el DataFrame entero y esto se dibuja en cada ciclo. La clave no es
    # de widget, así que sobrevive aunque el `segmented_control` se pode.
    clave_propuesta = f"prop_{clave}"
    if clave_propuesta not in st.session_state:
        st.session_state[clave_propuesta] = adivinar_tipo(df)
    propuesto = st.session_state[clave_propuesta]

    # Clave por tabla y no una global: Streamlit borra de la sesión la clave de
    # un widget que deja de dibujarse, y éste desaparece en cuanto el archivo es
    # un PDF; además, así una tabla nueva estrena propuesta en vez de heredar la
    # elección de la anterior.
    clave_widget = f"tipo_{clave}"
    # `default` sólo la primera vez, o Streamlit avisa de que el valor se está
    # fijando por dos vías. A partir de ahí manda lo que haya dejado el usuario.
    inicial = {} if clave_widget in st.session_state else {"default": propuesto}
    elegido = st.segmented_control(
        "¿Qué quieres pasar al calendario?",
        options=list(TIPOS),
        format_func=lambda m: TIPOS[m]["etiqueta"],
        key=clave_widget,
        **inicial,
    )
    # `st.segmented_control` deja deseleccionar pulsando la opción activa; ahí no
    # hay tipo nuevo que aplicar y vuelve a regir la propuesta.
    modo = elegido or propuesto
    st.caption(TIPOS[modo]["descripcion"])
    return modo


# --------------------------------------------------------------------------- #
# Barra lateral
# --------------------------------------------------------------------------- #

def hay_sesiones_con_horario(activas: list[TablaActiva]) -> bool:
    """¿Pinta algo la duración por omisión? Sólo si hay eventos con hora.

    Se miran las tablas abiertas **y** lo ya guardado: una sesión guardada en
    un archivo anterior también se exporta con esa duración.
    """
    return (any(t.modo == MODO_HORA for t in activas)
            or any(not ev.todo_el_dia for ev in st.session_state.guardados))


def barra_lateral(con_horario: bool, dibujar_google: bool = True) -> dict:
    """Los ajustes que valen para todas las tablas a la vez.

    La plantilla del título no está aquí: se mudó al paso 2 cuando dejó de haber
    un solo tipo de evento por sesión. Con una tabla de actividades y otra de
    videoconferencias abiertas, una plantilla única en la barra no podía servir
    a las dos, y cada una vive ahora en la pestaña de su tabla.
    """
    with st.container():
        st.markdown("### ⚙️ Ajustes")
        materia = st.text_input(
            "Nombre de la materia",
            help="Se antepone al título de cada evento y da nombre al calendario "
                 "nuevo.",
            key="materia",
        )
        zona = st.selectbox("Zona horaria", ZONAS, index=0)
        etiqueta_rec = st.selectbox("Recordatorio", list(RECORDATORIOS), index=0)

        with st.expander("Ajustes avanzados"):
            orden = st.radio(
                "Cuando la fecha sea ambigua (03/04/2026), léela como:",
                ["Día/Mes/Año — México", "Mes/Día/Año — EUA"],
                index=0,
            )
            anio_defecto = st.number_input(
                "Año para fechas escritas sin año",
                min_value=2000, max_value=2100, value=ANIO_ACTUAL, step=1,
            )
            duracion = st.number_input(
                "Duración de una sesión sin hora de fin (horas)",
                min_value=0.5, max_value=12.0, value=2.0, step=0.5,
                disabled=not con_horario,
            )
            rellenar = st.checkbox(
                "Rellenar hacia abajo las celdas combinadas de «Unidad»",
                value=True,
                help="Excel deja huecos debajo de una celda combinada; esto los completa.",
            )

        if dibujar_google:
            st.divider()
            panel_google()

    return {
        "materia": materia,
        "zona": zona,
        "recordatorio": RECORDATORIOS[etiqueta_rec],
        "dayfirst": orden.startswith("Día"),
        "anio_defecto": int(anio_defecto),
        "duracion": float(duracion),
        "rellenar": rellenar,
    }


# --------------------------------------------------------------------------- #
# Google
# --------------------------------------------------------------------------- #

AYUDA_SIN_CONFIGURAR = (
    "El botón de envío directo necesita credenciales de Google que configura **una "
    "sola vez quien publica la app** — no vienen en el código porque son secretas.\n\n"
    "Si tú administras esta instalación (ver `docs/DESPLIEGUE.md` → **Parte B**):\n\n"
    "- **En tu computadora:** deja el JSON que descargaste de Google Cloud dentro de "
    "la carpeta `env/`. La app lo encuentra sola.\n"
    "- **En Streamlit Cloud:** pega el `client_id` y el `client_secret` en "
    "*Settings → Secrets*.\n\n"
    "Mientras tanto, **Descargar archivo .ics** hace exactamente lo mismo."
)

# Cuánto se sonda esperando a que la ventana emergente traiga el permiso.
ESPERA_OAUTH = 180

# Va pegado al ancla en el mismo `st.html` —que Streamlit reinserta como
# `<script>` de verdad cuando se le pide JavaScript—, así que se ejecuta cada vez
# que el enlace se vuelve a pintar y siempre engancha el ancla recién creada.
SCRIPT_BOTON_GOOGLE = """
<script>
(function () {
  const anclas = document.querySelectorAll('a.boton-google');
  const enlace = anclas[anclas.length - 1];
  if (!enlace || enlace.dataset.enganchado) return;
  enlace.dataset.enganchado = '1';
  enlace.addEventListener('click', function (ev) {
    // Ctrl / Cmd / Mayús: el usuario está pidiendo pestaña o ventana a su
    // manera. Se le deja hacer.
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
    ev.preventDefault();
    const emergente = window.open(enlace.href, 'oauth_google',
                                  'popup,width=520,height=680');
    // Si un bloqueador la impidió no se toca nada: el href sigue siendo la URL
    // buena y debajo está el enlace de respaldo, que abre pestaña como antes.
    if (!emergente) return;
    emergente.focus();
    // Se guarda la referencia para poder cerrarla desde aquí al terminar: a
    // quien abre una ventana siempre se le permite cerrarla, aunque sea de otro
    // origen. El documento de la app no se recarga entre reejecuciones de
    // Streamlit, así que la global sobrevive toda la espera.
    window.__emergenteOAuth = emergente;
    // Abrir la ventana es cosa del navegador y el servidor no se entera. Este
    // clic sintético sobre el botón oculto es el único aviso posible de que ya
    // puede ponerse a esperar.
    document.querySelector('.st-key-oauth_espera button')?.click();
  });
})();
</script>
"""


def boton_empezar_de_nuevo() -> None:
    """Reinicio rápido, al principio de la barra lateral.

    Sólo se dibuja cuando hay algo que reiniciar: en la primera visita no hace
    falta y quitaría protagonismo a «Conectar con Google», que ahí es lo que
    toca. Va arriba del todo porque cuando el usuario aún no se ha conectado el
    panel de Google es largo y empujaba el botón fuera de la pantalla.
    """
    if st.session_state.archivo is None and not st.session_state.guardados:
        return
    if st.button(
        "🔄 Empezar de nuevo",
        width="stretch",
        help="Borra el archivo, los eventos y el nombre de la materia para "
             "empezar con otra. No te desconecta de Google.",
    ):
        # Se deja pendiente: en este ciclo los widgets ya están creados y
        # `reiniciar_sesion` borra sus claves.
        st.session_state.reiniciar_pendiente = True
        st.rerun()
    st.caption("Otra materia, sin volver a conectar Google.")
    st.divider()


def panel_google(actuales: list[Evento] | None = None) -> None:
    st.markdown("### 🔗 Google Calendar")

    if not gcal.DISPONIBLE:
        st.warning("Faltan las librerías de Google en este entorno.")
        return

    cfg = config_google()
    if not cfg:
        st.info("Envío directo no disponible: descarga el `.ics`.", icon="ℹ️")
        with st.expander("¿Por qué?"):
            st.markdown(AYUDA_SIN_CONFIGURAR)
            actual = url_base()
            if actual:
                st.caption("Al configurarlo, registra este URI de redirección en Google Cloud:")
                st.code(actual, language=None)
        return

    # El regreso de Google ya se procesó al arrancar main().
    if st.session_state.credenciales:
        correo = st.session_state.get("correo_google", "")
        st.success(f"Conectado{f' como {correo}' if correo else ''}", icon="✅")
        if st.button("Desconectar", width="stretch"):
            for clave in ("credenciales", "correo_google"):
                st.session_state.pop(clave, None)
            st.rerun()
    elif st.session_state.get("esperando_oauth"):
        # Mientras dura el sondeo no se genera URL nueva: cada una deja un
        # `state` en el proceso y se llenaría de intentos que nadie va a usar.
        st.info(
            "Termina de autorizar en la ventana emergente. En cuanto aceptes se "
            "cierra sola y esta página queda conectada, con tu trabajo intacto.",
            icon="⏳",
        )
        if st.button("Cancelar", width="stretch"):
            st.session_state.pop("esperando_oauth", None)
            st.rerun()
        aviso_app_sin_verificar()
    else:
        try:
            # Aunque el permiso se da en otra ventana, el trabajo del usuario
            # viaja igual junto al `state`: si la emergente no logra cerrarse, o
            # si se usó el enlace de respaldo, esa ventana acaba siendo la app y
            # tiene que poder devolvérselo.
            # `actuales` es la unión de las tablas abiertas: lo que hay en los
            # editores del paso 3 se guarda junto con lo que ya estaba, para que
            # el viaje a Google no se coma ninguna de las dos cosas.
            url, state = gcal.url_autorizacion(cfg, datos_sesion={
                "guardados": st.session_state.guardados + list(actuales or []),
                "materia": st.session_state.get("materia", ""),
            })
        except gcal.ErrorGoogle as e:
            st.error(str(e))
            return
        # Cada ejecución pinta un enlace con `state` nuevo y el usuario pudo
        # pulsar cualquiera de los anteriores (la página se redibuja sola a cada
        # rato), así que se recuerdan los últimos y se buscan todos al recoger.
        estados = st.session_state.setdefault("estados_oauth", [])
        estados.append(state)
        del estados[:-20]
        # Ancla propia y no `st.link_button` porque la ventana emergente hay que
        # abrirla con `window.open` dentro del mismo gesto del clic —si no, el
        # navegador la bloquea—, y el `<a>` de `st.link_button` además lleva
        # `rel="noreferrer"`, que le impediría cerrarse sola al terminar.
        # Navegar en la misma ventana no es opción: en Streamlit Cloud la app va
        # dentro de un iframe cuyo `sandbox` no trae `allow-top-navigation`, y
        # Google responde 403 a su pantalla de inicio de sesión si va enmarcada.
        st.html(
            f'<a class="boton-google" href="{escape(url, quote=True)}">'
            "Conectar con Google</a>" + SCRIPT_BOTON_GOOGLE,
            unsafe_allow_javascript=True,
        )
        # El camino de siempre, por si un bloqueador impidió la emergente.
        st.link_button(
            "¿No se abrió la ventana? Conéctate en otra pestaña",
            url, type="tertiary", width="stretch",
        )
        aviso_app_sin_verificar()


def aviso_app_sin_verificar() -> None:
    """Google enseña una pantalla de advertencia porque la app no está verificada.

    El trámite exige dominio propio. Sin explicar esto y cómo seguir, la mayoría
    se echa para atrás justo aquí, así que el aviso acompaña tanto al botón como
    a la espera de la ventana emergente: es entonces cuando se topan con ella.
    """
    st.markdown(
        '<div class="aviso-google">'
        '⚠️ Google te dirá que <b>«no ha verificado esta aplicación»</b>. '
        'Es normal y puedes continuar:<br><br>'
        '1. Pulsa <b>Configuración avanzada</b><br>'
        '2. Luego <b>Ir a Exportar Plan de Trabajo a Google Calendar</b>'
        '</div>',
        unsafe_allow_html=True,
    )
    with st.expander("¿Por qué sale eso? ¿Es seguro?"):
        st.markdown(
            "Esa pantalla **no significa que la app sea peligrosa**. Google la "
            "muestra en toda aplicación que no haya pasado su proceso de "
            "verificación, un trámite que exige dominio propio y aviso de "
            "privacidad publicado; para un proyecto estudiantil no compensa.\n\n"
            "Qué puedes comprobar tú:\n\n"
            "- Tu archivo **no se guarda**: se procesa mientras usas la página.\n"
            "- El permiso sólo sirve para **crear los eventos que confirmes**.\n"
            "- Puedes retirárselo cuando quieras en "
            "[tu cuenta de Google](https://myaccount.google.com/permissions).\n"
            "- El código es abierto y se puede revisar: "
            "[github.com/AmiyaMihari](https://github.com/AmiyaMihari/Table_to_google_calendar).\n\n"
            "Si aun así prefieres no dar permisos, descarga el `.ics` en el "
            "paso 4: hace exactamente lo mismo."
        )


def procesar_regreso_oauth(cfg: dict) -> None:
    """Google devuelve al usuario con ?code=...&state=... en la URL."""
    if st.session_state.credenciales:
        return
    codigo = st.query_params.get("code")
    if not codigo:
        return

    estado = st.query_params.get("state")
    try:
        credenciales, datos = gcal.credenciales_desde_codigo(cfg, codigo, estado)
    except gcal.ErrorGoogle as e:
        st.query_params.clear()
        st.error(str(e))
        return

    st.session_state.credenciales = credenciales
    st.session_state.correo_google = gcal.correo_usuario(credenciales)

    # Lo más probable es que esta ejecución sea la de la ventana emergente, que
    # para Streamlit es una sesión aparte: se deja copia en el proceso para que
    # la pestaña que la abrió la recoja y se conecte sin perder nada. Restaurar
    # la sesión propia no sobra —es lo que salva el caso de que la emergente no
    # consiga cerrarse, o el del enlace de respaldo en pestaña nueva.
    if estado:
        gcal.depositar_credenciales(estado, credenciales, st.session_state.correo_google)
    st.session_state.cerrar_si_es_emergente = True

    # Devolverle al usuario lo que tenía antes de salir a Google. El tipo de
    # cada tabla no viaja: sin archivo no hay tabla que tipar, y en cuanto suba
    # uno el paso 1 vuelve a proponerlo mirando lo que traiga.
    if datos:
        st.session_state.guardados = datos.get("guardados") or []
        if datos.get("materia") is not None and "materia" not in st.session_state:
            st.session_state.materia = datos["materia"]
        if st.session_state.guardados:
            st.session_state.aviso_restaurado = len(st.session_state.guardados)

    st.query_params.clear()
    st.rerun()


def despedir_ventana_emergente() -> None:
    """Cierra la ventana si esta ejecución resultó ser la emergente de OAuth.

    `close()` sólo obedece en ventanas abiertas por script, así que en una
    pestaña normal no ocurre nada y el usuario se queda aquí como siempre. Se
    hace en la ejecución siguiente al canje y no dentro de `procesar_regreso_oauth`
    porque aquélla termina en `st.rerun()`, que se llevaría el script por delante.
    """
    if not st.session_state.pop("cerrar_si_es_emergente", False):
        return
    # Un aviso que se desvanece: cuando la ventana sí se cierra nadie lo llega a
    # leer, y cuando no (el iframe de la nube no siempre puede cerrar su ventana)
    # dice lo único que hace falta saber.
    st.toast("Conexión lista. Si esta ventana no se cierra sola, ya puedes "
             "cerrarla y volver a la pestaña donde estabas.", icon="✅")
    st.html(
        "<script>try { window.top.close(); } catch (e) {}</script>",
        unsafe_allow_javascript=True,
    )


def recoger_credenciales_de_la_emergente() -> None:
    """Trae el permiso que la ventana emergente dejó en el proceso, si ya llegó.

    Se mira en todas las ejecuciones y no sólo mientras dura el sondeo: si la
    espera se agotó y el usuario autoriza más tarde, el primer clic que dé aquí
    lo conecta igual.
    """
    if st.session_state.credenciales:
        return
    for estado in st.session_state.get("estados_oauth", []):
        recogido = gcal.recoger_credenciales(estado)
        if recogido is None:
            continue
        st.session_state.credenciales, st.session_state.correo_google = recogido
        st.session_state.pop("esperando_oauth", None)
        st.session_state.pop("estados_oauth", None)
        # El cierre no se emite aquí: cualquier `st.rerun()` de más abajo se
        # llevaría el script por delante. Se deja pendiente para el final del
        # ciclo, que es donde ya nada puede tragárselo.
        st.session_state.cerrar_emergente_pendiente = True
        st.toast("Conectado con Google", icon="✅")
        return


def cerrar_emergente_desde_el_abridor() -> None:
    """Cierra la ventana emergente desde la pestaña que la abrió.

    Es el segundo camino del cierre, y el que sí es legal siempre: al popup se
    le permite cerrarse a sí mismo sólo si puede navegar su ventana completa, y
    en la nube va dentro de un iframe con `sandbox` donde eso falla en silencio;
    en cambio a quien abrió una ventana nunca se le niega cerrarla, aunque sea
    de otro origen. Con los dos caminos basta con que funcione cualquiera.
    """
    if not st.session_state.pop("cerrar_emergente_pendiente", False):
        return
    st.html(
        "<script>try {"
        "  if (window.__emergenteOAuth && !window.__emergenteOAuth.closed)"
        "    window.__emergenteOAuth.close();"
        "  window.__emergenteOAuth = null;"
        "} catch (e) {}</script>",
        unsafe_allow_javascript=True,
    )


def boton_puente_oauth(configurado: bool) -> None:
    """Botón invisible al que el script del enlace le da un clic sintético.

    Es la única manera de que el servidor se entere de que la ventana emergente
    se abrió: abrirla es cosa del navegador y Streamlit no ve nada. Vive en
    `main()` —y no junto al enlace— para que se pinte exactamente una vez por
    ejecución: su clave es única y `panel_google` tiene dos puntos de llamada.
    """
    if not configurado or st.session_state.credenciales:
        return
    if st.button("Esperando la autorización de Google", key="oauth_espera"):
        st.session_state.esperando_oauth = monotonic()


# --------------------------------------------------------------------------- #
# Paso 1 · Archivo
# --------------------------------------------------------------------------- #

def olvidar_archivo() -> None:
    """Vacía el archivo actual y el widget que lo sostiene."""
    st.session_state.archivo = None
    st.session_state.firma_archivo = ""
    st.session_state.ronda_subida += 1


def paso_archivo() -> tuple[bytes, str] | None:
    # El subtítulo no depende de ningún tipo a propósito: el PDF del plan trae
    # las dos tablas dentro, así que no hay que pedirle al usuario que decida
    # antes de subir nada.
    paso(1, "Sube tu archivo", "tu plan de trabajo en PDF, o la tabla en CSV o Excel")

    # Sin archivo y con eventos en el bolsillo sólo se llega por «Añadir otro
    # archivo» o al volver de Google, y en los dos casos lo que hace falta saber
    # es que lo anterior no se perdió. Sale de `guardados`, sin ninguna clave de
    # aviso: el propio estado lo dice todo.
    if st.session_state.archivo is None and st.session_state.guardados:
        st.success(
            f"Llevas **{len(st.session_state.guardados)} eventos** guardados. Sube "
            "otra tabla —de actividades o de videoconferencias— y al final se "
            "exportan todos juntos.",
            icon="✅",
        )

    subido = st.file_uploader(
        "Arrastra aquí el PDF, el CSV o el Excel",
        type=["pdf", "csv", "xlsx", "xlsm", "xls", "ods", "tsv", "txt"],
        label_visibility="collapsed",
        key=f"subida_{st.session_state.ronda_subida}",
    )
    # El contenido se guarda en la sesión, no se lee del widget: así el archivo
    # sobrevive a los reinicios de página (por ejemplo al volver de Google).
    if subido is not None:
        st.session_state.archivo = (subido.getvalue(), subido.name)

    archivo = st.session_state.archivo
    if archivo is None:
        nota(
            "<b>Lo más rápido: sube el PDF del plan de trabajo tal como te lo dieron.</b> "
            "La app busca dentro sus tablas —las actividades y las videoconferencias— y "
            "te enseña las que encontró para que elijas cuál pasar al calendario."
            "<br><br>"
            "¿Ya tienes la tabla por separado, en <b>CSV o Excel</b>? También sirve, y no "
            "importa si arriba hay filas de título ni si las celdas de «Unidad» están "
            "combinadas."
        )
        return None

    if subido is None:
        izq, der = st.columns([3, 2])
        izq.caption(f"📄 Trabajando con **{archivo[1]}**")
        # El «Añadir otro archivo» de más abajo vacía el mismo recuadro pero
        # conservando los eventos, así que aquí hay que decir en qué se
        # diferencian o se pulsa el que no era.
        if der.button(
            "Quitar archivo",
            width="stretch",
            help="Descarta este archivo y los eventos de su tabla. Para subir "
                 "otro **sin perderlos**, usa «➕ Añadir otro archivo».",
        ):
            olvidar_archivo()
            st.rerun()
    return archivo


def boton_otro_archivo(actuales: list[Evento]) -> None:
    """Cierra el paso 1 ofreciendo cargar otro archivo sin perder lo hecho.

    Es el caso de quien trae las actividades y las videoconferencias en archivos
    distintos: dentro de un PDF las dos tablas se marcan a la vez, pero con CSV
    hay que subirlas una por una. Mueve lo que hay en los editores a `guardados`
    y libera el `file_uploader`; el archivo nuevo propondrá su propio tipo.

    Se dibuja al final del ciclo aunque su hueco esté arriba: cuántos eventos hay
    no se sabe hasta el paso 3.
    """
    if not actuales:
        return
    total = len(st.session_state.guardados) + len(actuales)
    if st.button(
        f"➕ Añadir otro archivo (conservo los {total} eventos que llevas)",
        type="tertiary",
        help="Guarda lo que llevas y vacía el recuadro de arriba para que subas "
             "la otra tabla. Al final se exportan todas juntas.",
    ):
        st.session_state.guardados = st.session_state.guardados + actuales
        # Vaciar el widget es imprescindible: si no, vuelve a cargar el mismo
        # archivo y sus eventos se sumarían dos veces.
        olvidar_archivo()
        st.rerun()


@st.cache_data(show_spinner=False, max_entries=4)
def _tablas_del_pdf(datos: bytes, anio: int) -> list[planpdf.Candidata]:
    """Buscar las tablas tarda ~1 s y Streamlit reejecuta la página a cada clic."""
    return planpdf.extraer(datos, anio_defecto=anio)


def sugerir_materia(nombre: str) -> None:
    """Rellena el nombre de la materia con el que trae el plan de trabajo.

    Se hace desde aquí y no desde la barra lateral porque este paso corre antes
    de que se cree el `text_input`, y Streamlit no deja tocar la clave de un
    widget ya instanciado. Una sola vez por archivo y sólo si el campo está
    vacío: lo que escriba el usuario manda siempre.
    """
    if not nombre or st.session_state.materia_sugerida == st.session_state.firma_archivo:
        return
    st.session_state.materia_sugerida = st.session_state.firma_archivo
    if (st.session_state.get("materia") or "").strip():
        return
    st.session_state.materia = nombre
    st.info(
        f"Puse **{nombre}** como nombre de la materia, que es el que trae el plan. "
        "Si no es así, cámbialo en **⚙️ Ajustes**, a la izquierda.",
        icon="✏️",
    )


def _preseleccion(candidatas: list[planpdf.Candidata]) -> list[bool]:
    """Qué tablas del PDF vienen marcadas de entrada.

    Las actividades siempre: son a lo que viene todo el mundo. Las
    videoconferencias sólo si hay **una**; cuando el plan trae una tabla por
    grupo, marcar cualquiera sería meterle al alumno las sesiones del asesor
    equivocado, así que se le deja elegir la suya.
    """
    videos = sum(1 for c in candidatas if c.tipo == planpdf.TIPO_VIDEOCONFERENCIAS)
    return [c.tipo == planpdf.TIPO_ACTIVIDADES or videos == 1 for c in candidatas]


def paso_lectura_pdf(datos: bytes, nombre_archivo: str) -> list[TablaActiva]:
    """Enseña las tablas que trae el PDF y devuelve las que marcó el usuario."""
    if not planpdf.DISPONIBLE:
        st.error(
            "Falta la librería para leer PDF en este entorno. Instálala con "
            "`pip install pdfplumber`, o copia la tabla a Excel y sube ese archivo."
        )
        return []

    try:
        with st.spinner("Buscando las tablas del PDF…"):
            candidatas = _tablas_del_pdf(datos, ANIO_ACTUAL)
    except planpdf.ErrorDePDF as e:
        st.error(str(e))
        return []

    if not candidatas:
        st.error(
            "No encontré dentro del PDF ninguna tabla de actividades ni de "
            "videoconferencias. Copia la tabla a Excel o a Google Sheets y sube "
            "ese archivo.",
            icon="⚠️",
        )
        return []

    # Una casilla por tabla y no un `st.radio`: el plan trae las actividades y
    # las videoconferencias en tablas distintas y casi siempre se quieren las
    # dos. Se dibuja aunque sólo haya una candidata, porque marcarla y
    # desmarcarla es también la forma de decir «ésta no es».
    st.markdown("**¿Qué quieres pasar al calendario?** Marca una o varias.")
    marcadas: list[int] = []
    for i, (candidata, marcada) in enumerate(zip(candidatas, _preseleccion(candidatas))):
        # La clave lleva la firma del archivo: al cambiar de PDF, Streamlit poda
        # las de antes y la preselección se vuelve a calcular con las nuevas.
        clave = f"tabla_pdf_{st.session_state.firma_archivo}_{i}"
        # `value` sólo la primera vez, o Streamlit avisa de que el valor se está
        # fijando por dos vías.
        inicial = {} if clave in st.session_state else {"value": marcada}
        if st.checkbox(candidata.etiqueta(), key=clave, **inicial):
            marcadas.append(i)
    st.caption(
        "Se exportan juntas al final. Si alguna quedó del tipo equivocado, "
        "puedes corregirlo en el paso 2."
    )

    # La materia es dato del documento, no de la tabla: da igual cuál se marque.
    sugerir_materia(candidatas[0].materia)

    if not marcadas:
        st.warning("Marca al menos una tabla para seguir.", icon="⚠️")
        return []

    for i in marcadas:
        for aviso in candidatas[i].avisos:
            st.warning(f"{candidatas[i].nombre}: {aviso}", icon="⚠️")

    if len(marcadas) == 1:
        elegida = candidatas[marcadas[0]]
        st.success(
            f"Leí **{len(elegida.df)} filas** de «{elegida.nombre}» "
            f"({_rango(elegida.paginas)} del PDF).",
            icon="✅",
        )
    else:
        detalle = " + ".join(
            f"{len(candidatas[i].df)} de «{candidatas[i].nombre}»" for i in marcadas
        )
        total = sum(len(candidatas[i].df) for i in marcadas)
        st.success(f"Leí **{total} filas** en total: {detalle}.", icon="✅")

    activas = []
    for i in marcadas:
        candidata = candidatas[i]
        clave = firma(st.session_state.firma_archivo, "pdf", i)
        activas.append(TablaActiva(
            df=candidata.df,
            # `Candidata.modo` es la propuesta; manda lo que el usuario haya
            # dicho en el corrector del paso 2.
            modo=modo_de(clave, candidata.modo),
            nombre=candidata.nombre,
            origen=f"{nombre_archivo} · {candidata.nombre}",
            clave=clave,
            tipo_propuesto=candidata.modo,
        ))
    return activas


def _rango(paginas: list[int]) -> str:
    if len(paginas) == 1:
        return f"página {paginas[0]}"
    return f"páginas {min(paginas)} a {max(paginas)}"


def paso_lectura(datos: bytes, nombre: str) -> list[TablaActiva]:
    """Lee el archivo y devuelve las tablas con las que se va a trabajar.

    Un CSV o un Excel dan exactamente una; un PDF, tantas como marque el usuario.
    """
    nueva_firma = firma(nombre, len(datos))
    if nueva_firma != st.session_state.firma_archivo:
        st.session_state.firma_archivo = nueva_firma
        st.session_state.hoja = None
        st.session_state.fila_encabezado = None

    if planpdf.es_pdf(nombre):
        return paso_lectura_pdf(datos, nombre)

    hojas: list[str] = []
    if tablas.es_excel(nombre):
        try:
            hojas = tablas.listar_hojas(datos, nombre)
        except tablas.ErrorDeLectura as e:
            st.error(str(e))
            return []

    if hojas:
        cols = st.columns([2, 3])
        with cols[0]:
            indice = hojas.index(st.session_state.hoja) if st.session_state.hoja in hojas else 0
            elegida = st.selectbox("Hoja del Excel", hojas, index=indice)
        if elegida != st.session_state.hoja:
            st.session_state.hoja = elegida
            st.session_state.fila_encabezado = None

    try:
        lectura = tablas.cargar(
            datos, nombre,
            hoja=st.session_state.hoja,
            fila_encabezado=st.session_state.fila_encabezado,
        )
    except tablas.ErrorDeLectura as e:
        st.error(str(e))
        return []

    st.success(
        f"Tabla leída: **{len(lectura.df)} filas** y **{len(lectura.df.columns)} columnas**"
        + (f" de la hoja «{lectura.hoja}»" if lectura.hoja else ""),
        icon="✅",
    )
    # La pregunta va aquí, con la tabla ya leída, porque es lo que permite
    # proponer la respuesta; y después del selector de hoja, porque cada hoja del
    # Excel puede ser de un tipo distinto.
    clave = firma(st.session_state.firma_archivo, lectura.hoja)
    modo = selector_de_tipo_de_tabla(lectura.df, clave)
    return [TablaActiva(
        df=lectura.df,
        modo=modo,
        nombre=lectura.hoja or nombre,
        origen=nombre + (f" · {lectura.hoja}" if lectura.hoja else ""),
        clave=clave,
        fila_encabezado=lectura.fila_encabezado,
    )]


# --------------------------------------------------------------------------- #
# Paso 2 · Mapeo (sólo los campos del tipo elegido)
# --------------------------------------------------------------------------- #

# Una pestaña con el nombre entero del asesor dentro empuja a las demás fuera de
# la pantalla; lo que de verdad distingue una tabla de otra va antes.
_LARGO_PESTANIA = 40


def _recortar(texto: str, largo: int = _LARGO_PESTANIA) -> str:
    if len(texto) <= largo:
        return texto
    return texto[:largo].rsplit(" ", 1)[0].rstrip(" ·") + "…"


def etiquetas_de_pestania(activas: list[TablaActiva]) -> list[str]:
    """Nombres para las pestañas: cortos y sin repetidos.

    Dos tablas del PDF pueden llamarse igual (dos de videoconferencias sin
    grupo ni asesor), y recortar puede hacer iguales dos que no lo eran, así
    que la desambiguación va después del recorte.
    """
    salida, vistos = [], {}
    for tabla in activas:
        base = _recortar(tabla.etiqueta)
        vistos[base] = vistos.get(base, 0) + 1
        salida.append(base if vistos[base] == 1 else f"{base} ({vistos[base]})")
    return salida


def corrector_de_tipo(tabla: TablaActiva) -> None:
    """Segunda oportunidad para el tipo de una tabla del PDF.

    En el PDF el tipo lo dice la propia tabla y no se pregunta en el paso 1, así
    que si `pdf.py` la clasificó mal —o si el plan trae una tabla rara— éste es
    el único sitio donde el usuario puede desmentirlo. Va fuera del desplegable
    de abajo: quien lo necesita es porque toda la pantalla le está hablando del
    tipo equivocado, y esconderlo sería dejarlo sin salida.

    No hace falta aplicar el cambio a mano: tocar el widget reejecuta la página,
    y el paso 1 vuelve a construir la tabla leyendo esta misma clave (`modo_de`).
    """
    clave = f"tipo_{tabla.clave}"
    inicial = ({} if clave in st.session_state
               else {"index": list(TIPOS).index(tabla.tipo_propuesto)})
    st.radio(
        "Tipo de esta tabla",
        list(TIPOS),
        format_func=lambda m: TIPOS[m]["etiqueta"],
        horizontal=True,
        key=clave,
        help="Lo saqué de la propia tabla del PDF. Cámbialo si me equivoqué.",
        **inicial,
    )


def campo_plantilla(modo: str) -> None:
    st.text_input(
        "Plantilla del título",
        value=PLANTILLAS[modo],
        help="Campos disponibles: {materia}, {unidad}, {titulo}. "
             "Los campos vacíos se omiten junto con su separador.",
        key=f"plantilla_{modo}",
    )


def paso_mapeo(activas: list[TablaActiva], dayfirst: bool) -> list[dict]:
    """Configuración manual de cada tabla; devuelve un mapeo por tabla."""
    paso(2, "Configuración manual", "opcional — sólo si algo salió mal")

    # La plantilla es una por tipo, no una por tabla, así que con dos tablas del
    # mismo tipo sólo la dibuja la primera: dos widgets con la misma clave
    # (`plantilla_<modo>`) serían un error de Streamlit, y dos plantillas
    # distintas para el mismo tipo de evento no significarían nada.
    primera_del_tipo: dict[str, int] = {}
    for i, tabla in enumerate(activas):
        primera_del_tipo.setdefault(tabla.modo, i)

    if len(activas) == 1:
        return [config_de_tabla(activas[0], dayfirst, None)]

    salida = []
    etiquetas = etiquetas_de_pestania(activas)
    for i, (tabla, pestania) in enumerate(zip(activas, st.tabs(etiquetas))):
        with pestania:
            dueña = primera_del_tipo[tabla.modo]
            salida.append(config_de_tabla(
                tabla, dayfirst, None if dueña == i else etiquetas[dueña]))
    return salida


def config_de_tabla(tabla: TablaActiva, dayfirst: bool,
                    plantilla_en: str | None) -> dict:
    """Mapeo de columnas de una tabla, y lo demás que se ajusta por tabla.

    `plantilla_en` nombra la pestaña donde vive la plantilla de este tipo, o es
    None si le toca dibujarla a ésta.
    """
    df = tabla.df
    modo = tabla.modo
    principales, opcionales = deteccion.campos_de(modo)

    if tabla.tipo_propuesto:
        corrector_de_tipo(tabla)

    # El modo entra en la clave porque cambia qué campos se piden, y el número
    # de columnas porque corregir la fila de títulos cambia la tabla entera.
    clave = firma(tabla.clave, modo, len(df.columns))
    if f"auto_{clave}" not in st.session_state:
        st.session_state[f"auto_{clave}"] = deteccion.detectar_columnas(df, dayfirst, modo)
    automatico = st.session_state[f"auto_{clave}"]

    total = len(principales) + len(opcionales)
    detectados = sum(1 for c in principales + opcionales if automatico.get(c))
    falta_fecha = not automatico.get("fecha")

    opciones = ["— ninguna —"] + list(df.columns)
    mapeo: dict[str, str | None] = {c: None for c in deteccion.CAMPOS}

    def selector(campo: str, contenedor):
        sugerida = automatico.get(campo)
        indice = opciones.index(sugerida) if sugerida in opciones else 0
        elegida = contenedor.selectbox(
            deteccion.etiqueta(campo, modo), opciones, index=indice,
            key=f"map_{campo}_{clave}",
        )
        return None if elegida == "— ninguna —" else elegida

    # Se abre solo cuando de verdad hace falta intervenir.
    resumen = (
        "⚠️ No encontré la columna de fechas — ábreme"
        if falta_fecha else
        f"🪄 Detecté {detectados} de {total} columnas automáticamente. "
        "Ábreme sólo si algo quedó mal."
    )
    with st.expander(resumen, expanded=falta_fecha):
        for campo, col in zip(principales, st.columns(len(principales))):
            mapeo[campo] = selector(campo, col)
        for campo, col in zip(opcionales, st.columns(len(opcionales))):
            mapeo[campo] = selector(campo, col)

        st.divider()
        # La plantilla del título vivía en la barra lateral; se mudó aquí al
        # poder haber dos tipos de evento abiertos a la vez, cada uno con la
        # suya.
        if plantilla_en is None:
            campo_plantilla(modo)
        else:
            st.caption(
                f"El título sale de la plantilla `{plantilla_de(modo)}`, la misma "
                f"para todas las tablas de este tipo. Se ajusta en «{plantilla_en}»."
            )

        st.divider()
        # En un PDF no hay «fila de títulos» que ajustar: los títulos los
        # reconstruye `pdf.py` al armar la tabla. Si algo salió torcido, lo que
        # sirve es marcar otra tabla en el paso 1 o corregir en el paso 3.
        if tabla.fila_encabezado is None:
            st.caption("Así quedó la tabla que saqué del PDF:")
            st.dataframe(df.head(4), width="stretch", hide_index=True)
        else:
            st.caption(
                "Si los nombres de las columnas de arriba se ven raros, la tabla no "
                "empieza donde creí. Corrige aquí en qué fila están los títulos:"
            )
            izq, der = st.columns([1, 3])
            nueva = izq.number_input(
                "Fila de los títulos",
                min_value=1, max_value=30, value=tabla.fila_encabezado + 1, step=1,
            )
            der.dataframe(df.head(4), width="stretch", hide_index=True)
            if nueva - 1 != tabla.fila_encabezado:
                st.session_state.fila_encabezado = int(nueva) - 1
                st.rerun()

    # No basta con que falte la columna de horario: en 12 de los 14 planes de
    # `testing_files/` la hora viene **dentro** de la de fecha («FECHA Y HORA»,
    # «20 de agosto de 2025 de 20:00 a 22:00 hrs»), y `parse_fecha` la saca de
    # ahí sin problema. Sin esta segunda comprobación el aviso saltaba en casi
    # todos los PDF —ahora que las videoconferencias vienen premarcadas— y
    # aconsejaba justo lo contrario de lo correcto.
    if (modo == MODO_HORA and not mapeo["hora"]
            and not deteccion.hay_horarios(df, mapeo["fecha"])):
        donde = ("aquí arriba" if tabla.tipo_propuesto
                 else "en el paso 1")
        st.warning(
            "Esta tabla no parece traer horarios. Si son entregas, cambia su tipo "
            f"a «Actividades y entregas» {donde}.",
            icon="⚠️",
        )
    return mapeo


# --------------------------------------------------------------------------- #
# Paso 3 · Revisión
# --------------------------------------------------------------------------- #

def columnas_editor(modo: str) -> list[str]:
    base = ["Incluir", "Título", "Fecha"]
    base += ["Inicio", "Fin"] if modo == MODO_HORA else ["Fecha final"]
    return base + ["Descripción", "Lugar", "Revisar"]


def _a_dataframe(eventos: list[Evento], modo: str) -> pd.DataFrame:
    datos = pd.DataFrame({
        "Incluir": [ev.valido for ev in eventos],
        "Título": [ev.titulo for ev in eventos],
        "Fecha": pd.to_datetime([ev.fecha_inicio for ev in eventos], errors="coerce"),
        "Fecha final": pd.to_datetime([ev.fecha_fin for ev in eventos], errors="coerce"),
        "Inicio": pd.Series([ev.hora_inicio for ev in eventos], dtype="object"),
        "Fin": pd.Series([ev.hora_fin for ev in eventos], dtype="object"),
        "Descripción": [ev.descripcion for ev in eventos],
        "Lugar": [ev.lugar for ev in eventos],
        "Revisar": [ev.problema for ev in eventos],
    })
    return datos[columnas_editor(modo)]


def _hora(valor) -> time | None:
    if isinstance(valor, time):
        return valor
    if isinstance(valor, datetime):
        return valor.time()
    return None


def _desde_dataframe(editado: pd.DataFrame, origen: str) -> list[Evento]:
    salida: list[Evento] = []
    for i, fila in editado.iterrows():
        if not bool(fila.get("Incluir")):
            continue
        fecha = fila.get("Fecha")
        if fecha is None or pd.isna(fecha):
            continue
        fin = fila.get("Fecha final")
        salida.append(Evento(
            titulo=str(fila.get("Título") or "").strip() or "Actividad",
            descripcion=str(fila.get("Descripción") or "").strip(),
            fecha_inicio=pd.Timestamp(fecha).date(),
            fecha_fin=None if fin is None or pd.isna(fin) else pd.Timestamp(fin).date(),
            hora_inicio=_hora(fila.get("Inicio")),
            hora_fin=_hora(fila.get("Fin")),
            lugar=str(fila.get("Lugar") or "").strip(),
            origen=origen,
            fila=int(i) + 1,
        ))
    return salida


CONFIG_COLUMNAS = {
    "Incluir": lambda: st.column_config.CheckboxColumn("✓", width="small", default=True),
    "Título": lambda: st.column_config.TextColumn(width="large", required=True),
    "Fecha": lambda: st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
    "Fecha final": lambda: st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
    "Inicio": lambda: st.column_config.TimeColumn(format="HH:mm", width="small"),
    "Fin": lambda: st.column_config.TimeColumn(format="HH:mm", width="small"),
    "Descripción": lambda: st.column_config.TextColumn(width="large"),
    "Lugar": lambda: st.column_config.TextColumn(width="small"),
    "Revisar": lambda: st.column_config.TextColumn("⚠️", disabled=True, width="medium"),
}


def paso_revision(activas: list[TablaActiva], mapeos: list[dict],
                  ajustes: dict) -> list[Evento]:
    """Muestra los eventos de cada tabla abierta y devuelve la unión editada."""
    por_tabla = [
        construir_eventos(
            tabla.df, mapeo,
            materia=ajustes["materia"],
            plantilla=plantilla_de(tabla.modo),
            dayfirst=ajustes["dayfirst"],
            anio_defecto=ajustes["anio_defecto"],
            modo=tabla.modo,
            duracion_horas=ajustes["duracion"],
            rellenar_unidad=ajustes["rellenar"],
            origen=tabla.origen,
        )
        for tabla, mapeo in zip(activas, mapeos)
    ]

    listos = sum(1 for eventos in por_tabla for e in eventos if e.valido)
    con_problema = sum(len(eventos) for eventos in por_tabla) - listos
    paso(3, "Revisa los eventos",
         f"opcional — {listos} listos" + (f", {con_problema} por revisar" if con_problema else ""))

    if len(activas) == 1:
        return editor_de_tabla(activas[0], por_tabla[0], ajustes)

    salida: list[Evento] = []
    pestanias = st.tabs(etiquetas_de_pestania(activas))
    for tabla, eventos, pestania in zip(activas, por_tabla, pestanias):
        with pestania:
            salida.extend(editor_de_tabla(tabla, eventos, ajustes))
    return salida


def editor_de_tabla(tabla: TablaActiva, eventos: list[Evento],
                    ajustes: dict) -> list[Evento]:
    if not eventos:
        st.warning(
            "No encontré filas con datos. Abre «Configuración manual» arriba y revisa "
            "que las columnas apunten a donde deben.",
            icon="⚠️",
        )
        return []

    listos = sum(1 for e in eventos if e.valido)
    con_problema = len(eventos) - listos
    st.caption(
        f"{tabla.etiqueta} · {len(tabla.df)} filas leídas, {listos} eventos listos"
        + (f", {con_problema} por revisar" if con_problema else "")
    )

    if con_problema:
        st.warning(
            f"{con_problema} fila(s) sin fecha que yo entienda; están desmarcadas y no "
            "se exportarán. Escribe la fecha correcta en la tabla y se incluyen solas.",
            icon="⚠️",
        )

    # La clave lleva todo lo que cambia el contenido del editor: si no, Streamlit
    # conserva las ediciones de la tabla anterior y las aplica a filas que ya no
    # son las mismas.
    clave = firma(tabla.clave, tabla.modo, len(eventos),
                  plantilla_de(tabla.modo), ajustes["materia"])
    editado = st.data_editor(
        _a_dataframe(eventos, tabla.modo),
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        key=f"editor_{clave}",
        column_config={c: CONFIG_COLUMNAS[c]() for c in columnas_editor(tabla.modo)},
    )
    return _desde_dataframe(editado, tabla.origen)


# --------------------------------------------------------------------------- #
# Paso 4 · Exportar
# --------------------------------------------------------------------------- #

def paso_exportar(ajustes: dict, actuales: list[Evento]) -> None:
    """Todo junto: lo guardado de archivos anteriores y las tablas abiertas.

    `actuales` ya viene siendo la unión de todas las tablas activas, así que
    aquí no queda ninguna decisión de qué incluir: lo que se ve en el paso 3 se
    exporta.
    """
    eventos: list[Evento] = st.session_state.guardados + actuales
    dia = sum(1 for e in eventos if e.todo_el_dia)
    hora = len(eventos) - dia
    resumen = " + ".join(
        p for p in (f"{dia} actividades" if dia else "",
                    f"{hora} sesiones" if hora else "") if p
    )
    paso(4, "Manda todo a tu calendario", resumen, activo=bool(eventos))

    if not eventos:
        nota("Sube un archivo arriba y aquí aparecerán las opciones para mandarlo "
             "a tu calendario.")
        return

    if st.session_state.guardados:
        st.caption(
            f"Incluye {len(st.session_state.guardados)} eventos que ya habías "
            "cargado antes."
        )

    _, der = st.columns([3, 2])
    with der:
        if st.button("🗑️ Quitar todos los eventos", width="stretch"):
            st.session_state.guardados = []
            olvidar_archivo()
            st.rerun()

    with st.expander(f"📋 Ver los {len(eventos)} eventos que se van a crear"):
        st.dataframe(
            pd.DataFrame([{
                "Título": ev.titulo,
                "Cuándo": ev.resumen_fecha(),
                "Tipo": "Todo el día" if ev.todo_el_dia else "Con horario",
                "Origen": ev.origen,
            } for ev in eventos]),
            width="stretch", hide_index=True,
        )

    directo, ics, enlaces, csv_google = st.tabs([
        "🚀 Enviar a Google Calendar", "📅 Descargar archivo .ics",
        "🔗 Enlaces (sirve en celular)", "📄 CSV de Google",
    ])

    with directo:
        pestania_envio_directo(eventos, ajustes)

    with ics:
        st.markdown(
            "El `.ics` es la opción más segura: respeta horarios y recordatorios, y si "
            "vuelves a importarlo **actualiza** los eventos en vez de duplicarlos."
        )
        st.download_button(
            "📥 Descargar .ics",
            data=exportar.a_ics(
                eventos,
                zona=ajustes["zona"],
                duracion_horas=ajustes["duracion"],
                recordatorio_min=ajustes["recordatorio"],
                nombre_calendario=ajustes["materia"] or "Actividades",
            ),
            file_name=exportar.nombre_archivo(ajustes["materia"], "ics"),
            mime="text/calendar",
            type="primary",
            width="stretch",
        )
        st.markdown(
            "**Cómo importarlo:** entra a [calendar.google.com](https://calendar.google.com) "
            "en la computadora → ⚙️ **Configuración** → **Importar y exportar** → elige el "
            "archivo, selecciona el calendario destino y pulsa **Importar**."
        )

    with enlaces:
        st.markdown(
            "Cada liga abre Google Calendar con el evento **ya llenado**; sólo pulsas "
            "*Guardar*. No pide ningún permiso y **es la única opción que funciona desde "
            "el celular** (Google sólo deja importar archivos desde computadora).\n\n"
            "A cambio, es un evento a la vez: para muchos eventos conviene más el `.ics`."
        )
        st.dataframe(
            pd.DataFrame([{
                "Evento": ev.titulo,
                "Cuándo": ev.resumen_fecha(),
                "Añadir": exportar.enlace_google(ev, ajustes["zona"], ajustes["duracion"]),
            } for ev in eventos if ev.valido]),
            width="stretch",
            hide_index=True,
            column_config={
                "Evento": st.column_config.TextColumn(width="large"),
                "Añadir": st.column_config.LinkColumn(
                    "Abrir", display_text="➕ Añadir", width="small"
                ),
            },
        )

    with csv_google:
        st.markdown(
            "Úsalo sólo si el `.ics` te falla. Google interpreta las fechas del CSV según "
            "el idioma de tu cuenta; si los eventos caen en el día equivocado, cambia el "
            "formato aquí abajo y vuelve a importar."
        )
        etiqueta = st.selectbox("Formato de fecha", list(exportar.FORMATOS_CSV))
        st.download_button(
            "📥 Descargar CSV",
            data=exportar.a_csv_google(
                eventos, exportar.FORMATOS_CSV[etiqueta], ajustes["duracion"]
            ),
            file_name=exportar.nombre_archivo(ajustes["materia"], "csv"),
            mime="text/csv",
            width="stretch",
        )


def pestania_envio_directo(eventos: list[Evento], ajustes: dict) -> None:
    cfg = config_google()
    if not cfg:
        st.info(
            "El envío directo no está configurado en esta instalación. Usa la pestaña "
            "**Descargar archivo .ics** — hace exactamente lo mismo.",
            icon="ℹ️",
        )
        with st.expander("¿Por qué no aparece el botón?"):
            st.markdown(AYUDA_SIN_CONFIGURAR)
        return

    if not st.session_state.credenciales:
        st.warning("Primero conéctate con Google desde la barra lateral.", icon="🔗")
        return

    try:
        calendarios = gcal.listar_calendarios(st.session_state.credenciales)
    except gcal.SesionCaducada as e:
        st.warning(str(e), icon="⏱️")
        if st.button("Reconectar con Google", type="primary"):
            for clave in ("credenciales", "correo_google"):
                st.session_state.pop(clave, None)
            st.rerun()
        return
    except gcal.ErrorGoogle as e:
        st.error(str(e))
        return

    nombres = [c["nombre"] + (" (principal)" if c["principal"] else "") for c in calendarios]
    materia = (ajustes["materia"] or "").strip()

    # Un calendario propio para la materia va primero y elegido por omisión: al
    # acabar el semestre se oculta o se borra entero sin tocar lo demás. Se pone
    # siempre primero (no sólo si hay materia) para que el orden de la lista no
    # dependa de si el campo de la barra lateral ya se aplicó.
    nuevo = "➕ Crear un calendario nuevo para esta materia"
    opciones = [nuevo] + nombres

    izq, der = st.columns([3, 2])
    with izq:
        elegido = st.selectbox("¿A qué calendario?", opciones)
        nombre_nuevo = materia
        if elegido == nuevo:
            # Editable aquí mismo: así no hay que volver a la barra lateral ni
            # confirmar nada allá para que este nombre sea el correcto.
            nombre_nuevo = st.text_input(
                "Nombre del calendario nuevo",
                value=materia or "Actividades SUAyED",
                key=f"nombre_calendario_{materia}",
            )
    with der:
        evitar = st.checkbox("No duplicar eventos que ya existan", value=True)
        st.caption(f"Zona horaria: **{ajustes['zona']}**")

    validos = [ev for ev in eventos if ev.valido]
    if st.button(f"🚀 Crear {len(validos)} eventos en Google Calendar",
                 type="primary", width="stretch"):
        with st.status("Conectando con Google…", expanded=True) as estado:
            try:
                if elegido == nuevo:
                    estado.update(label="Creando el calendario…")
                    calendario_id = gcal.crear_calendario(
                        st.session_state.credenciales,
                        nombre_nuevo or "Actividades SUAyED",
                        ajustes["zona"],
                    )
                else:
                    calendario_id = calendarios[nombres.index(elegido)]["id"]

                barra = st.progress(0.0)

                def avance(i, total, titulo):
                    barra.progress(i / total, text=f"{i}/{total} · {titulo[:60]}")

                estado.update(label="Creando eventos…")
                resultado = gcal.insertar_eventos(
                    st.session_state.credenciales,
                    calendario_id,
                    validos,
                    zona=ajustes["zona"],
                    duracion_horas=ajustes["duracion"],
                    recordatorio_min=ajustes["recordatorio"],
                    evitar_duplicados=evitar,
                    progreso=avance,
                )
            except gcal.ErrorGoogle as e:
                estado.update(label="Falló el envío", state="error")
                st.error(str(e))
                return

            estado.update(label="Listo", state="complete")

        st.success(
            f"Se crearon **{resultado['creados']}** eventos"
            + (f" y se omitieron {resultado['omitidos']} que ya existían"
               if resultado["omitidos"] else "")
            + ".",
            icon="🎉",
        )
        st.balloons()
        if resultado["errores"]:
            with st.expander(f"{len(resultado['errores'])} evento(s) fallaron"):
                for error in resultado["errores"]:
                    st.write("- " + error)
        st.link_button("Abrir Google Calendar", "https://calendar.google.com")


# --------------------------------------------------------------------------- #
# Principal
# --------------------------------------------------------------------------- #

def main() -> None:
    estilos()
    arrancar_estado()

    # Antes que nada y antes de dibujar nada: si se pidió empezar de nuevo,
    # aquí es donde se puede borrar el estado sin chocar con ningún widget.
    if st.session_state.pop("reiniciar_pendiente", False):
        reiniciar_sesion()

    # Si el usuario viene de autorizar en Google, se procesa antes de dibujar
    # nada: así lo que traía recuperado ya está disponible para toda la página.
    cfg_google = config_google()
    if cfg_google:
        procesar_regreso_oauth(cfg_google)
    despedir_ventana_emergente()
    recoger_credenciales_de_la_emergente()
    boton_puente_oauth(bool(cfg_google))

    st.markdown(
        """
        <div class="bloque-titulo">
          <h1>📅 Exportar Plan de Trabajo a Google Calendar</h1>
          <p>Sube el plan de trabajo de tu materia y pasa las entregas y las
             videoconferencias a tu calendario en un par de clics. Sin instalar nada.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    restaurados = st.session_state.pop("aviso_restaurado", 0)
    if restaurados:
        st.success(
            f"Listo, ya estás conectado. Tus {restaurados} eventos siguen aquí.",
            icon="✅",
        )

    # «Empezar de nuevo» y «Conectar con Google» van arriba de todo en la barra
    # lateral, pero se dibujan al final: el primero necesita saber si hay
    # archivo abierto (lo carga `paso_archivo`, más abajo) y el segundo, qué
    # eventos preservar durante el viaje a Google. Se reservan los huecos ahora
    # y se rellenan después.
    contenedor_reinicio = st.sidebar.container()
    contenedor_google = st.sidebar.container()
    contenedor_ajustes = st.sidebar.container()

    archivo = paso_archivo()
    activas: list[TablaActiva] = []
    hueco_otro_archivo = None
    if archivo is not None:
        activas = paso_lectura(*archivo)
        # «Añadir otro archivo» cierra el paso 1, pero no puede dibujarse aún:
        # cuántos eventos hay no se sabe hasta el paso 3. Se le reserva el hueco
        # y se rellena al final del ciclo.
        hueco_otro_archivo = st.container()

    # La barra lateral va después del paso 1 porque necesita saber si alguna de
    # las tablas abiertas trae horario; y antes del paso 2, que usa su `dayfirst`.
    with contenedor_ajustes:
        ajustes = barra_lateral(hay_sesiones_con_horario(activas), dibujar_google=False)

    actuales: list[Evento] = []
    if activas:
        mapeos = paso_mapeo(activas, ajustes["dayfirst"])
        actuales = paso_revision(activas, mapeos, ajustes)
    else:
        paso(2, "Configuración manual", "opcional", activo=False)
        paso(3, "Revisa los eventos", "opcional", activo=False)

    paso_exportar(ajustes, actuales)

    if hueco_otro_archivo is not None:
        with hueco_otro_archivo:
            boton_otro_archivo(actuales)

    with contenedor_reinicio:
        boton_empezar_de_nuevo()
    with contenedor_google:
        panel_google(actuales)
        st.divider()
    with st.sidebar:
        pie_lateral()

    with st.expander("❓ Preguntas frecuentes"):
        st.markdown(
            """
**¿Tengo que confirmar algo para que se creen los eventos?**
No. Todo lo que ves en el paso 3 ya está incluido; ve directo al paso 4 y elige
cómo mandarlo a tu calendario.

**Tengo las actividades y las videoconferencias en tablas separadas.**
Si las dos vienen dentro del mismo PDF, márcalas juntas en el paso 1 y listo.
Si están en archivos distintos, sube el primero y al terminar el paso 1 pulsa
**«➕ Añadir otro archivo»**: se guarda lo que llevas y puedes subir el otro. Al
final se exportan juntas.

**Me equivoqué y quiero empezar de cero.**
En el paso 4, **«Quitar todos los eventos»**.

**¿En qué se diferencian «Quitar archivo» y «➕ Añadir otro archivo»?**
Los dos vacían el recuadro del paso 1, pero **«Quitar archivo» descarta** los
eventos de la tabla que tienes abierta —es el botón para cuando subiste el que
no era— y **«➕ Añadir otro archivo» los conserva**, que es el que quieres si vas
a sumar una segunda tabla. Lo que ya estaba guardado de archivos anteriores no
lo toca ninguno de los dos.

**¿Puedo subir el plan de trabajo en PDF, sin tocarlo?**
Sí, es lo más rápido. La app busca dentro sus tablas y te las enseña con una
casilla cada una para que marques las que quieras. Si prefieres, también acepta
la tabla ya pasada a CSV o Excel.

**Me salen varias tablas de videoconferencias.**
Tu plan trae un grupo por asesor, así que no marco ninguna: elige la de tu
asesor, que aparece con su nombre al lado del número de grupo.

**Marqué una tabla y la trata como si fuera del otro tipo.**
En el paso 2, arriba de «Configuración manual», cambia el **tipo de esa tabla**.
Si el archivo es CSV o Excel, el tipo se cambia en el paso 1.

**Subí el PDF y no encontró mis tablas.**
Puede que tu plan venga con un formato que la app todavía no reconoce, o que el
PDF sea una imagen escaneada (una foto de la hoja, sin texto que se pueda
copiar). Copia la tabla, pégala en Excel o Google Sheets y sube ese archivo: de
ahí en adelante todo funciona igual.

**No me lee bien el Excel.**
Abre **«Configuración manual»** en el paso 2: ahí puedes corregir en qué fila
están los títulos de las columnas y qué es cada una. Si tu archivo es `.xls`
viejo, ábrelo en Excel y guárdalo como `.xlsx`.

**Las fechas salieron en el día equivocado.**
En la barra lateral, dentro de «Ajustes avanzados», cambia si `03/04/2026` debe
leerse como día/mes o mes/día. También puedes corregir cualquier fecha a mano en
la tabla del paso 3.

**Mi plan trae las fechas sin año** («21 de agosto»).
Pon el año correcto en «Año para fechas escritas sin año».

**No aparece el botón de enviar a Google.**
Esa parte la configura quien publica la app (ver `docs/DESPLIEGUE.md`). Mientras
tanto, descarga el `.ics`: el resultado es idéntico.

**Ya importé y quiero volver a hacerlo.**
Vuelve a importar el mismo `.ics`: Google reconoce los eventos y los actualiza en
lugar de duplicarlos. Si usas el envío directo, deja marcada la casilla
«No duplicar eventos que ya existan».

**¿Se guarda mi información?**
No. El archivo se procesa en memoria mientras usas la página y no se almacena.
El permiso de Google sólo se usa para crear los eventos que confirmes.
            """
        )

    # Ya no queda nada que pueda reejecutar y tragarse el script, así que aquí
    # es donde se cierra la emergente si la recogida acaba de conectar. Sigue
    # siendo el mismo ciclo: se cierra en cuanto el usuario autoriza, no en la
    # siguiente vez que toque algo.
    cerrar_emergente_desde_el_abridor()

    # El sondeo va al final del todo, con la página ya dibujada: el permiso lo
    # trae la ventana emergente, que es otra sesión, y no hay forma de que el
    # servidor avise por su cuenta de que llegó. Volver a ejecutar cada dos
    # segundos es el sustituto pobre —pero sin dependencias— de ese aviso; si
    # estuviera arriba, la pausa retrasaría el dibujado entero.
    espera = st.session_state.get("esperando_oauth")
    if espera:
        if monotonic() - espera < ESPERA_OAUTH:
            sleep(2)
            st.rerun()
        # Se acabó la paciencia: se reejecuta una vez más para que vuelva a salir
        # el botón, porque si no la barra lateral se queda diciendo «termina de
        # autorizar» sin sondear ya nada. Y si el usuario autoriza más tarde no
        # se pierde nada: `recoger_credenciales_de_la_emergente` lo conecta en
        # cuanto toque cualquier cosa.
        st.session_state.pop("esperando_oauth", None)
        st.rerun()


if __name__ == "__main__":
    main()
