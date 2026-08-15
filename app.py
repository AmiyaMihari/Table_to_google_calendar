"""Exportar Plan de Trabajo a Google Calendar — aplicación Streamlit.

Tres pasos: subir el plan (PDF, CSV o Excel) y marcar qué tablas trae, revisar
y ajustar los eventos, y exportarlos a Google Calendar.

Todos los textos visibles van en tono impersonal y sin emojis: los lee gente sin
perfil técnico y la app tiene que sonar a instrucción, no a conversación.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import date, datetime, time
from html import escape
from pathlib import Path
# `time` aquí ya es `datetime.time`; para medir la espera de OAuth basta con
# esto, que además no se descuadra si cambia la hora del sistema.
from time import monotonic, sleep
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pandas as pd
import streamlit as st

from tabla_calendar import deteccion, exportar, ia, tablas
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
# Sin iconos: los dos tipos se distinguen por el texto, que es lo que hay que
# leer para elegir bien.
TIPOS = {
    MODO_DIA: {
        "corto": "Actividades",
        "etiqueta": "Actividades y entregas",
        "descripcion": "Tareas con fecha límite. Se crean como eventos de **todo el día**.",
        "plantilla": "Título de las actividades",
    },
    MODO_HORA: {
        "corto": "Videoconferencias",
        "etiqueta": "Videoconferencias y asesorías",
        "descripcion": "Sesiones con horario. Se crean como eventos **con hora de inicio y fin**.",
        "plantilla": "Título de las videoconferencias",
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
          /* El encabezado es presentación, no contenido: cuanto menos alto
             ocupe, antes se ve el paso 1. Y el texto va **sin `max-width`**,
             que era lo que lo partía en una columna angosta en medio de un
             recuadro ancho y vacío. */
          .bloque-titulo {
            background: linear-gradient(115deg, #4F46E5 0%, #7C3AED 55%, #DB2777 100%);
            color: #fff; border-radius: 12px; padding: 14px 20px; margin-bottom: 10px;
          }
          .bloque-titulo h1 {
            margin: 0; font-size: 1.4rem; font-weight: 700; letter-spacing: -.3px;
            line-height: 1.25;
          }
          .bloque-titulo p {
            margin: 4px 0 0; font-size: .9rem; opacity: .92; line-height: 1.4;
          }
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
          /* «Agregar otro calendario» en naranja, y sólo ése: la regla cuelga de
             la clave de su botón (`.st-key-<clave>`), así que ningún otro
             `type="primary"` —el de descargar el .ics, el de crear los eventos—
             se pinta de este color. El naranja es el oscuro (#C2410C) y no uno
             más vivo porque el texto va en blanco: con #EA580C el contraste se
             queda en 3.6:1 y no llega al mínimo legible. */
          .st-key-agregar_calendario button {
            background-color: #C2410C !important; border-color: #C2410C !important;
            color: #fff !important;
          }
          .st-key-agregar_calendario button:hover {
            background-color: #9A3412 !important; border-color: #9A3412 !important;
          }
          .st-key-agregar_calendario button:active,
          .st-key-agregar_calendario button:focus:not(:active) {
            background-color: #7C2D12 !important; border-color: #7C2D12 !important;
            box-shadow: none !important;
          }
          /* Streamlit escribe «Press Enter to apply» y no es configurable;
             se oculta y se sustituye por la versión en español. */
          div[data-testid="InputInstructions"] { visibility: hidden; position: relative; }
          div[data-testid="InputInstructions"]::after {
            content: "Enter o clic fuera para aplicarlo";
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
    # `guardados` son eventos que ya no cuelgan de ninguna tabla abierta y aun
    # así hay que exportar. Desde que se quitó «Añadir otro archivo» los llena un
    # solo sitio: `procesar_regreso_oauth`, que devuelve lo que la sesión llevaba
    # al salir a Google (la emergente es otra sesión y empieza en blanco). Los de
    # las tablas abiertas se calculan al vuelo y se suman al exportar, así que no
    # hay ningún botón de «confirmar» que pulsar.
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


def firma_de_archivo(datos: bytes, nombre: str) -> str:
    """Identidad del archivo cargado: **su contenido**, no sólo su nombre.

    De ella cuelga todo lo que la sesión recuerda por archivo: las claves de los
    widgets (por `TablaActiva.clave`), el `ia_fallo_` que impide reintentar una
    lectura que ya falló y el gasto apuntado en `usos_ia`. Con nombre y tamaño
    bastaba para distinguir dos archivos distintos, pero no dos versiones del
    mismo: un plan corregido que conservara el nombre y la longitud heredaba las
    elecciones del anterior —y su `ia_fallo_`, que le negaba la lectura con IA
    sin haberla intentado nunca—. Los bytes ya están en memoria y el md5 de un
    PDF cuesta milisegundos.
    """
    return firma(nombre, len(datos), hashlib.md5(datos).hexdigest())


# Lo único que sobrevive a «Agregar otro calendario»: volver a pasar por Google
# cuesta salir de la página, aceptar permisos y volver, y es justo lo que se
# quiere evitar cuando sólo se va a cargar el plan de otra materia.
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


def config_ia() -> dict | None:
    """Clave y modelo para leer el PDF con IA: Secrets, variable de entorno o env/.

    Sin clave la app funciona igual con el lector geométrico de `pdf.py`; la IA
    la configura quien publica la app y es quien paga sus tokens, así que aquí
    sólo se comprueba si existe.
    """
    if not ia.DISPONIBLE:
        return None
    return ia.leer_config(st.secrets) or ia.buscar_clave_local(RAIZ)


def config_admin() -> str | None:
    """La contraseña del panel de administración, si esta instalación tiene una.

    En la nube va en los Secrets (`[admin]` → `clave`); en local, en
    `env/admin_secret.json`. Sin ninguna de las dos el panel **no se dibuja**:
    lo que enseña es contabilidad de quien paga la clave de OpenAI, no algo que
    el estudiante deba encontrarse, y un panel sin llave sería peor que no
    tenerlo.
    """
    try:
        cfg = st.secrets.get("admin")
    except Exception:
        cfg = None
    if cfg:
        clave = str(cfg.get("clave", "")).strip()
        if clave:
            return clave
    return ia.buscar_clave_admin(RAIZ)


# --------------------------------------------------------------------------- #
# Las tablas activas — qué se está pasando al calendario ahora mismo
# --------------------------------------------------------------------------- #

@dataclass
class TablaActiva:
    """Una tabla en curso: la del CSV o el Excel, o cada tabla marcada del PDF.

    Es la unidad de trabajo de los pasos 2 y 3: cada una trae su tipo, su mapeo
    de columnas y su editor, y al exportar se suman todas.

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


