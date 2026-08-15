"""Lectura del plan de trabajo con un modelo de OpenAI.

`pdf.py` reconstruye las tablas midiendo la rejilla que devuelve `pdfplumber`,
y lo hace bien con las **dos familias de plan que conocemos**. El problema es
justo ése: cada facultad maqueta su plan a su manera, y un formato nuevo —una
columna de más, un encabezado partido de otro modo, una tabla sin bordes— cae
fuera de lo que esa geometría sabe reconocer. Aquí se lee el PDF como lo leería
una persona: el texto plano, y un modelo que dice qué filas son actividades y
cuáles videoconferencias.

De paso resuelve algo que la geometría no puede: la columna de descripción de
estos planes son párrafos enteros con los ejercicios uno por uno, y en el
calendario eso no cabe. El modelo devuelve un resumen de dos o tres frases.

Hay planes que no listan las asesorías una por una, sino que dan el **horario
semanal de dudas del asesor** («Días: martes y jueves · Hora: 14:00 a 16:00»).
Eso **no es una tabla de videoconferencias** y el prompt se lo dice al modelo
para que lo ignore, en la misma lista que los videos grabados y los exámenes.
Llegó a desplegarse en sesiones fechadas, y se revirtió: son las horas en que el
asesor atiende dudas, no clases a las que haya que ir.

Su salida son las mismas `pdf.Candidata` que el lector clásico, con los mismos
nombres de columna, así que `deteccion`, `modelo` y `exportar` no se enteran de
quién leyó el PDF. Quien llame decide: si la IA no encuentra nada aprovechable
devuelve una lista vacía —sin excepción— y se puede caer al lector de siempre.

Este módulo **no importa Streamlit**: se puede ejercitar desde `python` a secas,
igual que el resto del paquete.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from . import fechas, pdf

try:
    import openai
    DISPONIBLE = True
except ImportError:  # pragma: no cover - depende del entorno
    openai = None
    DISPONIBLE = False


MODELO_POR_DEFECTO = "gpt-5-mini"

# USD por millón de tokens: (entrada, caché, salida). En OpenAI los tokens
# cacheados son un subconjunto de los de entrada y sólo cambian de precio:
# escribir en la caché no cuesta nada aparte.
PRECIOS: dict[str, tuple[float, float, float]] = {
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
}

# Un plan largo ronda los 50.000 caracteres de texto; su JSON cabe de sobra.
_MAX_TOKENS = 16000

# El PDF entero viaja en el mensaje, así que la llamada tarda. Un minuto no
# alcanza para los planes grandes con el modelo pensando.
_ESPERA_SEGUNDOS = 120.0

# Lo que puede durar el período de un plan de trabajo. Un semestre de la UNAM va
# de agosto a diciembre o de febrero a junio: cinco meses largos. Si las fechas
# de un mismo plan abarcan más que esto, no es que el curso dure año y medio, es
# que alguna tabla quedó con el año equivocado (ver `_aviso_de_anios`).
_MAX_DIAS_PERIODO = 200


class ErrorDeIA(Exception):
    """Fallo al leer con IA, con mensaje entendible para el usuario."""


# --------------------------------------------------------------------------- #
# Uso y costo
# --------------------------------------------------------------------------- #

@dataclass
class Uso:
    """Lo que consumió una lectura, para poder enseñárselo al usuario."""

    modelo: str
    entrada: int
    salida: int
    # Subconjunto de `entrada` que venía cacheado, no una cifra aparte.
    cache_lectura: int

    @property
    def costo_usd(self) -> float | None:
        """Cuánto costó la llamada. None si no sabemos el precio del modelo."""
        precio = PRECIOS.get(self.modelo)
        if precio is None:
            return None
        pe, pc, ps = precio
        return (
            (self.entrada - self.cache_lectura) * pe
            + self.cache_lectura * pc
            + self.salida * ps
        ) / 1e6

    def resumen(self) -> str:
        """Una línea para la interfaz: cuántos tokens y cuánto costó."""
        # `entrada` ya trae dentro los tokens cacheados, así que aquí no se suma
        # nada: lo único que cambia por el caché es el precio, no la cuenta.
        texto = f"{self.entrada:,} tokens de entrada + {self.salida:,} de salida"
        costo = self.costo_usd
        if costo is None:
            return texto
        return f"{texto} ≈ ${costo:.4f} USD"


@dataclass
class ResultadoIA:
    """Lo que devuelve una lectura: las tablas y lo que costó sacarlas."""

    candidatas: list
    uso: Uso


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #

def leer_config(secretos) -> dict | None:
    """Extrae api_key / model de la sección «openai» de st.secrets.

    Mismo trato que `google_calendar.leer_config`: `st.secrets` truena si no hay
    `secrets.toml`, así que el acceso va dentro de un `try`.
    """
    try:
        cfg = secretos.get("openai")
    except Exception:
        return None
    if not cfg:
        return None

    clave = str(cfg.get("api_key", "")).strip()
    if not clave:
        return None
    modelo = str(cfg.get("model", "")).strip() or MODELO_POR_DEFECTO
    return {"api_key": clave, "model": modelo}


def buscar_clave_local(base) -> dict | None:
    """La clave para desarrollo local: variable de entorno o JSON en `env/`.

    La variable manda, porque es lo que ya usa el SDK de OpenAI y lo que
    tiene puesto quien trabaja con la API desde la terminal. `env/` está en
    .gitignore, igual que las credenciales de Google.
    """
    clave = os.environ.get("OPENAI_API_KEY", "").strip()
    if clave:
        modelo = os.environ.get("OPENAI_MODEL", "").strip() or MODELO_POR_DEFECTO
        return {"api_key": clave, "model": modelo}

    try:
        datos = json.loads(Path(base).joinpath("env", "openai_secret.json")
                           .read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(datos, dict):
        return None

    # Dos formas para el mismo archivo: la del proyecto (`api_key`) y la que
    # deja quien copia el nombre de la variable de entorno (`OPENAI_API_KEY`).
    clave = (str(datos.get("api_key", "")).strip()
             or str(datos.get("OPENAI_API_KEY", "")).strip())
    if not clave:
        return None
    modelo = str(datos.get("model", "")).strip() or MODELO_POR_DEFECTO
    return {"api_key": clave, "model": modelo}


def buscar_clave_admin(base) -> str | None:
    """La contraseña del panel de administración, para la instalación local.

    Vive en `env/admin_secret.json` (`{"clave": "..."}`), junto a los demás
    secretos y dentro de la misma carpeta que ignora git. En la nube el sitio es
    `st.secrets["admin"]["clave"]`, que lee la interfaz. Sin ninguno de los dos
    el panel no se dibuja: no hay nada que proteger ni que enseñar.
    """
    try:
        datos = json.loads(Path(base).joinpath("env", "admin_secret.json")
                           .read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(datos, dict):
        return None
    return str(datos.get("clave", "")).strip() or None


# --------------------------------------------------------------------------- #
# Registro de gasto — una línea por lectura pagada
# --------------------------------------------------------------------------- #

# JSON por líneas y no CSV ni base de datos: se abre con cualquier cosa, aguanta
# que dos sesiones escriban a la vez (cada `write` es una línea suelta) y una
# línea corrompida no se lleva el resto del archivo por delante.
NOMBRE_REGISTRO = "registro_ia.jsonl"


def ruta_registro(base) -> Path:
    """Dónde se apuntan las lecturas: `env/`, la carpeta que git ya ignora."""
    return Path(base) / "env" / NOMBRE_REGISTRO


def apuntar_uso(uso: Uso, archivo: str, ruta) -> None:
    """Añade una lectura al registro. **Nunca lanza.**

    Se llama justo después de pagar una llamada al modelo, en medio de la
    lectura del PDF: un disco lleno, un permiso mal puesto o una carpeta que no
    existe no pueden tumbar lo que el usuario vino a hacer. Si falla, lo que se
    pierde es una línea de contabilidad.
    """
    linea = {
        # Hora local con huso: el registro lo lee una persona, en su zona.
        "fecha": datetime.now().astimezone().isoformat(timespec="seconds"),
        "archivo": archivo,
        "modelo": uso.modelo,
        "entrada": uso.entrada,
        "salida": uso.salida,
        "cache": uso.cache_lectura,
        "costo_usd": uso.costo_usd,
    }
    try:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with ruta.open("a", encoding="utf-8") as archivo_registro:
            archivo_registro.write(json.dumps(linea, ensure_ascii=False) + "\n")
    except Exception:
        pass


def leer_registro(ruta) -> list[dict]:
    """Las líneas del registro, saltándose las que no se dejen leer.

    Devuelve una lista vacía si el archivo no existe, que es el caso normal
    mientras nadie haya leído ningún PDF con IA.
    """
    try:
        texto = Path(ruta).read_text(encoding="utf-8")
    except Exception:
        return []
    lineas = []
    for cruda in texto.splitlines():
        cruda = cruda.strip()
        if not cruda:
            continue
        try:
            dato = json.loads(cruda)
        except Exception:
            continue
        if isinstance(dato, dict):
            lineas.append(dato)
    return lineas


def _entero(valor) -> int:
    """Un número del registro, venga como venga: el archivo se edita a mano."""
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def _decimal(valor) -> float:
    try:
        return float(valor or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _sumar(cubo: dict, linea: dict) -> None:
    cubo["llamadas"] += 1
    cubo["entrada"] += _entero(linea.get("entrada"))
    cubo["salida"] += _entero(linea.get("salida"))
    cubo["costo"] += _decimal(linea.get("costo_usd"))


def _cubo() -> dict:
    return {"llamadas": 0, "entrada": 0, "salida": 0, "costo": 0.0}


def resumir_registro(lineas: list[dict]) -> dict:
    """Totales del registro, más el desglose por archivo y por día.

    Devuelve datos y no texto: quien lo enseñe decide cuántas filas le caben.
    Los archivos salen de mayor a menor gasto y los días, del más reciente al
    más antiguo.
    """
    total = _cubo()
    por_archivo: dict[str, dict] = {}
    por_dia: dict[str, dict] = {}
    for linea in lineas:
        _sumar(total, linea)
        nombre = str(linea.get("archivo") or "(sin nombre)")
        _sumar(por_archivo.setdefault(nombre, _cubo()), linea)
        dia = str(linea.get("fecha") or "")[:10] or "(sin fecha)"
        _sumar(por_dia.setdefault(dia, _cubo()), linea)
    return {
        "total": total,
        "por_archivo": sorted(por_archivo.items(),
                              key=lambda par: par[1]["costo"], reverse=True),
        "por_dia": sorted(por_dia.items(), key=lambda par: par[0], reverse=True),
    }


# --------------------------------------------------------------------------- #
# Lo que se le pide al modelo
# --------------------------------------------------------------------------- #

_INSTRUCCIONES = """\
Extraes las tablas de un plan de trabajo universitario (SUAyED / UNAM) para
pasarlas a un calendario. Recibes el texto completo del PDF, página por página,
y devuelves JSON según el esquema.

