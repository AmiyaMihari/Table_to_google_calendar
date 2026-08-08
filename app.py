"""Exportar Plan de Trabajo a Google Calendar — aplicación Streamlit.

Sube el plan de trabajo (CSV o Excel), revisa lo que se detectó y manda las
actividades y las videoconferencias a tu Google Calendar de un botón.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time
from html import escape
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
import streamlit as st

from tabla_calendar import deteccion, exportar, tablas
from tabla_calendar import google_calendar as gcal
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
        "etiqueta": "📝  Actividades y entregas",
        "corta": "Actividades",
        "descripcion": "Tareas con fecha límite. Se crean como eventos de **todo el día**.",
        "ayuda_archivo": "la tabla de actividades con su fecha de entrega",
        "ejemplo": "razonamiento_logico.csv",
    },
    MODO_HORA: {
        "etiqueta": "🎥  Videoconferencias y asesorías",
        "corta": "Videoconferencias",
        "descripcion": "Sesiones con horario. Se crean como eventos **con hora de inicio y fin**.",
        "ayuda_archivo": "la tabla de sesiones con su fecha y su horario",
        "ejemplo": "videoconferencias_ejemplo.csv",
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
          /* st.link_button siempre abre pestaña nueva y no se puede cambiar; con
             OAuth eso deja al usuario con dos pestañas y la original a medias.
             Este enlace navega en la misma. */
          a.boton-google {
            display: block; width: 100%; box-sizing: border-box;
            background: #4F46E5; color: #fff !important; text-decoration: none !important;
            border-radius: 8px; padding: 11px 16px; text-align: center;
            font-weight: 600; font-size: .95rem; border: 1px solid #4F46E5;
          }
          a.boton-google:hover { background: #4338CA; border-color: #4338CA; }
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
          /* El selector de tipo manda sobre todo lo demás: que se vea así. */
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


def firma(*partes) -> str:
    return hashlib.md5("|".join(str(p) for p in partes).encode()).hexdigest()[:12]


def url_base() -> str:
    """URL pública de la app, sin parámetros: sirve como redirect_uri de OAuth."""
    try:
        partes = urlsplit(st.context.url)
        return urlunsplit((partes.scheme, partes.netloc, partes.path, "", ""))
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
# Selector de tipo — la decisión que gobierna todo lo demás
# --------------------------------------------------------------------------- #

def selector_de_tipo() -> str:
    # Un cambio de tipo pedido desde otro punto de la página (el botón «Incluir
    # también…») se aplica aquí: Streamlit prohíbe tocar la clave de un widget
    # una vez creado, así que se deja pendiente y se resuelve al inicio del
    # siguiente ciclo, justo antes de instanciarlo.
    pendiente = st.session_state.pop("modo_pendiente", None)
    if pendiente:
        st.session_state.modo = pendiente

    # `default` sólo la primera vez: si el valor ya viene en la sesión (por
    # ejemplo restaurado al volver de Google), pasar ambos hace que Streamlit
    # avise por consola de que se está fijando el valor por dos vías.
    inicial = {} if "modo" in st.session_state else {"default": MODO_DIA}
    modo = st.segmented_control(
        "¿Qué vas a pasar al calendario?",
        options=list(TIPOS),
        format_func=lambda m: TIPOS[m]["etiqueta"],
        key="modo",
        **inicial,
    ) or MODO_DIA
    st.caption(TIPOS[modo]["descripcion"])
    return modo


# --------------------------------------------------------------------------- #
# Barra lateral
# --------------------------------------------------------------------------- #

def barra_lateral(modo: str, dibujar_google: bool = True) -> dict:
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
            plantilla = st.text_input(
                "Plantilla del título",
                value=PLANTILLAS[modo],
                help="Campos disponibles: {materia}, {unidad}, {titulo}. "
                     "Los campos vacíos se omiten junto con su separador.",
                key=f"plantilla_{modo}",
            )
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
                disabled=modo == MODO_DIA,
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
        "plantilla": plantilla,
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
    else:
        try:
            # Al ir a Google el navegador recarga la página y Streamlit pierde la
            # sesión, así que el trabajo del usuario viaja guardado junto al
            # `state` de OAuth y se restaura al volver.
            url = gcal.url_autorizacion(cfg, datos_sesion={
                "guardados": st.session_state.guardados + list(actuales or []),
                "materia": st.session_state.get("materia", ""),
                "modo": st.session_state.get("modo"),
            })
        except gcal.ErrorGoogle as e:
            st.error(str(e))
            return
        # `st.html` y no `st.markdown`: éste último procesa markdown, y el
        # `state` de OAuth lleva guiones bajos que se pueden interpretar como
        # cursiva y romper el enlace. Los `&` se escapan como manda HTML.
        #
        # target="_top" y no "_self": Google rechaza sus pantallas de inicio de
        # sesión dentro de un iframe (responde 403), y Streamlit Cloud sirve la
        # app enmarcada en algunos casos. "_top" navega la ventana completa, y
        # cuando no hay iframe se comporta igual que "_self".
        st.html(
            f'<a class="boton-google" href="{escape(url, quote=True)}" '
            'target="_top" rel="noopener">Conectar con Google</a>'
        )
        # Google enseña una pantalla de advertencia porque la app no está
        # verificada (el trámite exige dominio propio). Sin explicar esto y
        # cómo seguir, la mayoría se echa para atrás justo aquí.
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

    # Devolverle al usuario lo que tenía antes de salir a Google.
    if datos:
        st.session_state.guardados = datos.get("guardados") or []
        for clave in ("materia", "modo"):
            if datos.get(clave) is not None and clave not in st.session_state:
                st.session_state[clave] = datos[clave]
        if st.session_state.guardados:
            st.session_state.aviso_restaurado = len(st.session_state.guardados)

    st.query_params.clear()
    st.rerun()


# --------------------------------------------------------------------------- #
# Paso 1 · Archivo
# --------------------------------------------------------------------------- #

def olvidar_archivo() -> None:
    """Vacía el archivo actual y el widget que lo sostiene."""
    st.session_state.archivo = None
    st.session_state.firma_archivo = ""
    st.session_state.ronda_subida += 1


def paso_archivo(modo: str) -> tuple[bytes, str] | None:
    paso(1, "Sube tu archivo", TIPOS[modo]["ayuda_archivo"])

    guardados = st.session_state.pop("aviso_guardado", 0)
    if guardados:
        st.success(
            f"Guardé {guardados} eventos. Ahora sube **{TIPOS[modo]['ayuda_archivo']}**; "
            "al final se exportan todos juntos.",
            icon="✅",
        )

    subido = st.file_uploader(
        "Arrastra aquí el CSV o el Excel",
        type=["csv", "xlsx", "xlsm", "xls", "ods", "tsv", "txt"],
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
            "¿No tienes el plan en tabla? Copia la tabla del PDF y pégala en Excel o en "
            "Google Sheets, guárdala y súbela aquí. No importa si arriba hay filas de "
            "título ni si las celdas de «Unidad» están combinadas: la app lo resuelve."
        )
        return None

    if subido is None:
        izq, der = st.columns([3, 2])
        izq.caption(f"📄 Trabajando con **{archivo[1]}**")
        if der.button("Quitar archivo", width="stretch"):
            olvidar_archivo()
            st.rerun()
    return archivo


def paso_lectura(datos: bytes, nombre: str) -> tablas.Lectura | None:
    nueva_firma = firma(nombre, len(datos))
    if nueva_firma != st.session_state.firma_archivo:
        st.session_state.firma_archivo = nueva_firma
        st.session_state.hoja = None
        st.session_state.fila_encabezado = None

    hojas: list[str] = []
    if tablas.es_excel(nombre):
        try:
            hojas = tablas.listar_hojas(datos, nombre)
        except tablas.ErrorDeLectura as e:
            st.error(str(e))
            return None

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
        return None

    st.success(
        f"Tabla leída: **{len(lectura.df)} filas** y **{len(lectura.df.columns)} columnas**"
        + (f" de la hoja «{lectura.hoja}»" if lectura.hoja else ""),
        icon="✅",
    )
    return lectura


# --------------------------------------------------------------------------- #
# Paso 2 · Mapeo (sólo los campos del tipo elegido)
# --------------------------------------------------------------------------- #

def paso_mapeo(lectura: tablas.Lectura, modo: str, dayfirst: bool) -> dict:
    df = lectura.df
    principales, opcionales = deteccion.campos_de(modo)
    paso(2, "Configuración manual", "opcional — sólo si algo salió mal")

    clave = firma(st.session_state.firma_archivo, st.session_state.hoja, modo, len(df.columns))
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
        st.caption(
            "Si los nombres de las columnas de arriba se ven raros, la tabla no "
            "empieza donde creí. Corrige aquí en qué fila están los títulos:"
        )
        izq, der = st.columns([1, 3])
        nueva = izq.number_input(
            "Fila de los títulos",
            min_value=1, max_value=30, value=lectura.fila_encabezado + 1, step=1,
        )
        der.dataframe(df.head(4), width="stretch", hide_index=True)
        if nueva - 1 != lectura.fila_encabezado:
            st.session_state.fila_encabezado = int(nueva) - 1
            st.rerun()

    if modo == MODO_HORA and not mapeo["hora"]:
        st.warning(
            "Esta tabla no parece traer horarios. Si son entregas, cambia el tipo "
            "allá arriba a «Actividades y entregas».",
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


def paso_revision(df: pd.DataFrame, mapeo: dict, modo: str, ajustes: dict,
                  origen: str) -> list[Evento]:
    """Muestra los eventos de la tabla abierta y devuelve los que quedaron."""
    eventos = construir_eventos(
        df, mapeo,
        materia=ajustes["materia"],
        plantilla=ajustes["plantilla"],
        dayfirst=ajustes["dayfirst"],
        anio_defecto=ajustes["anio_defecto"],
        modo=modo,
        duracion_horas=ajustes["duracion"],
        rellenar_unidad=ajustes["rellenar"],
        origen=origen,
    )

    listos = sum(1 for e in eventos if e.valido)
    con_problema = len(eventos) - listos
    paso(3, "Revisa los eventos",
         f"opcional — {listos} listos" + (f", {con_problema} por revisar" if con_problema else ""))

    if not eventos:
        st.warning(
            "No encontré filas con datos. Abre «Configuración manual» arriba y revisa "
            "que las columnas apunten a donde deben.",
            icon="⚠️",
        )
        return []

    if con_problema:
        st.warning(
            f"{con_problema} fila(s) sin fecha que yo entienda; están desmarcadas y no "
            "se exportarán. Escribe la fecha correcta en la tabla y se incluyen solas.",
            icon="⚠️",
        )

    editado = st.data_editor(
        _a_dataframe(eventos, modo),
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        key=f"editor_{firma(origen, modo, len(eventos), ajustes['plantilla'], ajustes['materia'])}",
        column_config={c: CONFIG_COLUMNAS[c]() for c in columnas_editor(modo)},
    )
    return _desde_dataframe(editado, origen)


# --------------------------------------------------------------------------- #
# Paso 4 · Exportar
# --------------------------------------------------------------------------- #

def paso_exportar(ajustes: dict, actuales: list[Evento], modo: str) -> None:
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

    otro = MODO_HORA if modo == MODO_DIA else MODO_DIA
    izq, der = st.columns([3, 2])
    with izq:
        if actuales and st.button(
            f"➕ Incluir también {TIPOS[otro]['corta'].lower()}",
            width="stretch",
            help="Si tu plan trae esa información en otra tabla. Guarda lo de "
                 "ahora y te deja listo para subirla.",
        ):
            # Se conserva lo hecho, se cambia solo el tipo y se vacía el widget:
            # si no se vacía, vuelve a cargar el mismo archivo y los eventos se
            # duplican en cada pulsación.
            st.session_state.guardados = st.session_state.guardados + actuales
            st.session_state.aviso_guardado = len(actuales)
            st.session_state.modo_pendiente = otro
            olvidar_archivo()
            st.rerun()
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

    # Si el usuario viene de autorizar en Google, se procesa antes de dibujar
    # nada: así lo que traía recuperado ya está disponible para toda la página.
    cfg_google = config_google()
    if cfg_google:
        procesar_regreso_oauth(cfg_google)

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

    modo = selector_de_tipo()

    # Conectar con Google va arriba de todo en la barra lateral, pero se dibuja
    # al final: necesita saber qué eventos hay que preservar durante el viaje a
    # Google. Se reservan los huecos ahora y se rellenan después.
    contenedor_google = st.sidebar.container()
    contenedor_ajustes = st.sidebar.container()

    actuales: list[Evento] = []
    archivo = paso_archivo(modo)
    if archivo is not None:
        datos, nombre = archivo
        lectura = paso_lectura(datos, nombre)
        if lectura is not None:
            with contenedor_ajustes:
                ajustes = barra_lateral(modo, dibujar_google=False)
            mapeo = paso_mapeo(lectura, modo, ajustes["dayfirst"])
            origen = nombre + (f" · {lectura.hoja}" if lectura.hoja else "")
            actuales = paso_revision(lectura.df, mapeo, modo, ajustes, origen)
        else:
            with contenedor_ajustes:
                ajustes = barra_lateral(modo, dibujar_google=False)
    else:
        with contenedor_ajustes:
            ajustes = barra_lateral(modo, dibujar_google=False)
        paso(2, "Configuración manual", "opcional", activo=False)
        paso(3, "Revisa los eventos", "opcional", activo=False)

    paso_exportar(ajustes, actuales, modo)

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
Sube la primera y, en el paso 4, pulsa **«Incluir también videoconferencias»**
(o *actividades*, según lo que falte). Se guarda lo que llevas, se cambia solo
el tipo, y ya sólo tienes que subir la otra tabla. Al final se exportan juntas.

**Me equivoqué y quiero empezar de cero.**
En el paso 4, **«Quitar todos los eventos»**. Para cambiar sólo el archivo sin
perder lo anterior, usa *Quitar archivo* en el paso 1.

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


if __name__ == "__main__":
    main()