def plantilla_de(modo: str) -> str:
    """La plantilla del título vigente para un tipo de evento.

    Vive en la clave del `text_input` que dibuja «Ajustes avanzados»
    (`plantilla_<modo>`), una por tipo y no una por tabla: dos tablas de
    videoconferencias son el mismo tipo de evento y titularlas distinto no
    tendría sentido. Está en la barra lateral y no en el paso 2 porque es jerga
    —`{materia} · {unidad} · {titulo}`— y en medio del flujo estorbaba.
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

    Con un PDF no se dibuja: allí el tipo lo trae escrito cada tabla
    (`Candidata.modo`, obra del lector) y lo anuncia el nombre con el que sale
    en su casilla — «Actividades — 13 filas…», «Videoconferencias · grupo 8596 ·
    …». Preguntarlo otra vez al lado de cada casilla obligaba a leer dos veces
    lo mismo, una a cada lado de la línea.
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
        "Tipo de tabla",
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

def campo_plantilla(modo: str) -> None:
    """Un campo por tipo de evento, dentro de «Ajustes avanzados»."""
    st.text_input(
        TIPOS[modo]["plantilla"],
        value=PLANTILLAS[modo],
        key=f"plantilla_{modo}",
    )


def hay_sesiones_con_horario(activas: list[TablaActiva]) -> bool:
    """¿Pinta algo la duración por omisión? Sólo si hay eventos con hora.

    Se miran las tablas abiertas **y** lo ya guardado: una sesión guardada en
    un archivo anterior también se exporta con esa duración.
    """
    return (any(t.modo == MODO_HORA for t in activas)
            or any(not ev.todo_el_dia for ev in st.session_state.guardados))


def barra_lateral(con_horario: bool, dibujar_google: bool = True) -> dict:
    """Los ajustes que valen para todas las tablas a la vez.

    Aquí dentro, en «Ajustes avanzados», vive también la plantilla del título:
    una por tipo de evento (`plantilla_<modo>`). Estuvo en el paso 2 mientras
    hizo falta una por tabla abierta, pero es jerga —lleva llaves y nombres de
    campo— y en medio del flujo distraía de lo único que hay que revisar ahí.
    """
    with st.container():
        st.markdown("### Ajustes")
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

            # Las dos plantillas, siempre visibles: una por tipo de evento, no
            # una por tabla. Se dibujan aquí aunque el archivo abierto sólo
            # traiga uno de los dos tipos, para que estén siempre en el mismo
            # sitio.
            st.caption(
                "Título de los eventos. Campos disponibles: `{materia}`, "
                "`{unidad}`, `{titulo}`; los vacíos se omiten con su separador."
            )
            for modo in TIPOS:
                campo_plantilla(modo)

            # El interruptor sólo existe si hay clave configurada: sin ella no
            # hay nada que apagar. `value` sólo la primera vez, o Streamlit
            # avisa de que el valor se fija por dos vías.
            cfg_ia = config_ia()
            if cfg_ia:
                inicial = {} if "usar_ia" in st.session_state else {"value": True}
                st.checkbox(
                    "Leer los PDF con inteligencia artificial",
                    key="usar_ia",
                    help=f"Un modelo de OpenAI ({cfg_ia['model']}) extrae las "
                         "tablas y resume cada actividad. Apagado, trabaja el "
                         "lector clásico, que no envía el PDF a ningún servicio.",
                    **inicial,
                )
                # El gasto de la sesión ya no se enseña aquí: quien sube su plan
                # no decide nada con esa cifra —la paga quien publica la app— y
                # ocupaba sitio en el único desplegable que sí toca abrir. Se
                # sigue apuntando (`usos_ia`, y el registro en disco) y se
                # consulta en «Administración», al fondo de la barra lateral.

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
# Administración — el gasto de la IA, para quien paga la clave
# --------------------------------------------------------------------------- #

# Cuántas filas de desglose caben en la barra lateral sin volverla un listado.
_FILAS_ADMIN = 6


def _linea_gasto(cubo: dict) -> str:
    """Una lectura del contador: lecturas, tokens y dólares."""
    lecturas = cubo["llamadas"]
    return (f"{lecturas} lectura{'' if lecturas == 1 else 's'} · "
            f"{cubo['entrada']:,} tokens de entrada + {cubo['salida']:,} de salida · "
            f"${cubo['costo']:.4f} USD")


def _desglose(titulo: str, filas: list, limite: int = _FILAS_ADMIN) -> None:
    """Un bloque compacto de «etiqueta · lecturas · dólares», ya recortado."""
    if not filas:
        return
    st.markdown(f"**{titulo}**")
    lineas = [f"{etiqueta} · {cubo['llamadas']} · ${cubo['costo']:.4f}"
              for etiqueta, cubo in filas[:limite]]
    if len(filas) > limite:
        lineas.append(f"y {len(filas) - limite} más")
    # Un solo `caption` con saltos de línea: seis `caption` seguidos separan
    # tanto que el bloque deja de leerse como una tabla.
    st.caption("  \n".join(lineas))


def resumen_de_gasto() -> None:
    """Lo que ha costado la lectura con IA: esta sesión y el registro en disco.

    Son dos cuentas distintas a propósito. `usos_ia` es lo que se pagó **en esta
    sesión** —lo que el dueño está viendo pasar ahora mismo— y el registro es lo
    acumulado por todas las sesiones del proceso, que es lo que hay que mirar
    para decidir si la clave sale cara.
    """
    usos = st.session_state.get("usos_ia", {})
    lecturas = [u for lista in usos.values() for u in lista]
    st.markdown("**Esta sesión**")
    if lecturas:
        sesion = {
            "llamadas": len(lecturas),
            "entrada": sum(u.entrada for u in lecturas),
            "salida": sum(u.salida for u in lecturas),
            "costo": sum(u.costo_usd or 0.0 for u in lecturas),
        }
        st.caption(f"{len(usos)} archivo{'' if len(usos) == 1 else 's'} · "
                   + _linea_gasto(sesion))
    else:
        st.caption("Sin lecturas con IA.")

    ruta = ia.ruta_registro(RAIZ)
    resumen = ia.resumir_registro(ia.leer_registro(ruta))
    st.markdown("**Acumulado**")
    if not resumen["total"]["llamadas"]:
        st.caption(f"El registro (`env/{ia.NOMBRE_REGISTRO}`) está vacío.")
        return
    st.caption(_linea_gasto(resumen["total"]))
    _desglose("Por día", resumen["por_dia"])
    _desglose("Por archivo", resumen["por_archivo"])
    st.caption(f"Origen: `env/{ia.NOMBRE_REGISTRO}`")


def panel_admin() -> None:
    """El panel de administración, al fondo de la barra lateral y bajo llave.

    Va detrás de todo lo demás y cerrado: no es parte del flujo de nadie que
    venga a pasar su plan al calendario. Sin contraseña configurada
    (`config_admin`) no se dibuja ni el desplegable.
    """
    clave = config_admin()
    if not clave:
        return
    with st.expander("Administración"):
        if not st.session_state.get("admin_abierto"):
            escrita = st.text_input("Contraseña", type="password", key="admin_clave")
            if not escrita:
                return
            # `compare_digest` y no `==`: comparar cadena a cadena termina en
            # cuanto encuentra la primera diferencia, y ese tiempo se puede
            # medir desde fuera para adivinar la contraseña letra a letra. Va
            # en bytes porque con `str` sólo admite ASCII: una contraseña con
            # eñe o acento —que en español es lo normal— reventaría la app con
            # un `TypeError`.
            if not hmac.compare_digest(escrita.encode("utf-8"), clave.encode("utf-8")):
                st.caption("Contraseña incorrecta.")
                return
            # Se sigue de largo en esta misma ejecución en vez de pedir un
            # `st.rerun()`: lo que hay que dibujar ya se puede dibujar, y un
            # ciclo más sólo añadiría un parpadeo.
            st.session_state.admin_abierto = True
        resumen_de_gasto()


# --------------------------------------------------------------------------- #
# Google
# --------------------------------------------------------------------------- #

AYUDA_SIN_CONFIGURAR = (
    "El envío directo necesita credenciales de Google que configura **una sola vez "
    "quien publica la app** — no vienen en el código porque son secretas.\n\n"
    "Para administrar esta instalación (ver `docs/DESPLIEGUE.md` → **Parte B**):\n\n"
    "- **En una computadora propia:** dejar el JSON descargado de Google Cloud "
    "dentro de la carpeta `env/`. La app lo encuentra solo.\n"
    "- **En Streamlit Cloud:** pegar el `client_id` y el `client_secret` en "
    "*Settings → Secrets*.\n\n"
    "Entretanto, **Descargar archivo .ics** hace exactamente lo mismo."
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


def boton_agregar_calendario() -> None:
    """Reinicio rápido, al principio de la barra lateral.

    Se llamó «Empezar de nuevo» y ahora dice **«Agregar otro calendario»**: la
    mecánica es la misma —`reiniciar_sesion` deja la app como recién abierta sin
    soltar la sesión de Google— pero el nombre viejo describía lo que se borra y
    no para qué se borra, que es pasar el plan de la siguiente materia. Va en
    naranja (`type="primary"` más la regla `.st-key-agregar_calendario` de
    `estilos()`) porque es lo que se busca al terminar con una materia y en gris
    no se encontraba.

    Sólo se dibuja cuando hay algo que reiniciar: en la primera visita no hace
    falta y quitaría protagonismo a «Conectar con Google», que ahí es lo que
    toca. Va arriba del todo porque cuando el usuario aún no se ha conectado el
    panel de Google es largo y empujaba el botón fuera de la pantalla.
    """
    if st.session_state.archivo is None and not st.session_state.guardados:
        return
    if st.button(
        "Agregar otro calendario",
        key="agregar_calendario",
        type="primary",
        width="stretch",
        help="Borra el archivo, los eventos y el nombre de la materia para "
             "empezar con otra. No cierra la sesión de Google.",
    ):
        # Se deja pendiente: en este ciclo los widgets ya están creados y
        # `reiniciar_sesion` borra sus claves.
        st.session_state.reiniciar_pendiente = True
        st.rerun()
    st.caption("Vacía el plan actual para pasar otra materia, sin volver a "
               "conectar Google.")
    st.divider()


def panel_google(actuales: list[Evento] | None = None) -> None:
    st.markdown("### Google Calendar")

    if not gcal.DISPONIBLE:
        st.warning("Faltan las librerías de Google en este entorno.")
        return

    cfg = config_google()
    if not cfg:
        st.info("Envío directo no disponible en esta instalación. Queda el `.ics`.")
        with st.expander("¿Por qué?"):
            st.markdown(AYUDA_SIN_CONFIGURAR)
            actual = url_base()
            if actual:
                st.caption("Al configurarlo, registrar este URI de redirección en Google Cloud:")
                st.code(actual, language=None)
        return

    # El regreso de Google ya se procesó al arrancar main().
    if st.session_state.credenciales:
        correo = st.session_state.get("correo_google", "")
        st.success(f"Conectado{f' como {correo}' if correo else ''}")
        if st.button("Desconectar", width="stretch"):
            for clave in ("credenciales", "correo_google"):
                st.session_state.pop(clave, None)
            st.rerun()
    elif st.session_state.get("esperando_oauth"):
        # Mientras dura el sondeo no se genera URL nueva: cada una deja un
        # `state` en el proceso y se llenaría de intentos que nadie va a usar.
        st.info(
            "Falta autorizar en la ventana emergente. Al aceptar, se cierra sola "
            "y esta página queda conectada, con el trabajo intacto."
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
            "¿No se abrió la ventana? Conectar en otra pestaña",
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
        'Google avisará de que <b>«no ha verificado esta aplicación»</b>. '
        'Es normal y se puede continuar:<br><br>'
        '1. Pulsar <b>Configuración avanzada</b><br>'
        '2. Después <b>Ir a Exportar Plan de Trabajo a Google Calendar</b>'
        '</div>',
        unsafe_allow_html=True,
    )
    with st.expander("¿Por qué sale ese aviso? ¿Es seguro?"):
        st.markdown(
            "Esa pantalla **no significa que la app sea peligrosa**. Google la "
            "muestra en toda aplicación que no haya pasado su proceso de "
            "verificación, un trámite que exige dominio propio y aviso de "
            "privacidad publicado; para un proyecto estudiantil no compensa.\n\n"
            "Qué se puede comprobar:\n\n"
            "- El archivo **no se guarda**: se procesa mientras la página está abierta.\n"
            "- El permiso sólo sirve para **crear los eventos exportados**.\n"
            "- Se puede retirar en cualquier momento desde "
            "[la cuenta de Google](https://myaccount.google.com/permissions).\n"
            "- El código es abierto y se puede revisar: "
            "[github.com/AmiyaMihari](https://github.com/AmiyaMihari/Table_to_google_calendar).\n\n"
            "Sin dar ningún permiso queda el `.ics` del paso 3: hace exactamente "
            "lo mismo."
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
    st.toast("Conexión lista. Si esta ventana no se cierra sola, se puede "
             "cerrar a mano y volver a la pestaña anterior.")
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
        st.toast("Conectado con Google")
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
    paso(1, "Subir el archivo", "el plan de trabajo en PDF, o la tabla en CSV o Excel")

    # Sin archivo y con eventos en el bolsillo sólo se llega al volver de Google
    # —la ventana emergente es otra sesión y `procesar_regreso_oauth` le
    # devuelve lo que había—, y lo que hace falta saber ahí es que lo anterior no
    # se perdió. Sale de `guardados`, sin ninguna clave de aviso: el propio
    # estado lo dice todo.
    if st.session_state.archivo is None and st.session_state.guardados:
        st.success(
            f"Hay **{len(st.session_state.guardados)} eventos** guardados. Al subir "
            "otra tabla —de actividades o de videoconferencias— se exportan todos "
            "juntos al final."
        )

    subido = st.file_uploader(
        "Arrastrar aquí el PDF, el CSV o el Excel",
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
            "<b>Lo más rápido es subir el PDF del plan de trabajo tal como lo "
            "entregaron.</b> La app busca dentro sus tablas —las actividades y las "
            "videoconferencias— y muestra las que encontró para elegir cuáles pasar "
            "al calendario."
            "<br><br>"
            "La tabla suelta en <b>CSV o Excel</b> también sirve, y no importa si "
            "arriba hay filas de título ni si las celdas de «Unidad» están combinadas."
        )
        return None

    if subido is None:
        izq, der = st.columns([3, 2])
        izq.caption(f"Archivo abierto: **{archivo[1]}**")
        if der.button(
            "Quitar archivo",
            width="stretch",
            help="Descarta este archivo y los eventos de su tabla. El resto de "
                 "los ajustes se conservan.",
        ):
            olvidar_archivo()
            st.rerun()
    return archivo


@st.cache_data(show_spinner=False, max_entries=4)
def _tablas_del_pdf(datos: bytes, anio: int) -> list[planpdf.Candidata]:
    """Buscar las tablas tarda ~1 s y Streamlit reejecuta la página a cada clic."""
    return planpdf.extraer(datos, anio_defecto=anio)


@st.cache_data(show_spinner=False, max_entries=4)
def _tablas_del_pdf_ia(datos: bytes, anio: int, clave: str,
                       modelo: str) -> tuple[ia.ResultadoIA, str]:
    """Una llamada al modelo por archivo, y ni una más: cada una cuesta dinero.

    El caché es lo que la garantiza: Streamlit reejecuta la página entera a cada
    clic, y sin él cada marca de una casilla volvería a pagar la extracción.

    Devuelve además una marca de llamada, que es lo único que distingue una
    respuesta recién pagada de una servida del caché: el cuerpo de esta función
    corre sólo cuando se falla el caché, así que la marca cambia exactamente
    cuando se paga. Sin ella no habría forma de contar el gasto —cada
    reejecución sumaría otra vez lo mismo, o, si se sobreescribe, la segunda
    llamada de un PDF expulsado del caché no sumaría nunca—.
    """
    texto = planpdf.texto_completo(datos)
    resultado = ia.extraer(texto, clave_api=clave, modelo=modelo, anio_defecto=anio)
    return resultado, uuid4().hex


def _leer_pdf_con_ia(datos: bytes, cfg: dict,
                     nombre_archivo: str) -> list[planpdf.Candidata] | None:
    """Intenta la lectura con IA; None significa «que lo haga el lector clásico».

    Un fallo se recuerda por archivo (`ia_fallo_<firma>`) y no se reintenta:
    reintentar en cada reejecución sería pagar la llamada una y otra vez contra
    el mismo error. El lector clásico toma el relevo, y si el PDF está dañado o
    escaneado será él quien dé el diagnóstico definitivo.

    `nombre_archivo` sólo sirve para el registro de gasto: la firma identifica
    al archivo dentro de la sesión, pero en un registro que se lee semanas
    después lo único reconocible es el nombre del plan.
    """
    firma_archivo = st.session_state.firma_archivo
    if st.session_state.get(f"ia_fallo_{firma_archivo}"):
        return None
    try:
        with st.spinner(f"Leyendo el PDF con IA ({cfg['model']})…"):
            resultado, marca = _tablas_del_pdf_ia(
                datos, ANIO_ACTUAL, cfg["api_key"], cfg["model"])
    except (ia.ErrorDeIA, planpdf.ErrorDePDF) as e:
        st.session_state[f"ia_fallo_{firma_archivo}"] = True
        st.warning(
            f"No se pudo leer el PDF con IA; lo leyó el lector clásico. Detalle: {e}"
        )
        return None

    # El gasto se apunta aunque el modelo no haya encontrado nada: ya se pagó.
    # Una llamada, un apunte: la marca dice si esta respuesta se acaba de pagar
    # o venía del caché, así que las reejecuciones no suman de más y un PDF que
    # el caché expulsó y hubo que volver a leer suma las dos veces. Por eso es
    # una lista por archivo y no un solo `Uso` que se sobreescribe.
    if marca not in st.session_state.setdefault("llamadas_ia", set()):
        st.session_state.llamadas_ia.add(marca)
        st.session_state.setdefault("usos_ia", {}).setdefault(firma_archivo, []).append(
            resultado.uso)
        # Y el mismo apunte en disco, que es lo que sobrevive a la sesión: la
        # contabilidad de quien paga la clave no puede vivir en un
        # `session_state` que se borra al cerrar la pestaña. Este es el único
        # punto del programa donde consta que se pagó una llamada.
        ia.apuntar_uso(resultado.uso, nombre_archivo, ia.ruta_registro(RAIZ))
    if not resultado.candidatas:
        st.session_state[f"ia_fallo_{firma_archivo}"] = True
        return None
    return resultado.candidatas


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
        f"Se tomó **{nombre}** como nombre de la materia, que es el que trae el "
        "plan. Se puede cambiar en **Ajustes**, a la izquierda."
    )


def _preseleccion(candidatas: list[planpdf.Candidata]) -> list[bool]:
    """Qué tablas del PDF vienen marcadas de entrada: sólo las de actividades.

    Las entregas son a lo que viene todo el mundo, y son las mismas para todos
    los grupos. Las videoconferencias **nunca** vienen marcadas, ni cuando el
    plan trae una sola tabla: a las sesiones en vivo va quien va, y meterlas en
    el calendario sin que nadie las haya pedido es peor que pedir un clic de
    más. Cuando el plan trae una tabla por grupo, además, marcar cualquiera
    sería colarle al alumno las sesiones del asesor equivocado.
    """
    return [c.tipo == planpdf.TIPO_ACTIVIDADES for c in candidatas]


def paso_lectura_pdf(datos: bytes, nombre_archivo: str) -> list[TablaActiva]:
    """Enseña las tablas que trae el PDF y devuelve las que marcó el usuario."""
    if not planpdf.DISPONIBLE:
        st.error(
            "Falta la librería para leer PDF en este entorno. Instálala con "
            "`pip install pdfplumber`, o copia la tabla a Excel y sube ese archivo."
        )
        return []

    # La IA primero, si está configurada y el usuario no la apagó. El valor de
    # `usar_ia` lo escribe un checkbox de la barra lateral que se dibuja después
    # de este paso; leerlo de la sesión trae el del ciclo anterior, y el propio
    # cambio del checkbox reejecuta la página, así que siempre converge.
    candidatas = None
    cfg_ia = config_ia() if st.session_state.get("usar_ia", True) else None
    if cfg_ia:
        candidatas = _leer_pdf_con_ia(datos, cfg_ia, nombre_archivo)
    # Si la IA cobró pero no sirvió (falló o no encontró nada), las tablas que
    # se enseñan abajo son del lector clásico y la nota de costo no debe
    # atribuírselas al modelo.
    leidas_con_ia = candidatas is not None
    # Qué lector armó estas candidatas entra en la clave de cada tabla: la
    # identidad de una tabla del PDF es su posición en la lista, y los dos
    # lectores no encuentran ni las mismas tablas ni en el mismo orden. Al
    # apagar `usar_ia` —o si la IA falla a media sesión— «la tabla 2» pasa a ser
    # otra, y sin esto heredaría la marca y el tipo corregido de la anterior.
    # Con el lector dentro, las claves viejas quedan huérfanas y Streamlit las
    # poda solas.
    lector = "ia" if leidas_con_ia else "geo"

    if candidatas is None:
        try:
            with st.spinner("Buscando las tablas del PDF…"):
                candidatas = _tablas_del_pdf(datos, ANIO_ACTUAL)
        except planpdf.ErrorDePDF as e:
            st.error(str(e))
            return []

    if not candidatas:
        st.error(
            "No se encontró dentro del PDF ninguna tabla de actividades ni de "
            "videoconferencias. Copiar la tabla a Excel o a Google Sheets y subir "
            "ese archivo."
        )
        return []

    # Una casilla por tabla y no un `st.radio`: el plan trae las actividades y
    # las videoconferencias en tablas distintas y casi siempre se quieren las
    # dos. Se dibuja aunque sólo haya una candidata, porque marcarla y
    # desmarcarla es también la forma de decir «ésta no es».
    # «Se exportan juntas al final» va aquí arriba y ya no de pie de la lista:
    # con el encabezado de grupos en medio, un `caption` al final parecía hablar
    # sólo de las videoconferencias.
    st.markdown(
        "**Tablas encontradas en el PDF.** Marcar las que se van a exportar; "
        "pueden ser varias y se exportan juntas al final."
    )
    preseleccion = _preseleccion(candidatas)
    marcadas: list[tuple[int, str]] = []

    def casilla(i: int) -> None:
        # La clave lleva la firma del archivo y el lector: al cambiar de PDF —o
        # de lector— Streamlit poda las de antes y la preselección se vuelve a
        # calcular con las nuevas. Lleva también el índice **en la lista
        # original**, así que agrupar las casillas por tipo no le cambia la
        # identidad a ninguna tabla ni le pasa la marca a otra.
        clave_marca = f"tabla_pdf_{st.session_state.firma_archivo}_{lector}_{i}"
        clave = firma(st.session_state.firma_archivo, "pdf", lector, i)
        # `value` sólo la primera vez, o Streamlit avisa de que el valor se está
        # fijando por dos vías.
        inicial = ({} if clave_marca in st.session_state
                   else {"value": preseleccion[i]})
        # Sin nada a la derecha: el tipo de cada tabla lo dice su propio nombre
        # («Actividades — …», «Videoconferencias · grupo 8596 · …») y un control
        # aparte repetía a la derecha lo que ya se lee a la izquierda.
        if st.checkbox(_etiqueta_candidata(candidatas[i]), key=clave_marca, **inicial):
            marcadas.append((i, clave))

    # Las casillas van agrupadas por tipo —primero las entregas, después las
    # sesiones— aunque en el PDF salgan intercaladas: lo que hay que decidir en
    # el segundo grupo no es si interesan las videoconferencias, sino **cuál de
    # los grupos es el propio**, y esa pregunta necesita su encabezado. Sin él,
    # tres o cuatro casillas casi idénticas parecen opciones repetidas.
    entregas = [i for i, c in enumerate(candidatas)
                if c.tipo == planpdf.TIPO_ACTIVIDADES]
    sesiones = [i for i, c in enumerate(candidatas)
                if c.tipo != planpdf.TIPO_ACTIVIDADES]
    for i in entregas:
        casilla(i)
    if sesiones:
        st.markdown("**Elegir el grupo que corresponda (opcional):**")
        for i in sesiones:
            casilla(i)

    # La materia es dato del documento, no de la tabla: da igual cuál se marque.
    sugerir_materia(candidatas[0].materia)

    if not marcadas:
        st.warning("Marcar al menos una tabla para continuar.")
        return []

    for i, _ in marcadas:
        for aviso in candidatas[i].avisos:
            st.warning(f"{candidatas[i].nombre}: {aviso}")

    # Aquí hubo un `st.success` con las filas que se leyeron de cada tabla
    # marcada y **se quitó**: la casilla que se acaba de marcar ya dice ese
    # mismo número y esas mismas páginas, así que el aviso verde no añadía nada
    # y empujaba las tablas hacia arriba, fuera de la vista.

    activas = []
    for i, clave in marcadas:
        candidata = candidatas[i]
        activas.append(TablaActiva(
            df=candidata.df,
            # El tipo lo decide el lector, que es quien distingue una tabla de
            # entregas de una de sesiones al reconocerla, y lo dice el nombre
            # con el que la tabla sale en su casilla.
            modo=candidata.modo,
            nombre=candidata.nombre,
            origen=f"{nombre_archivo} · {candidata.nombre}",
            clave=clave,
        ))
    return activas


def _etiqueta_candidata(candidata: planpdf.Candidata) -> str:
    """Cómo se presenta una tabla del PDF en su casilla, sin iconos.

    No se usa `Candidata.etiqueta()` porque ésa trae el icono del tipo. El tipo
    lo dice el nombre de la tabla, que es lo primero que se lee; el guión largo
    se conserva porque es lo que lo separa de su tamaño.
    """
    return (f"{candidata.nombre} — {len(candidata.df)} filas, "
            f"{_rango(candidata.paginas)}")


def _rango(paginas: list[int]) -> str:
    if not paginas:
        return "sin páginas"
    if len(paginas) == 1:
        return f"página {paginas[0]}"
    return f"páginas {min(paginas)} a {max(paginas)}"


def paso_lectura(datos: bytes, nombre: str) -> list[TablaActiva]:
    """Lee el archivo y devuelve las tablas con las que se va a trabajar.

    Un CSV o un Excel dan exactamente una; un PDF, tantas como marque el usuario.
    """
    nueva_firma = firma_de_archivo(datos, nombre)
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

    # Aquí hubo un `st.success` («Tabla leída: 12 filas y 4 columnas») y se quitó
    # junto con el del PDF: el mismo recuento sale dos veces más abajo —en el
    # subtítulo del paso 2 y en el `caption` que encabeza el editor— y las
    # columnas las cuenta el desplegable del mapeo («Se detectaron 6 de 6»). Lo
    # que aquí sí hace falta es la pregunta por el tipo, y un aviso verde encima
    # se la comía.
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
# Paso 2 · Revisar y ajustar (mapeo de columnas + editor, tabla por tabla)
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
        base = _recortar(tabla.nombre)
        vistos[base] = vistos.get(base, 0) + 1
        salida.append(base if vistos[base] == 1 else f"{base} ({vistos[base]})")
    return salida


def paso_revisar(activas: list[TablaActiva], ajustes: dict) -> list[Evento]:
    """Un solo paso para revisar: las columnas de cada tabla y sus eventos.

    Antes eran dos —«Configuración manual» y «Revisa los eventos»— y obligaban a
    subir y bajar entre el desplegable de una tabla y el editor de la misma
    tabla. Ahora cada pestaña trae las dos cosas, en ese orden.

    Devuelve la unión editada de todas las tablas abiertas.
    """
    # El encabezado dice cuántos eventos hay, y eso no se sabe hasta haberlos
    # construido: se le reserva el hueco y se rellena al final del paso (el
    # patrón de «Agregar otro calendario»). La nota de responsabilidad va en ese
    # mismo hueco, justo debajo del encabezado y encima de las pestañas.
    cabecera = st.container()

    sitios = ([st.container()] if len(activas) == 1
              else list(st.tabs(etiquetas_de_pestania(activas))))

    salida: list[Evento] = []
    listos = total = 0
    for tabla, sitio in zip(activas, sitios):
        with sitio:
            mapeo = config_de_tabla(tabla, ajustes["dayfirst"])
            eventos = construir_eventos(
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
            listos += sum(1 for e in eventos if e.valido)
            total += len(eventos)
            salida.extend(editor_de_tabla(tabla, eventos, ajustes))

    con_problema = total - listos
    with cabecera:
        paso(2, "Revisar y ajustar",
             f"{listos} eventos listos"
             + (f", {con_problema} por revisar" if con_problema else ""))
        # El único emoji de la interfaz además del favicon, y va aquí a
        # propósito: es la nota de responsabilidad, lo que separa «la app leyó el
        # plan» de «el plan está bien leído», y sin el triángulo se lee como un
        # aviso más de los muchos que puede haber en este paso.
        st.warning(
            "Verificar que no falte ninguna actividad ni sesión: la lectura "
            "automática puede fallar y la revisión final corre por cuenta de "
            "quien exporta.",
            icon="⚠️",
        )
    return salida


def config_de_tabla(tabla: TablaActiva, dayfirst: bool) -> dict:
    """Mapeo de columnas de una tabla; cerrado salvo que haga falta abrirlo."""
    df = tabla.df
    modo = tabla.modo
    principales, opcionales = deteccion.campos_de(modo)

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

    def selector(campo: str, contenedor, opcional: bool = False):
        sugerida = automatico.get(campo)
        indice = opciones.index(sugerida) if sugerida in opciones else 0
        etiqueta = deteccion.etiqueta(campo, modo)
        if opcional:
            etiqueta = _como_opcional(etiqueta)
        elegida = contenedor.selectbox(
            etiqueta, opciones, index=indice, key=f"map_{campo}_{clave}",
        )
        return None if elegida == "— ninguna —" else elegida

    # Se abre solo cuando de verdad hace falta intervenir.
    resumen = (
        "No se encontró la columna de fechas. Abrir para elegirla."
        if falta_fecha else
        f"Se detectaron {detectados} de {total} columnas. "
        "Abrir para elegirlas manualmente."
    )
    with st.expander(resumen, expanded=falta_fecha):
        for campo, col in zip(principales, st.columns(len(principales))):
            mapeo[campo] = selector(campo, col)

        # Los opcionales, aparte y marcados: «Liga (Zoom, Meet…) o aula» casi
        # nunca existe en la tabla de origen, y mezclado con los demás parecía un
        # campo que faltaba llenar. Las actividades ya no tienen ninguno, y
        # `st.columns(0)` revienta, así que el bloque entero es condicional.
        if opcionales:
            st.caption("Columnas opcionales; la mayoría de los planes no las traen.")
            for campo, col in zip(opcionales, st.columns(len(opcionales))):
                mapeo[campo] = selector(campo, col, opcional=True)

        # En un PDF no hay «fila de títulos» que ajustar —los títulos los
        # reconstruye `pdf.py` al armar la tabla—, así que aquí no queda nada más
        # que enseñar. Hubo una vista previa de la tabla extraída y **se quitó**:
        # el editor de eventos va justo debajo, con las mismas filas y además
        # editables, y ver la misma tabla dos veces seguidas hacía dudar de cuál
        # de las dos era la que cuenta.
        if tabla.fila_encabezado is not None:
            st.divider()
            st.caption(
                "Si los nombres de las columnas salen raros, la tabla empieza en "
                "otra fila. Indicar aquí en cuál están los títulos:"
            )
            izq, der = st.columns([1, 3])
            nueva = izq.number_input(
                "Fila de los títulos",
                min_value=1, max_value=30, value=tabla.fila_encabezado + 1, step=1,
            )
            # Ésta sí se queda: no repite el editor, sino la tabla **cruda**, que
            # es lo único con lo que se puede juzgar si los títulos son títulos.
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
        # A dónde mandar depende del archivo. En CSV y Excel el tipo es una
        # elección del usuario y se corrige con un clic en el paso 1; en el PDF
        # lo pone el lector al reconocer la tabla y no hay ningún control que
        # tocar, así que lo útil es revisar las horas abajo —o dejar la tabla
        # fuera si no era ésta—.
        if tabla.fila_encabezado is None:
            st.warning(
                "Esta tabla no parece traer horarios. Conviene revisar las horas "
                "en la lista de abajo; si no son sesiones, desmarcarla en el paso 1."
            )
        else:
            st.warning(
                "Esta tabla no parece traer horarios. Si son entregas, cambiar su "
                "tipo a «Actividades y entregas» en el paso 1."
            )
    return mapeo


def _como_opcional(etiqueta: str) -> str:
    """«Fecha final (eventos de varios días)» → «Fecha final (opcional)».

    Dos paréntesis seguidos no los lee nadie, así que la aclaración que ya trae
    la etiqueta cede el sitio a la que importa aquí: que el campo se puede dejar
    vacío. Sólo se sustituye si el paréntesis está al final; en «Liga (Zoom,
    Meet…) o aula» se queda donde está.
    """
    if etiqueta.endswith(")") and " (" in etiqueta:
        etiqueta = etiqueta[:etiqueta.rfind(" (")]
    return f"{etiqueta} (opcional)"


# --------------------------------------------------------------------------- #
# El editor de cada tabla, dentro del paso 2
# --------------------------------------------------------------------------- #

def columnas_editor(modo: str, con_problema: bool = False) -> list[str]:
    """Qué columnas enseña el editor de una tabla, y en qué orden.

    Una entrega no lleva ni «Fecha final» ni «Lugar»: el mapeo del paso 2 ya no
    pide esas columnas, así que saldrían siempre vacías. Los eventos de varios
    días que salen de un rango escrito en una sola celda («del 20 al 25 de
    octubre») se siguen exportando con su fecha final; lo que desapareció es la
    columna, no el dato (ver `_desde_dataframe`).

    «Revisar» sólo existe si hay algo que revisar. Es la única forma de avisar de
    una fila que se quedó sin fecha, pero con todo en orden era una columna vacía
    y sin explicación en cada tabla, y nadie entendía qué se le pedía.
    """
    base = ["Incluir", "Título", "Fecha"]
    if modo == MODO_HORA:
        base += ["Inicio", "Fin"]
    base += ["Descripción"]
    if modo == MODO_HORA:
        base += ["Lugar"]
    return base + (["Revisar"] if con_problema else [])


def _a_dataframe(eventos: list[Evento], modo: str,
                 con_problema: bool = False) -> pd.DataFrame:
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
    # El índice se enseña (`hide_index=False`), y numerado desde 1: es lo que
    # dice de un vistazo cuántas actividades trae la tabla, sin tener que
    # contarlas ni bajar al pie. Sigue siendo un `RangeIndex`, así que
    # `num_rows="dynamic"` puede seguir añadiendo filas —las numera N+1, N+2…—
    # sin pedirle al usuario que invente el índice.
    datos.index = pd.RangeIndex(1, len(datos) + 1)
    return datos[columnas_editor(modo, con_problema)]


def _hora(valor) -> time | None:
    if isinstance(valor, time):
        return valor
    if isinstance(valor, datetime):
        return valor.time()
    return None


def _desde_dataframe(editado: pd.DataFrame, origen: str,
                     originales: list[Evento]) -> list[Evento]:
    """Vuelve a armar los eventos con lo que quedó en el editor.

    `originales` es lo que se le dio a dibujar, y sirve para recuperar la **fecha
    final** de las tablas de actividades, que ya no tienen columna para ella: un
    rango escrito en una sola celda («del 20 al 25 de octubre») produce un evento
    de varios días, y el `.ics` y Google Calendar lo pintan entero. Sin esto, dar
    la vuelta por el editor lo convertiría en un evento de un día.

    El índice del editor es 1..N y `num_rows="dynamic"` conserva el de cada fila
    que ya existía —las nuevas siguen contando desde N+1—, así que es lo que
    empareja cada fila con su evento de origen.
    """
    salida: list[Evento] = []
    lleva_columna = "Fecha final" in editado.columns
    for i, fila in editado.iterrows():
        if not bool(fila.get("Incluir")):
            continue
        fecha = fila.get("Fecha")
        if fecha is None or pd.isna(fecha):
            continue
        inicio = pd.Timestamp(fecha).date()

        fin = fila.get("Fecha final")
        fecha_fin = None if fin is None or pd.isna(fin) else pd.Timestamp(fin).date()
        if fecha_fin is None and not lleva_columna:
            previo = (originales[int(i) - 1]
                      if 1 <= int(i) <= len(originales) else None)
            # Sólo si sigue teniendo sentido: si el usuario corrigió la fecha de
            # inicio a mano, el fin de antes puede haber quedado por detrás.
            if previo is not None and previo.fecha_fin and previo.fecha_fin >= inicio:
                fecha_fin = previo.fecha_fin

        salida.append(Evento(
            titulo=str(fila.get("Título") or "").strip() or "Actividad",
            descripcion=str(fila.get("Descripción") or "").strip(),
            fecha_inicio=inicio,
            fecha_fin=fecha_fin,
            hora_inicio=_hora(fila.get("Inicio")),
            hora_fin=_hora(fila.get("Fin")),
            lugar=str(fila.get("Lugar") or "").strip(),
            origen=origen,
            fila=int(i),
        ))
    return salida


CONFIG_COLUMNAS = {
    "Incluir": lambda: st.column_config.CheckboxColumn(width="small", default=True),
    "Título": lambda: st.column_config.TextColumn(width="large", required=True),
    "Fecha": lambda: st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
    "Fecha final": lambda: st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
    "Inicio": lambda: st.column_config.TimeColumn(format="HH:mm", width="small"),
    "Fin": lambda: st.column_config.TimeColumn(format="HH:mm", width="small"),
    "Descripción": lambda: st.column_config.TextColumn(width="large"),
    "Lugar": lambda: st.column_config.TextColumn(width="small"),
    "Revisar": lambda: st.column_config.TextColumn(disabled=True, width="medium"),
}


def editor_de_tabla(tabla: TablaActiva, eventos: list[Evento],
                    ajustes: dict) -> list[Evento]:
    """La tabla editable de los eventos de una tabla activa, ya en su pestaña."""
    if not eventos:
        st.warning(
            "No se encontraron filas con datos. Abrir el desplegable de columnas "
            "de arriba y comprobar que cada una apunte a donde debe."
        )
        return []

    listos = sum(1 for e in eventos if e.valido)
    con_problema = len(eventos) - listos
    # No es lo mismo que `con_problema`: una sesión con fecha pero sin hora es un
    # evento válido y aun así tiene algo que decir («quedará como evento de todo
    # el día»). La columna «Revisar» es el único sitio donde eso se lee, así que
    # aparece en cuanto alguna fila trae texto — y sólo entonces.
    hay_que_revisar = any(ev.problema for ev in eventos)
    st.caption(
        f"{TIPOS[tabla.modo]['etiqueta']} · {len(tabla.df)} filas leídas · "
        f"{listos} eventos listos"
        + (f", {con_problema} por revisar" if con_problema else "")
    )

    if con_problema:
        st.warning(
            f"{con_problema} fila(s) sin una fecha reconocible; quedan desmarcadas "
            "y no se exportan. Al escribir la fecha correcta en la tabla se "
            "incluyen solas."
        )

    # La clave lleva todo lo que cambia el contenido del editor: si no, Streamlit
    # conserva las ediciones de la tabla anterior y las aplica a filas que ya no
    # son las mismas. `hay_que_revisar` entra porque decide si hay columna
    # «Revisar», y una columna de más o de menos es otra tabla.
    columnas = columnas_editor(tabla.modo, hay_que_revisar)
    clave = firma(tabla.clave, tabla.modo, len(eventos), hay_que_revisar,
                  plantilla_de(tabla.modo), ajustes["materia"])
    editado = st.data_editor(
        _a_dataframe(eventos, tabla.modo, hay_que_revisar),
        width="stretch",
        # El índice va visible y numerado 1..N: es lo que dice cuántas
        # actividades hay sin tener que contarlas.
        hide_index=False,
        num_rows="dynamic",
        key=f"editor_{clave}",
        column_config={c: CONFIG_COLUMNAS[c]() for c in columnas},
    )
    return _desde_dataframe(editado, tabla.origen, eventos)


# --------------------------------------------------------------------------- #
# Paso 3 · Exportar
# --------------------------------------------------------------------------- #

def paso_exportar(ajustes: dict, actuales: list[Evento]) -> None:
    """Todo junto: lo que quedó guardado y las tablas abiertas.

    `actuales` ya viene siendo la unión de todas las tablas activas, así que
    aquí no queda ninguna decisión de qué incluir: lo que se ve en el paso 2 se
    exporta.

    Aquí no se repite la lista de eventos: está completa y editable un paso más
    arriba, y volver a enseñarla hacía dudar de si había que revisarla otra vez.
    Basta con el recuento por tabla. La excepción son los de `guardados` —los
    que la sesión traía antes de salir a Google, que `procesar_regreso_oauth`
    devuelve—: no salen en ninguna pestaña abierta y de otro modo quedarían
    invisibles.
    """
    eventos: list[Evento] = st.session_state.guardados + actuales
    dia = sum(1 for e in eventos if e.todo_el_dia)
    hora = len(eventos) - dia
    resumen = " + ".join(
        p for p in (f"{dia} actividades" if dia else "",
                    f"{hora} sesiones" if hora else "") if p
    )
    paso(3, "Exportar al calendario", resumen, activo=bool(eventos))

    if not eventos:
        nota("Al subir un archivo aparecen aquí las opciones para mandarlo al "
             "calendario.")
        return

    por_origen: dict[str, int] = {}
    for ev in eventos:
        por_origen[ev.origen] = por_origen.get(ev.origen, 0) + 1
    detalle = " · ".join(f"{n} de «{origen}»" for origen, n in por_origen.items())

    izq, der = st.columns([3, 2])
    izq.markdown(f"**{len(eventos)} eventos** en total — {detalle}")
    with der:
        if st.button("Quitar todos los eventos", width="stretch"):
            st.session_state.guardados = []
            olvidar_archivo()
            st.rerun()

    guardados = st.session_state.guardados
    if guardados:
        with st.expander(f"Ver los {len(guardados)} eventos ya guardados"):
            st.dataframe(
                pd.DataFrame([{
                    "Título": ev.titulo,
                    "Cuándo": ev.resumen_fecha(),
                    "Tipo": "Todo el día" if ev.todo_el_dia else "Con horario",
                    "Origen": ev.origen,
                } for ev in guardados]),
                width="stretch", hide_index=True,
            )

    directo, ics, enlaces, csv_google = st.tabs([
        "Enviar a Google Calendar", "Descargar archivo .ics",
        "Enlaces (sirve en celular)", "CSV de Google",
    ])

    with directo:
        pestania_envio_directo(eventos, ajustes)

    with ics:
        st.markdown(
            "El `.ics` es la opción más segura: respeta horarios y recordatorios, y "
            "al volver a importarlo **actualiza** los eventos en vez de duplicarlos."
        )
        st.download_button(
            "Descargar .ics",
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
            "**Cómo importarlo:** entrar a [calendar.google.com](https://calendar.google.com) "
            "desde una computadora → **Configuración** → **Importar y exportar** → elegir "
            "el archivo, seleccionar el calendario destino y pulsar **Importar**."
        )

    with enlaces:
        st.markdown(
            "Cada liga abre Google Calendar con el evento **ya llenado**; sólo falta "
            "pulsar *Guardar*. No pide ningún permiso y **es la única opción que "
            "funciona desde el celular** (Google sólo deja importar archivos desde "
            "computadora).\n\n"
            "A cambio, es un evento a la vez: para muchos conviene más el `.ics`."
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
                    "Abrir", display_text="Añadir", width="small"
                ),
            },
        )

    with csv_google:
        st.markdown(
            "Sólo si el `.ics` falla. Google interpreta las fechas del CSV según el "
            "idioma de la cuenta; si los eventos caen en el día equivocado, cambiar "
            "el formato aquí abajo y volver a importar."
        )
        etiqueta = st.selectbox("Formato de fecha", list(exportar.FORMATOS_CSV))
        st.download_button(
            "Descargar CSV",
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
            "El envío directo no está configurado en esta instalación. La pestaña "
            "**Descargar archivo .ics** hace exactamente lo mismo."
        )
        with st.expander("¿Por qué no aparece el botón?"):
            st.markdown(AYUDA_SIN_CONFIGURAR)
        return

    if not st.session_state.credenciales:
        st.warning("Falta conectar con Google desde la barra lateral.")
        return

    try:
        calendarios = gcal.listar_calendarios(st.session_state.credenciales)
    except gcal.SesionCaducada as e:
        st.warning(str(e))
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
    nuevo = "Crear un calendario nuevo para esta materia"
    opciones = [nuevo] + nombres

    izq, der = st.columns([3, 2])
    with izq:
        # Se elige la **posición**, no el nombre: dos calendarios pueden
        # llamarse igual (uno propio y otro compartido, o dos de semestres
        # distintos) y buscar el elegido por su nombre daría siempre con el
        # primero, mandando los eventos al calendario que no era.
        elegido = st.selectbox(
            "Calendario destino", range(len(opciones)),
            format_func=lambda i: opciones[i],
        )
        es_nuevo = elegido == 0
        nombre_nuevo = materia
        if es_nuevo:
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
    if st.button(f"Crear {len(validos)} eventos en Google Calendar",
                 type="primary", width="stretch"):
        with st.status("Conectando con Google…", expanded=True) as estado:
            try:
                if es_nuevo:
                    estado.update(label="Creando el calendario…")
                    calendario_id = gcal.crear_calendario(
                        st.session_state.credenciales,
                        nombre_nuevo or "Actividades SUAyED",
                        ajustes["zona"],
                    )
                else:
                    # La opción 0 es «crear uno nuevo», así que el resto van
                    # corridas una posición respecto de `calendarios`.
                    calendario_id = calendarios[elegido - 1]["id"]

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
            + "."
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
          <h1>Exportar Plan de Trabajo a Google Calendar</h1>
          <p>El plan de trabajo en PDF, Excel o CSV se convierte en eventos de Google
             Calendar: las entregas y las videoconferencias quedan agendadas en unos
             cuantos clics, desde el navegador y sin instalar nada.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    restaurados = st.session_state.pop("aviso_restaurado", 0)
    if restaurados:
        st.success(f"Conexión lista. Los {restaurados} eventos siguen aquí.")

    # «Agregar otro calendario» y «Conectar con Google» van arriba de todo en la
    # barra lateral, pero se dibujan al final: el primero necesita saber si hay
    # archivo abierto (lo carga `paso_archivo`, más abajo) y el segundo, qué
    # eventos preservar durante el viaje a Google. Se reservan los huecos ahora
    # y se rellenan después.
    contenedor_reinicio = st.sidebar.container()
    contenedor_google = st.sidebar.container()
    contenedor_ajustes = st.sidebar.container()

    archivo = paso_archivo()
    activas: list[TablaActiva] = []
    if archivo is not None:
        activas = paso_lectura(*archivo)

    # La barra lateral va después del paso 1 porque necesita saber si alguna de
    # las tablas abiertas trae horario; y antes del paso 2, que usa su `dayfirst`
    # y las plantillas del título que se ajustan ahí.
    with contenedor_ajustes:
        ajustes = barra_lateral(hay_sesiones_con_horario(activas), dibujar_google=False)

    actuales: list[Evento] = []
    if activas:
        actuales = paso_revisar(activas, ajustes)
    else:
        paso(2, "Revisar y ajustar", activo=False)

    paso_exportar(ajustes, actuales)

    with contenedor_reinicio:
        boton_agregar_calendario()
    with contenedor_google:
        panel_google(actuales)
        st.divider()
    with st.sidebar:
        pie_lateral()
        # Lo último de la barra lateral, debajo del crédito: sólo lo busca quien
        # sabe que está ahí, y sin contraseña configurada no se dibuja nada.
        panel_admin()

    with st.expander("Preguntas frecuentes"):
        st.markdown(
            """