Sólo hay dos clases de tabla que interesan:

1. **actividades** — las entregas del curso, con su fecha límite.
2. **videoconferencias** — las sesiones o asesorías **en vivo**, con su fecha y,
   si el plan la trae, su hora.

Cuando el plan trae una tabla de videoconferencias **por grupo** (varios grupos,
cada uno con su asesor), devuelve **una entrada de `tablas` por grupo**, con su
`grupo` y su `asesor`. No las mezcles: al alumno de un grupo no le sirven las
sesiones del asesor de otro.

Ignora por completo, y no las devuelvas ni como tabla ni como fila suelta:

- **El horario semanal de dudas del asesor**: la tabla con columnas `Días` y
  `Hora` pero sin fechas concretas —«DATOS DEL ASESOR O GRUPO DE ASESORES», con
  «Martes y jueves» y «14:00 a 16:00»—, y las frases del tipo «asesorías todos
  los martes y jueves de 14:00 a 16:00». **No es una tabla de videoconferencias**:
  son las horas en que el asesor atiende dudas, no sesiones a las que haya que
  asistir. No la devuelvas, ni con filas ni vacía, y no calcules sus fechas.
- Videos grabados y sesiones sin fecha propia («verla antes de la unidad 3»).
- Exámenes y parciales, incluida la tabla de `FECHA DE APLICACIÓN`.
- Ponderaciones, valores y escalas de calificación.
- Temarios con horas por tema.
- Cualquier fila de totales o de suma.

