"""Detección automática de qué columna es cuál.

No basta con mirar el nombre del encabezado: muchos planes traen columnas
llamadas "Columna 3" o "Unnamed". Por eso cada columna se puntúa combinando
el nombre con una muestra de su contenido (¿parece fecha? ¿parece párrafo?).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import fechas

CAMPOS = (
    "fecha", "hora", "hora_fin", "unidad", "titulo", "descripcion", "fecha_fin", "lugar",
)

# Qué columnas tiene sentido pedir según el tipo de evento. Mostrar sólo éstas
# evita el batidillo de mezclar campos de entregas con campos de asesorías.
CAMPOS_POR_MODO = {
    "dia": {
        "principales": ("fecha", "titulo", "unidad", "descripcion"),
        "opcionales": ("fecha_fin", "lugar"),
    },
    "hora": {
        "principales": ("fecha", "titulo", "hora", "hora_fin"),
        "opcionales": ("descripcion", "lugar", "unidad"),
    },
}

ETIQUETAS = {
    "fecha": "Fecha",
    "fecha_fin": "Fecha final (eventos de varios días)",
    "hora": "Hora de inicio",
    "hora_fin": "Hora de fin",
    "unidad": "Unidad / Módulo",
    "titulo": "Nombre",
    "descripcion": "Descripción",
    "lugar": "Lugar o liga",
}

# Ajustes de redacción para que cada modo hable el idioma de su tabla.
ETIQUETAS_MODO = {
    "dia": {
        "fecha": "Fecha de entrega",
        "titulo": "Nombre de la actividad",
        "unidad": "Unidad / Módulo / Semana",
    },
    "hora": {
        "fecha": "Fecha de la sesión",
        "titulo": "Nombre de la sesión",
        "unidad": "Número de sesión",
        "lugar": "Liga (Zoom, Meet…) o aula",
    },
}


def etiqueta(campo: str, modo: str = "dia") -> str:
    return ETIQUETAS_MODO.get(modo, {}).get(campo) or ETIQUETAS[campo]


def campos_de(modo: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    cfg = CAMPOS_POR_MODO.get(modo, CAMPOS_POR_MODO["dia"])
    return cfg["principales"], cfg["opcionales"]

# El orden importa: las primeras palabras valen más.
PALABRAS = {
    "fecha": (
        "fecha de entrega", "fecha limite", "fecha de asesoria", "fecha de la sesion",
        "fecha de inicio", "start date", "fecha", "entrega", "vencimiento", "vence",
        "deadline", "due date", "due", "dia", "cuando",
    ),
    "fecha_fin": (
        "fecha final", "fecha de cierre", "end date", "fecha fin", "hasta",
        "cierre", "termino",
    ),
    "hora": (
        "hora de inicio", "start time", "horario", "hora inicio", "hora", "hrs",
        "inicio", "time",
    ),
    "hora_fin": (
        "hora de fin", "end time", "hora final", "hora fin", "hasta las",
        "termina", "fin",
    ),
    "unidad": (
        "unidad", "modulo", "no. de unidad", "num unidad", "semana", "bloque",
        "sesion", "tema", "eje",
    ),
    "titulo": (
        "nombre de la actividad", "nombre de la asesoria", "actividad", "asesoria",
        "videoconferencia", "sesion", "nombre", "titulo", "tarea", "asunto",
        "evento", "subject", "title", "no. actividad", "n° actividad",
    ),
    "descripcion": (
        "descripcion de la actividad", "descripcion", "description", "detalle",
        "instrucciones", "indicaciones", "observaciones", "contenido",
        "comentarios", "notas", "notes", "especificaciones",
    ),
    "lugar": (
        "lugar", "ubicacion", "location", "modalidad", "aula", "salon", "liga",
        "enlace", "link", "zoom", "plataforma", "sede",
    ),
}

# Columnas de relleno que nunca sirven como título ni descripción.
_VALORES_BOOLEANOS = {
    "true", "false", "verdadero", "falso", "si", "no", "x", "0", "1", "n/a",
}

# Se asignan en este orden; cada columna se usa una sola vez.
_PRIORIDAD = (
    "fecha", "hora", "hora_fin", "descripcion", "titulo", "unidad", "fecha_fin", "lugar",
)

_UMBRAL = 18.0
_MUESTRA = 40


@dataclass
class Puntaje:
    columna: str
    valor: float
    motivo: str


def _puntaje_nombre(campo: str, columna: str) -> float:
    nombre = fechas.normalizar(columna)
    if not nombre or nombre.startswith("columna ") or nombre.startswith("unnamed"):
        return 0.0
    mejor = 0.0
    for i, palabra in enumerate(PALABRAS[campo]):
        peso = max(1.0, 12.0 - i)
        if nombre == palabra:
            mejor = max(mejor, 60.0 + peso)
        elif palabra in nombre:
            mejor = max(mejor, 38.0 + peso)
        elif nombre in palabra and len(nombre) >= 4:
            mejor = max(mejor, 26.0 + peso)
    return mejor


def _muestra(serie: pd.Series) -> list:
    valores = [v for v in serie.tolist() if not fechas.es_vacio(v)]
    return valores[:_MUESTRA]


def _puntaje_contenido(campo: str, serie: pd.Series, dayfirst: bool) -> float:
    valores = _muestra(serie)
    if not valores:
        return -10.0

    n = len(valores)
    textos = [str(v).strip() for v in valores]
    largo_medio = sum(len(t) for t in textos) / n
    unicidad = len(set(textos)) / n

    if campo in ("fecha", "fecha_fin"):
        prop = sum(1 for v in valores if fechas.parse_fecha(v, dayfirst, 2025)) / n
        return prop * 55.0 - (12.0 if prop < 0.3 else 0.0)

    if campo in ("hora", "hora_fin"):
        prop_hora = sum(1 for v in valores if fechas.tiene_pinta_de_hora(v)) / n
        prop_fecha = sum(1 for v in valores if fechas.parse_fecha(v, dayfirst, 2025)) / n
        return prop_hora * 45.0 - prop_fecha * 25.0

    # Columnas de texto: penalizamos las que en realidad son fechas.
    prop_fecha = sum(1 for v in valores if fechas.parse_fecha(v, dayfirst, 2025)) / n
    castigo = prop_fecha * 30.0

    # "All Day Event" con puros False parecía un buen título por ser texto corto.
    if all(fechas.normalizar(t) in _VALORES_BOOLEANOS for t in textos):
        return -60.0
    if campo in ("titulo", "descripcion") and unicidad < 0.5:
        castigo += 20.0

    if campo == "unidad":
        cortos = sum(1 for t in textos if len(t) <= 12) / n
        numericos = sum(1 for t in textos if any(c.isdigit() for c in t)) / n
        repetidos = 1.0 - unicidad
        return cortos * 16.0 + numericos * 10.0 + repetidos * 12.0 - castigo

    if campo == "titulo":
        bueno = 18.0 if 4 <= largo_medio <= 70 else -4.0
        return bueno + unicidad * 14.0 - castigo

    if campo == "descripcion":
        bueno = 24.0 if largo_medio >= 60 else (8.0 if largo_medio >= 25 else -8.0)
        return bueno + unicidad * 8.0 - castigo

    if campo == "lugar":
        pistas = sum(1 for t in textos if any(
            p in fechas.normalizar(t) for p in ("zoom", "http", "aula", "salon", "linea", "presencial")
        )) / n
        return pistas * 30.0 - castigo

    return 0.0


def detectar_columnas(
    df: pd.DataFrame, dayfirst: bool = True, modo: str = "dia"
) -> dict[str, str | None]:
    """Devuelve {campo: nombre_de_columna | None} para los campos del modo."""
    principales, opcionales = campos_de(modo)
    relevantes = set(principales) | set(opcionales)

    columnas = list(df.columns)
    puntajes: dict[str, dict[str, float]] = {}
    for campo in CAMPOS:
        if campo not in relevantes:
            continue
        puntajes[campo] = {
            col: _puntaje_nombre(campo, col) + _puntaje_contenido(campo, df[col], dayfirst)
            for col in columnas
        }

    # Asignación por mejor puntaje global, no por orden fijo de campos: así una
    # columna llamada "Subject" se lleva el título aunque su texto sea largo y
    # también puntúe alto como descripción.
    pares = sorted(
        ((p, _PRIORIDAD.index(campo), campo, col)
         for campo, cols in puntajes.items() for col, p in cols.items()
         if p >= _UMBRAL),
        key=lambda x: (-x[0], x[1]),
    )

    mapeo: dict[str, str | None] = {c: None for c in CAMPOS}
    usadas: set[str] = set()
    for _, _, campo, col in pares:
        if mapeo[campo] is None and col not in usadas:
            mapeo[campo] = col
            usadas.add(col)

    # Si no hubo columna de título pero sí de descripción, la descripción manda.
    if mapeo["titulo"] is None and mapeo["descripcion"] is not None:
        mapeo["titulo"] = mapeo["descripcion"]

    return mapeo


def hay_horarios(df: pd.DataFrame, columna: str | None) -> bool:
    """True si la columna de horario trae horas de verdad en al menos 1 de cada 3 filas."""
    if not columna or columna not in df.columns:
        return False
    valores = _muestra(df[columna])
    if not valores:
        return False
    return sum(1 for v in valores if fechas.tiene_pinta_de_hora(v)) / len(valores) >= 0.33