**¿Hay que confirmar algo para que se creen los eventos?**
No. Todo lo que aparece en el paso 2 ya cuenta; en el paso 3 sólo se elige cómo
mandarlo al calendario.

**Las actividades y las videoconferencias están en tablas separadas.**
Si las dos vienen dentro del mismo PDF, se marcan juntas en el paso 1 y se
exportan de una vez. Si están en archivos distintos, se exporta el primero y
después, con **«Agregar otro calendario»**, se sube el segundo.

**Empezar de cero.**
En el paso 3, **«Quitar todos los eventos»**; en la barra lateral,
**«Agregar otro calendario»** borra además el nombre de la materia.

**¿Se puede subir el plan de trabajo en PDF, sin tocarlo?**
Sí, es lo más rápido. La app busca dentro sus tablas y las muestra con una
casilla cada una. También acepta la tabla ya pasada a CSV o Excel.

**Aparecen varias tablas de videoconferencias.**
El plan trae un grupo por asesor, así que no viene marcada ninguna: van juntas
bajo **«Elegir el grupo que corresponda»** y hay que marcar la del asesor
propio, que aparece con su nombre al lado del número de grupo. Marcar sólo las
actividades y ninguna de ellas también es una respuesta válida.

**Una tabla quedó del tipo equivocado.**
En un CSV o un Excel, el tipo se cambia en el paso 1, con el selector que sale al
leer el archivo; la pestaña del paso 2 se acomoda sola. En un PDF lo pone la app
al reconocer cada tabla y lo dice el nombre de su casilla: si una no es lo que
dice ser, lo que corresponde es desmarcarla.