Reglas de los campos:

- **Fechas** en ISO `AAAA-MM-DD`. **No inventes fechas**: si una fila no trae,
  deja `fecha` en cadena vacía.
- **El año no es el nombre del semestre.** «Semestre 2027-1» es el primer
  semestre del ciclo 2027 y va de **agosto a diciembre de 2026**; el «2027-2»
  va de enero a junio de 2027. El año sale de las fechas escritas del propio
  documento: las de la tabla de videoconferencias, las de los exámenes, las de
  la portada. Y **todas las tablas de un mismo plan cubren el mismo período**:
  si una trae el año escrito, las demás llevan ése, aunque sus filas sólo digan
  «Jueves 3 de septiembre». Otra comprobación, cuando la fila dice el día de la
  semana: el año bueno es aquel en que esa fecha cae en ese día. Sólo si no hay
  ni un año en todo el documento se usa el año por defecto del mensaje.
- **`resumen`** — reescribe la descripción de la actividad en 1 a 3 frases
  claras y directas: qué hay que hacer o entregar, en qué formato, cuántos
  ejercicios. No copies el enunciado completo ni sus ejercicios uno por uno.
- **`hora_inicio`, `hora_fin` y `lugar`** — sólo en videoconferencias; en
  actividades van en cadena vacía. Las horas, en `HH:MM` de 24 horas y ya
  normalizadas: la de fin nunca es anterior a la de inicio, así que una sesión
  «de 14:00 a 6:00 h.» va de `14:00` a `16:00`, no a las seis de la mañana.
