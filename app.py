"""Exportar Plan de Trabajo a Google Calendar — aplicación Streamlit.

Sube el plan de trabajo (CSV o Excel), revisa lo que se detectó y manda las
actividades y las videoconferencias a tu Google Calendar de un botón.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time
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


# --------------------------------------------------------------------------- #
# Estado
# --------------------------------------------------------------------------- #

def arrancar_estado() -> None:
    st.session_state.setdefault("eventos", [])
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
    modo = st.segmented_control(
        "¿Qué vas a pasar al calendario?",
        options=list(TIPOS),
        format_func=lambda m: TIPOS[m]["etiqueta"],
        default=MODO_DIA,
        key="modo",
    ) or MODO_DIA
    st.caption(TIPOS[modo]["descripcion"])
    return modo


# --------------------------------------------------------------------------- #
# Barra lateral
# --------------------------------------------------------------------------- #

def barra_lateral(modo: str) -> dict:
    with st.sidebar:
        mascota = RAIZ / "assets" / "gato.jpeg"
        if mascota.exists():
            st.image(str(mascota), width="stretch")

        st.markdown("### ⚙️ Ajustes")
        materia = st.text_input(
            "Nombre de la materia",
            placeholder="Ej. Matemáticas Financieras",
            help="Se antepone al título de cada evento para distinguirlos en el calendario.",
            key="materia",
        )
        zona = st.selectbox("Zona horaria", ZONAS, index=0)
        etiqueta_rec = st.selectbox("Recordatorio", list(RECORDATORIOS), index=3)

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

        st.divider()
        panel_google()

        st.markdown(
            '<div class="marca">Hecho para SUAyED · '
            '<a href="https://github.com/AmiyaMihari" target="_blank">@AmiyaMihari</a></div>',
            unsafe_allow_html=True,
        )

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


def panel_google() -> None:
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

    procesar_regreso_oauth(cfg)

    if st.session_state.credenciales:
        correo = st.session_state.get("correo_google", "")
        st.success(f"Conectado{f' como {correo}' if correo else ''}", icon="✅")
        if st.button("Desconectar", width="stretch"):
            for clave in ("credenciales", "correo_google"):
                st.session_state.pop(clave, None)
            st.rerun()
    else:
        try:
            url = gcal.url_autorizacion(cfg)
        except gcal.ErrorGoogle as e:
            st.error(str(e))
            return
        st.link_button("Conectar con Google", url, width="stretch", type="primary")
        st.caption("Sólo se usa para crear los eventos que tú confirmes.")


def procesar_regreso_oauth(cfg: dict) -> None:
    """Google devuelve al usuario con ?code=...&state=... en la URL."""
    if st.session_state.credenciales:
        return
    codigo = st.query_params.get("code")
    if not codigo:
        return

    estado = st.query_params.get("state")
    try:
        credenciales = gcal.credenciales_desde_codigo(cfg, codigo, estado)
    except gcal.ErrorGoogle as e:
        st.query_params.clear()
        st.error(str(e))
        return

    st.session_state.credenciales = credenciales
    st.session_state.correo_google = gcal.correo_usuario(credenciales)
    st.query_params.clear()
    st.rerun()


# --------------------------------------------------------------------------- #
# Paso 1 · Archivo
# --------------------------------------------------------------------------- #

def paso_archivo(modo: str) -> tuple[bytes, str] | None:
    paso(1, "Sube tu archivo", TIPOS[modo]["ayuda_archivo"])

    ejemplo = TIPOS[modo]["ejemplo"]
    ruta_ejemplo = RAIZ / "ejemplos" / ejemplo if ejemplo else None
    hay_ejemplo = bool(ruta_ejemplo and ruta_ejemplo.exists())

    izq, der = st.columns([3, 2])
    with izq:
        subido = st.file_uploader(
            "Arrastra aquí el CSV o el Excel",
            type=["csv", "xlsx", "xlsm", "xls", "ods", "tsv", "txt"],
            label_visibility="collapsed",
        )
    with der:
        if hay_ejemplo:
            if st.button("📄 Probar con un archivo de ejemplo", width="stretch"):
                st.session_state["usar_ejemplo"] = True
            if st.session_state.get("usar_ejemplo") and st.button(
                "Quitar el ejemplo", width="stretch"
            ):
                st.session_state["usar_ejemplo"] = False

    if subido is not None:
        st.session_state["usar_ejemplo"] = False
        return subido.getvalue(), subido.name
    if hay_ejemplo and st.session_state.get("usar_ejemplo"):
        return ruta_ejemplo.read_bytes(), ruta_ejemplo.name

    nota(
        "¿No tienes el plan en tabla? Copia la tabla del PDF y pégala en Excel o en "
        "Google Sheets, guárdala y súbela aquí. No importa si arriba hay filas de "
        "título: la app detecta sola dónde empieza la tabla."
    )
    return None


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

    for aviso in lectura.avisos:
        st.info(aviso, icon="🔎")

    with st.expander("Ajustes de lectura · sólo si la tabla se ve mal"):
        actual = lectura.fila_encabezado + 1
        nueva = st.number_input(
            "Fila donde están los títulos de las columnas",
            min_value=1, max_value=30, value=actual, step=1,
            help="Cámbiala si la vista previa muestra encabezados equivocados.",
        )
        if nueva - 1 != lectura.fila_encabezado:
            st.session_state.fila_encabezado = int(nueva) - 1
            st.rerun()
        st.dataframe(lectura.df.head(8), width="stretch", hide_index=True)

    st.success(
        f"Tabla leída: **{len(lectura.df)} filas** y **{len(lectura.df.columns)} columnas**"
        + (f" de la hoja «{lectura.hoja}»" if lectura.hoja else ""),
        icon="✅",
    )
    return lectura


# --------------------------------------------------------------------------- #
# Paso 2 · Mapeo (sólo los campos del tipo elegido)
# --------------------------------------------------------------------------- #

def paso_mapeo(df: pd.DataFrame, modo: str, dayfirst: bool) -> dict:
    principales, opcionales = deteccion.campos_de(modo)
    paso(2, "Revisa qué es cada columna", "ya está detectado; corrige sólo si hace falta")

    clave = firma(st.session_state.firma_archivo, st.session_state.hoja, modo, len(df.columns))
    if f"auto_{clave}" not in st.session_state:
        st.session_state[f"auto_{clave}"] = deteccion.detectar_columnas(df, dayfirst, modo)
    automatico = st.session_state[f"auto_{clave}"]

    opciones = ["— ninguna —"] + list(df.columns)

    def selector(campo: str, contenedor):
        sugerida = automatico.get(campo)
        indice = opciones.index(sugerida) if sugerida in opciones else 0
        elegida = contenedor.selectbox(
            deteccion.etiqueta(campo, modo), opciones, index=indice,
            key=f"map_{campo}_{clave}",
        )
        return None if elegida == "— ninguna —" else elegida

    mapeo: dict[str, str | None] = {c: None for c in deteccion.CAMPOS}

    for campo, col in zip(principales, st.columns(len(principales))):
        mapeo[campo] = selector(campo, col)

    with st.expander("Columnas opcionales"):
        for campo, col in zip(opcionales, st.columns(len(opcionales))):
            mapeo[campo] = selector(campo, col)

    total = len(principales) + len(opcionales)
    detectados = sum(1 for c in principales + opcionales if automatico.get(c))
    st.caption(f"🪄 Detecté automáticamente {detectados} de {total} columnas.")

    if not mapeo["fecha"]:
        st.warning(
            "No encontré la columna de fechas. Selecciónala arriba: sin fecha no se "
            "pueden crear eventos.",
            icon="⚠️",
        )
    elif modo == MODO_HORA and not mapeo["hora"]:
        st.warning(
            "No encontré la columna de horarios. Si esta tabla no trae hora, arriba "
            "cambia a «Actividades y entregas».",
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


def paso_revision(df: pd.DataFrame, mapeo: dict, modo: str, ajustes: dict, origen: str) -> None:
    paso(3, "Revisa y corrige", "puedes editar cualquier celda")

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

    if not eventos:
        st.warning("No encontré filas con datos. Revisa el mapeo del paso 2.", icon="⚠️")
        return

    listos = sum(1 for e in eventos if e.valido)
    con_problema = len(eventos) - listos
    m1, m2, m3 = st.columns(3)
    m1.metric("Filas leídas", len(eventos))
    m2.metric("Eventos listos", listos)
    m3.metric("Necesitan revisión", con_problema)

    if con_problema:
        with st.expander(f"⚠️ {con_problema} fila(s) sin fecha válida"):
            for ev in eventos:
                if not ev.valido:
                    st.write(f"**Fila {ev.fila}** — {ev.titulo or '(sin título)'}: {ev.problema}")
            st.caption("Escribe la fecha correcta en la tabla de abajo y quedarán incluidas.")

    editado = st.data_editor(
        _a_dataframe(eventos, modo),
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        key=f"editor_{firma(origen, modo, len(eventos), ajustes['plantilla'], ajustes['materia'])}",
        column_config={c: CONFIG_COLUMNAS[c]() for c in columnas_editor(modo)},
    )

    izq, der = st.columns([3, 2])
    with izq:
        if st.button("➕ Añadir a mi lista", type="primary", width="stretch"):
            nuevos = _desde_dataframe(editado, origen)
            if not nuevos:
                st.warning("No hay filas marcadas con fecha válida.")
            else:
                st.session_state.eventos.extend(nuevos)
                st.toast(f"Añadí {len(nuevos)} eventos a tu lista", icon="✅")
                st.rerun()
    with der:
        otro = MODO_HORA if modo == MODO_DIA else MODO_DIA
        st.caption(
            f"¿También tienes {TIPOS[otro]['corta'].lower()}? Añade éstas, cambia el "
            "tipo allá arriba y sube la otra tabla: se acumulan en la misma lista."
        )


# --------------------------------------------------------------------------- #
# Paso 4 · Exportar
# --------------------------------------------------------------------------- #

def paso_exportar(ajustes: dict) -> None:
    eventos: list[Evento] = st.session_state.eventos
    dia = sum(1 for e in eventos if e.todo_el_dia)
    hora = len(eventos) - dia
    resumen = " + ".join(
        p for p in (f"{dia} actividades" if dia else "",
                    f"{hora} sesiones" if hora else "") if p
    )
    paso(4, "Manda todo a tu calendario", resumen, activo=bool(eventos))

    if not eventos:
        nota("Aún no has añadido eventos. Completa los pasos anteriores y pulsa "
             "«Añadir a mi lista».")
        return

    with st.expander(f"📋 Ver mi lista ({len(eventos)} eventos)"):
        st.dataframe(
            pd.DataFrame([{
                "Título": ev.titulo,
                "Cuándo": ev.resumen_fecha(),
                "Tipo": "Todo el día" if ev.todo_el_dia else "Con horario",
                "Origen": ev.origen,
            } for ev in eventos]),
            width="stretch", hide_index=True,
        )
        if st.button("🗑️ Vaciar la lista"):
            st.session_state.eventos = []
            st.rerun()

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
    except gcal.ErrorGoogle as e:
        st.error(str(e))
        return

    nombres = [c["nombre"] + (" (principal)" if c["principal"] else "") for c in calendarios]
    nuevo = "➕ Crear un calendario nuevo para esta materia"

    izq, der = st.columns([3, 2])
    with izq:
        elegido = st.selectbox("¿A qué calendario?", nombres + [nuevo])
        nombre_nuevo = ""
        if elegido == nuevo:
            nombre_nuevo = st.text_input(
                "Nombre del calendario",
                value=ajustes["materia"] or "Actividades SUAyED",
                help="Tener la materia en su propio calendario te deja ocultarlo o "
                     "borrarlo completo al terminar el semestre.",
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

    modo = selector_de_tipo()
    ajustes = barra_lateral(modo)

    archivo = paso_archivo(modo)
    if archivo is not None:
        datos, nombre = archivo
        lectura = paso_lectura(datos, nombre)
        if lectura is not None:
            mapeo = paso_mapeo(lectura.df, modo, ajustes["dayfirst"])
            origen = nombre + (f" · {lectura.hoja}" if lectura.hoja else "")
            paso_revision(lectura.df, mapeo, modo, ajustes, origen)
    else:
        paso(2, "Revisa qué es cada columna", activo=False)
        paso(3, "Revisa y corrige", activo=False)

    paso_exportar(ajustes)

    with st.expander("❓ Preguntas frecuentes"):
        st.markdown(
            """
**Tengo actividades y videoconferencias. ¿Hago dos veces el proceso?**
Sí, y está pensado así: deja arriba **Actividades**, sube esa tabla y pulsa
*Añadir a mi lista*; luego cambia a **Videoconferencias**, sube la otra y añádela
también. Los eventos se acumulan y se exportan juntos al final.

**No me lee bien el Excel.**
Abre «Ajustes de lectura» y corrige la fila donde están los títulos de las
columnas. Si tu archivo es `.xls` viejo, ábrelo en Excel y guárdalo como `.xlsx`.

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