**El PDF se subió y no se encontraron las tablas.**
Puede que el plan traiga un formato que la app todavía no reconoce, o que el PDF
sea una imagen escaneada (una foto de la hoja, sin texto que se pueda copiar).
Copiar la tabla, pegarla en Excel o Google Sheets y subir ese archivo: de ahí en
adelante todo funciona igual.

**El Excel no se lee bien.**
En el paso 2, abrir el desplegable de columnas: ahí se corrige en qué fila están
los títulos y qué es cada columna. Si el archivo es `.xls` viejo, conviene
abrirlo en Excel y guardarlo como `.xlsx`.

**Las fechas salieron en el día equivocado.**
En la barra lateral, dentro de «Ajustes avanzados», se elige si `03/04/2026` se
lee como día/mes o mes/día. Cualquier fecha se puede corregir a mano en la tabla
del paso 2.

**El plan trae las fechas sin año** («21 de agosto»).
Poner el año correcto en «Año para fechas escritas sin año».

**No aparece el botón de enviar a Google.**
Esa parte la configura quien publica la app (ver `docs/DESPLIEGUE.md`).
Entretanto, el `.ics` da un resultado idéntico.

**Ya se importó una vez y hay que repetirlo.**
Volver a importar el mismo `.ics`: Google reconoce los eventos y los actualiza en
lugar de duplicarlos. Con el envío directo, dejar marcada la casilla «No duplicar
eventos que ya existan».

**¿Cómo se cambia el título de los eventos?**
En la barra lateral, «Ajustes avanzados»: hay una plantilla por tipo de evento,
con los campos `{materia}`, `{unidad}` y `{titulo}`.

**¿La app usa inteligencia artificial?**
Sólo para leer el PDF, y sólo si quien publica la app configuró una clave de
OpenAI: un modelo GPT encuentra las tablas —venga el plan en el formato que
venga— y **resume la descripción de cada actividad** en un par de frases. Sin
clave, o apagándola en «Ajustes avanzados», trabaja el lector clásico, que no
envía nada a ningún servicio.

**¿Se guarda la información?**
No. El archivo se procesa en memoria mientras la página está abierta y no se
almacena. El permiso de Google sólo se usa para crear los eventos exportados. Si
esta instalación tiene la lectura con IA activada, el texto del PDF se envía a la
API de OpenAI para extraer las tablas; la API no lo usa para entrenar modelos y
la app no lo guarda.
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