- **`materia`** — el nombre de la asignatura de la portada, en Mayúsculas De
  Título (no TODO EN MAYÚSCULAS), sin la clave ni la carrera.
- **`paginas`** — los números de los marcadores `=== Página N ===` donde está
  cada tabla.
- Los campos sin dato van en cadena vacía, nunca inventados.

No inventes filas ni completes huecos con suposiciones: si el plan no lo dice,
no está.\
"""

# El modo estructurado no admite minLength/maxLength/minimum/pattern, y exige
# `additionalProperties: false` y un `required` con **todas** las propiedades de
# cada objeto. Por eso los campos vacíos son cadena vacía y no ausencia.
_FILA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "unidad": {
            "type": "string",
            "description": "«Unidad 3» o «», tal como identifica el plan la "
                           "unidad, módulo o sesión.",
        },
        "titulo": {
            "type": "string",
            "description": "Nombre corto de la actividad o tema de la sesión.",
        },
        "fecha": {"type": "string", "description": "AAAA-MM-DD o «»."},
        "hora_inicio": {"type": "string", "description": "HH:MM o «»."},
        "hora_fin": {"type": "string", "description": "HH:MM o «»."},
        "resumen": {
            "type": "string",
            "description": "1 a 3 frases con lo esencial de la descripción.",
        },
        "lugar": {
            "type": "string",
            "description": "Liga de Zoom o Meet, aula, plataforma, o «».",
        },
    },
    "required": ["unidad", "titulo", "fecha", "hora_inicio", "hora_fin",
                 "resumen", "lugar"],
}

_TABLA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "tipo": {"type": "string", "enum": ["actividades", "videoconferencias"]},
        "grupo": {
            "type": "string",
            "description": "Número de grupo, sólo en videoconferencias. «» si no lo trae.",
        },
        "asesor": {
            "type": "string",
            "description": "Nombre del asesor, sólo en videoconferencias. «» si no lo trae.",
        },
        "paginas": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Páginas de los marcadores «=== Página N ===».",
        },
        "filas": {"type": "array", "items": _FILA},
    },
    "required": ["tipo", "grupo", "asesor", "paginas", "filas"],
}

_ESQUEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "materia": {
            "type": "string",
            "description": "Asignatura de la portada, en Mayúsculas De Título.",
        },
        "tablas": {"type": "array", "items": _TABLA},
    },
    "required": ["materia", "tablas"],
}


# --------------------------------------------------------------------------- #
# De JSON a Candidata
# --------------------------------------------------------------------------- #

# Los nombres de columna son los que `deteccion.detectar_columnas` mapea solo,
# los mismos que traen los PDF reales. No los cambies sin tocar `deteccion`.
#
# Las actividades no traen ni «Fecha final» ni «Lugar»: el mapeo del modo día ya
# no pide ninguna de las dos, así que serían columnas que nadie puede usar. Los
# rangos escritos en una sola celda («del 20 al 25 de octubre») los sigue
# resolviendo `fechas.parse_fecha_fin` sobre la propia columna de fecha.
_COLUMNAS_ACTIVIDADES = ["Unidad", "Nombre de la actividad", "Fecha de entrega",
                         "Descripción"]
_COLUMNAS_VIDEOCONFERENCIAS = ["Sesión", "Nombre de la sesión", "Fecha",
                               "Hora de inicio", "Hora de fin", "Lugar o liga"]


def _txt(fila: dict, campo: str) -> str:
    """El campo como texto limpio. El modelo puede mandar null o un número."""
    valor = fila.get(campo)
    if valor is None:
        return ""
    return str(valor).strip()


def _filas_utiles(bruto: dict) -> list[dict]:
    """Las filas que dicen algo: sin título y sin fecha no hay evento posible."""
    filas = bruto.get("filas") or []
    return [f for f in filas
            if isinstance(f, dict) and (_txt(f, "titulo") or _txt(f, "fecha"))]


def _df_actividades(filas: list[dict]) -> pd.DataFrame:
    registros = [[_txt(f, "unidad"), _txt(f, "titulo"), _txt(f, "fecha"),
                  _txt(f, "resumen")]
                 for f in filas]
    return pd.DataFrame(registros, columns=_COLUMNAS_ACTIVIDADES)


def _df_videoconferencias(filas: list[dict]) -> pd.DataFrame:
    registros = []
    for f in filas:
        # El resumen de una sesión en vivo no aporta nada al calendario —el tema
        # ya está en el título—, salvo cuando el título viene vacío y es lo
        # único que hay para nombrar el evento.
        titulo = _txt(f, "titulo") or _txt(f, "resumen")
        registros.append([_txt(f, "unidad"), titulo, _txt(f, "fecha"),
                          _txt(f, "hora_inicio"), _txt(f, "hora_fin"),
                          _txt(f, "lugar")])
    return pd.DataFrame(registros, columns=_COLUMNAS_VIDEOCONFERENCIAS)


def _paginas(bruto: dict) -> list[int]:
    salida = []
    for valor in bruto.get("paginas") or []:
        try:
            salida.append(int(valor))
        except (TypeError, ValueError):
            continue
    return sorted(set(salida))


def _candidatas(datos: dict, anio_defecto: int) -> list:
    """El JSON del modelo → las mismas `Candidata` que devuelve `pdf.extraer`."""
    materia = _txt(datos, "materia")

    candidatas = []
    for bruto in datos.get("tablas") or []:
        if not isinstance(bruto, dict):
            continue
        tipo = _txt(bruto, "tipo")

        filas = _filas_utiles(bruto)
        if not filas:
            continue

        if tipo == pdf.TIPO_ACTIVIDADES:
            df = _df_actividades(filas)
        elif tipo == pdf.TIPO_VIDEOCONFERENCIAS:
            df = _df_videoconferencias(filas)
        else:
            continue
        if df.empty:
            continue

        es_video = tipo == pdf.TIPO_VIDEOCONFERENCIAS
        candidata = pdf.Candidata(
            df=df,
            tipo=tipo,
            paginas=_paginas(bruto),
            grupo=_txt(bruto, "grupo") if es_video else "",
            asesor=_txt(bruto, "asesor") if es_video else "",
            materia=materia,
        )
        # Mismo aviso que el lector clásico: el usuario tiene que enterarse de
        # que faltan fechas lea quien lea el PDF.
        if candidata.confianza < 1.0:
            faltan = len(df) - candidata.filas_con_fecha
            candidata.avisos.append(
                f"{faltan} de {len(df)} filas se quedaron sin una fecha que yo entienda."
            )
        candidatas.append(candidata)

    aviso = _aviso_de_anios(candidatas, anio_defecto)
    if aviso:
        _avisar(candidatas, aviso)

    candidatas.sort(key=lambda c: (c.tipo != pdf.TIPO_ACTIVIDADES,
                                   -c.confianza, -len(c.df)))
    return candidatas


# --------------------------------------------------------------------------- #
# Los años del plan
# --------------------------------------------------------------------------- #

# Las dos columnas de fecha que arma este módulo, para leer de vuelta el período
# que cubre el plan sin tener que adivinar el nombre de la columna.
_COLUMNAS_DE_FECHA = (_COLUMNAS_ACTIVIDADES[2], _COLUMNAS_VIDEOCONFERENCIAS[2])


def _fechas_de(candidata, anio_defecto: int) -> list[date]:
    """Las fechas que se entienden de una candidata ya armada."""
    for columna in _COLUMNAS_DE_FECHA:
        if columna in candidata.df.columns:
            return [f for f in (fechas.parse_fecha(v, True, anio_defecto)
                                for v in candidata.df[columna]) if f is not None]
    return []


def _avisar(candidatas: list, texto: str) -> None:
    """Cuelga un aviso de la tabla de actividades, que es la que todos miran.

    La interfaz sólo enseña los avisos de las tablas marcadas, y las actividades
    vienen marcadas de entrada; a falta de ellas, en la primera candidata que
    haya. Si no quedó ninguna, la lista sale vacía y quien llama cae al lector
    clásico, que dará su propio diagnóstico.
    """
    if not candidatas:
        return
    anfitriona = next((c for c in candidatas if c.tipo == pdf.TIPO_ACTIVIDADES),
                      candidatas[0])
    anfitriona.avisos.append(texto)


def _aviso_de_anios(candidatas: list, anio_defecto: int) -> str:
    """Avisa si las fechas del plan no caben en un solo semestre. «» si cuadran.

    Existe por un caso real: un plan cuyas actividades no escriben el año
    («Jueves 3 de septiembre») y una portada que dice «Semestre 2027-1» —que en
    la UNAM va de agosto a diciembre de **2026**—. El modelo fechó las
    actividades en 2027 y las videoconferencias en 2026, y el plan entero salió
    abarcando quince meses. Un semestre no llega a `_MAX_DIAS_PERIODO` días, así
    que cuando el rango los pasa alguna tabla quedó con el año equivocado y hay
    que decirlo: es de las pocas cosas que el usuario no va a notar mirando la
    lista de eventos, porque cada fecha por separado parece correcta.

    La regla del año vive en `_INSTRUCCIONES`, que es donde se corrige el
    problema; esto es sólo la red por debajo.
    """
    todas = sorted(f for c in candidatas for f in _fechas_de(c, anio_defecto))
    if not todas or (todas[-1] - todas[0]).days <= _MAX_DIAS_PERIODO:
        return ""

    anios = sorted({f.year for f in todas})
    revoltijo = ("mezclan los años " + " y ".join(str(a) for a in anios)
                 if len(anios) > 1 else "abarcan más de un semestre")
    return (
        f"Las fechas del plan {revoltijo} (de {todas[0]:%d/%m/%Y} a "
        f"{todas[-1]:%d/%m/%Y}), y un semestre no dura tanto: alguna tabla quedó "
        "con el año equivocado. Conviene revisar los años antes de exportar."
    )


# --------------------------------------------------------------------------- #
# La llamada
# --------------------------------------------------------------------------- #

def _pedir(cliente, texto: str, modelo: str, anio_defecto: int):
    """La llamada a la API, con los fallos traducidos a `ErrorDeIA`.

    El orden de los `except` importa: las tres primeras son subclases de
    `APIStatusError`, y al revés las atraparía todas el caso genérico.

    **De aquí no sale nada que no sea `ErrorDeIA`**, y por eso el último caso lo
    atrapa todo: quien llama sólo espera esa excepción, y cualquier otra revienta
    la app sin darle ocasión de apuntar el fallo, así que la siguiente
    reejecución vuelve a llamar a la API y a pagarla. No basta con la lista de
    arriba: `APIResponseValidationError`, por ejemplo, cuelga de `APIError` y no
    de `APIStatusError`.
    """
    extras = {}
    if modelo.startswith("gpt-5"):
        # La familia gpt-5 razona antes de contestar y esos tokens se cobran como
        # salida; para extracción con esquema, «low» rinde bien y no dispara el
        # costo.
        extras["reasoning_effort"] = "low"

    # No hay nada que cachear a mano: OpenAI cachea solo los prefijos largos.
    try:
        return cliente.chat.completions.create(
            model=modelo,
            # `max_tokens` está retirado en gpt-5; el nombre nuevo es éste.
            max_completion_tokens=_MAX_TOKENS,
            messages=[
                {"role": "system", "content": _INSTRUCCIONES},
                {"role": "user",
                 "content": f"Año por defecto si el documento no lo dice: "
                            f"{anio_defecto}\n\n{texto}"},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "plan_de_trabajo", "strict": True,
                                "schema": _ESQUEMA},
            },
            **extras,
        )
    except openai.AuthenticationError as e:
        raise ErrorDeIA("La clave de la API de OpenAI no es válida.") from e
    except openai.PermissionDeniedError as e:
        raise ErrorDeIA(
            f"Esta clave no tiene permiso para usar el modelo «{modelo}»."
        ) from e
    except openai.RateLimitError as e:
        raise ErrorDeIA(
            "Demasiadas peticiones seguidas; espera un momento y reintenta."
        ) from e
    except openai.APIStatusError as e:
        raise ErrorDeIA(
            f"La API de OpenAI respondió con un error {e.status_code}: {e}"
        ) from e
    except openai.APIConnectionError as e:
        raise ErrorDeIA(
            "No hubo conexión con la API de OpenAI. Revisa tu internet e "
            "inténtalo de nuevo."
        ) from e
    except Exception as e:
        # Lo que no encaja en ningún caso de arriba: otros `APIError`, un fallo
        # del propio SDK, lo que sea. Se conserva el mensaje original porque es
        # lo único que hay para diagnosticarlo.
        raise ErrorDeIA(
            f"Falló la llamada a la API de OpenAI: {type(e).__name__}: {e}"
        ) from e


def _uso_de(respuesta, modelo: str) -> Uso:
    uso = respuesta.usage
    detalles = getattr(uso, "prompt_tokens_details", None)
    return Uso(
        modelo=modelo,
        # `prompt_tokens` ya incluye los cacheados; `cache_lectura` es la parte
        # de ésos que se cobra al precio rebajado.
        entrada=getattr(uso, "prompt_tokens", 0) or 0,
        salida=getattr(uso, "completion_tokens", 0) or 0,
        # El desglose de caché no viene en todas las respuestas.
        cache_lectura=getattr(detalles, "cached_tokens", 0) or 0,
    )


def extraer(texto: str, clave_api: str, modelo: str = MODELO_POR_DEFECTO,
            anio_defecto: int = 2026) -> ResultadoIA:
    """Texto de un PDF → tablas candidatas, en el mismo formato que `pdf.extraer`.

    Si el plan no trae ninguna tabla aprovechable devuelve la lista vacía **sin
    excepción**: quien llama decide si cae al lector clásico o se rinde.
    """
    if not DISPONIBLE:
        raise ErrorDeIA(
            "Falta la librería de OpenAI. Instálala con: pip install openai"
        )
    clave_api = (clave_api or "").strip()
    if not clave_api:
        raise ErrorDeIA("Falta la clave de la API de OpenAI.")
    if not (texto or "").strip():
        raise ErrorDeIA("El PDF no tiene texto que mandarle al modelo.")

    cliente = openai.OpenAI(api_key=clave_api, timeout=_ESPERA_SEGUNDOS,
                            max_retries=1)
    respuesta = _pedir(cliente, texto, modelo, anio_defecto)

    # Una respuesta sin `choices` es rarísima, pero indexarla a ciegas daría un
    # `IndexError` que se escaparía de `ErrorDeIA` y reventaría a quien llama.
    elecciones = getattr(respuesta, "choices", None) or []
    if not elecciones:
        raise ErrorDeIA(
            "La API de OpenAI devolvió una respuesta vacía; vuelve a intentarlo."
        )

    eleccion = elecciones[0]
    if getattr(eleccion.message, "refusal", None):
        raise ErrorDeIA("El modelo declinó procesar este documento.")
    if eleccion.finish_reason == "length":
        raise ErrorDeIA(
            "La respuesta del modelo se quedó a medias (PDF demasiado largo)."
        )

    # El modo estructurado garantiza que el contenido es JSON válido según el
    # esquema; el `try` cubre el caso raro de que no lo sea.
    try:
        datos = json.loads(eleccion.message.content or "")
    except json.JSONDecodeError as e:
        raise ErrorDeIA(
            "El modelo devolvió algo que no es JSON; vuelve a intentarlo."
        ) from e

    return ResultadoIA(candidatas=_candidatas(datos, anio_defecto),
                       uso=_uso_de(respuesta, modelo))
