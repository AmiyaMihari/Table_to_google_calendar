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
from pathlib import Path

import pandas as pd

from . import pdf

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

- Videos grabados y sesiones sin fecha propia («verla antes de la unidad 3»).
- Exámenes y parciales, incluida la tabla de `FECHA DE APLICACIÓN`.
- Ponderaciones, valores y escalas de calificación.
- Temarios con horas por tema.
- Horarios recurrentes sin fechas concretas («martes de 19 a 21 h»).
- Cualquier fila de totales o de suma.

Reglas de los campos:

- **Fechas** en ISO `AAAA-MM-DD`. El año sale del propio documento (el período
  del curso, las fechas del semestre); sólo si el documento no lo dice usa el
  año por defecto que viene en el mensaje. **No inventes fechas**: si una fila
  no trae, deja `fecha` en cadena vacía.
- **`resumen`** — reescribe la descripción de la actividad en 1 a 3 frases
  claras y directas: qué hay que hacer o entregar, en qué formato, cuántos
  ejercicios. No copies el enunciado completo ni sus ejercicios uno por uno.
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
        "fecha_fin": {
            "type": "string",
            "description": "AAAA-MM-DD o «». Para rangos «del 20 al 25...».",
        },
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
    "required": ["unidad", "titulo", "fecha", "fecha_fin", "hora_inicio",
                 "hora_fin", "resumen", "lugar"],
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
_COLUMNAS_ACTIVIDADES = ["Unidad", "Nombre de la actividad", "Fecha de entrega",
                         "Fecha final", "Descripción", "Lugar"]
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
                  _txt(f, "fecha_fin"), _txt(f, "resumen"), _txt(f, "lugar")]
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


def _candidatas(datos: dict) -> list:
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

    candidatas.sort(key=lambda c: (c.tipo != pdf.TIPO_ACTIVIDADES,
                                   -c.confianza, -len(c.df)))
    return candidatas


# --------------------------------------------------------------------------- #
# La llamada
# --------------------------------------------------------------------------- #

def _pedir(cliente, texto: str, modelo: str, anio_defecto: int):
    """La llamada a la API, con los fallos traducidos a `ErrorDeIA`.

    El orden de los `except` importa: las tres primeras son subclases de
    `APIStatusError`, y al revés las atraparía todas el caso genérico.
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

    eleccion = respuesta.choices[0]
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

    return ResultadoIA(candidatas=_candidatas(datos), uso=_uso_de(respuesta, modelo))
