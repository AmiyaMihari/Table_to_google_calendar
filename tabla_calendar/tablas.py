"""Carga de tablas desde CSV, Excel y ODS.

El problema típico de los planes de trabajo: el encabezado real no está en la
primera fila (hay logos, títulos y filas en blanco arriba), las celdas de la
columna "Unidad" están combinadas, y las fechas vienen como fecha real de Excel.
Aquí se resuelve todo eso antes de que nadie mapee columnas.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import fechas

EXTENSIONES = (".csv", ".xlsx", ".xlsm", ".xls", ".ods", ".txt", ".tsv")

_MOTORES = {
    ".xlsx": "openpyxl",
    ".xlsm": "openpyxl",
    ".xltx": "openpyxl",
    ".xltm": "openpyxl",
    ".xls": "xlrd",
    ".ods": "odf",
}

_CODIFICACIONES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

PALABRAS_ENCABEZADO = (
    # español
    "unidad", "actividad", "actividades", "fecha", "entrega", "descripcion",
    "tema", "asesoria", "asesorias", "hora", "horario", "valor", "modulo",
    "semana", "sesion", "titulo", "nombre", "ponderacion", "lugar", "modalidad",
    "tarea", "videoconferencia", "liga", "enlace",
    # inglés (el CSV que exporta Google Calendar viene así)
    "subject", "start", "end", "date", "time", "day", "event", "description",
    "location", "private", "due", "title",
)


class ErrorDeLectura(Exception):
    """Problema al abrir el archivo, con un mensaje entendible para el usuario."""


@dataclass
class Lectura:
    """Resultado de cargar una tabla."""

    df: pd.DataFrame
    hoja: str | None = None
    fila_encabezado: int = 0
    hojas_disponibles: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def _extension(nombre: str) -> str:
    return Path(nombre).suffix.lower()


def es_excel(nombre: str) -> bool:
    return _extension(nombre) in _MOTORES


def _motor(nombre: str) -> str:
    ext = _extension(nombre)
    motor = _MOTORES.get(ext)
    if motor is None:
        raise ErrorDeLectura(f"No sé leer archivos «{ext}».")
    return motor


def listar_hojas(datos: bytes, nombre: str) -> list[str]:
    """Nombres de las hojas de un Excel/ODS."""
    try:
        with pd.ExcelFile(io.BytesIO(datos), engine=_motor(nombre)) as xls:
            return [str(h) for h in xls.sheet_names]
    except ImportError as e:
        raise ErrorDeLectura(_mensaje_motor_faltante(nombre)) from e
    except Exception as e:
        raise ErrorDeLectura(
            f"No pude abrir el archivo. Verifica que no esté protegido con contraseña "
            f"ni dañado.\n\nDetalle: {type(e).__name__}: {e}"
        ) from e


def _mensaje_motor_faltante(nombre: str) -> str:
    ext = _extension(nombre)
    paquete = {"xlrd": "xlrd", "odf": "odfpy"}.get(_MOTORES.get(ext, ""), "openpyxl")
    return (
        f"Falta la librería para leer archivos «{ext}». "
        f"Instálala con: pip install {paquete}"
    )


def _decodificar(datos: bytes) -> str:
    for cod in _CODIFICACIONES:
        try:
            return datos.decode(cod)
        except UnicodeDecodeError:
            continue
    return datos.decode("utf-8", errors="replace")


def _delimitador(texto: str) -> str:
    muestra = texto[:8192]
    try:
        return csv.Sniffer().sniff(muestra, delimiters=",;\t|").delimiter
    except Exception:
        conteos = {d: muestra.count(d) for d in (",", ";", "\t", "|")}
        return max(conteos, key=conteos.get) if max(conteos.values()) else ","


def leer_crudo(datos: bytes, nombre: str, hoja: str | None = None) -> pd.DataFrame:
    """Lee el archivo tal cual, sin interpretar encabezados (header=None)."""
    if es_excel(nombre):
        try:
            df = pd.read_excel(
                io.BytesIO(datos),
                sheet_name=hoja if hoja is not None else 0,
                header=None,
                dtype=object,        # <- clave: conserva las fechas como fechas
                engine=_motor(nombre),
            )
        except ImportError as e:
            raise ErrorDeLectura(_mensaje_motor_faltante(nombre)) from e
        except Exception as e:
            raise ErrorDeLectura(
                f"No pude leer la hoja «{hoja}».\n\nDetalle: {type(e).__name__}: {e}"
            ) from e
        if isinstance(df, dict):  # por si sheet_name devolvió varias
            df = next(iter(df.values()))
        return df

    texto = _decodificar(datos)
    try:
        return pd.read_csv(
            io.StringIO(texto),
            header=None,
            sep=_delimitador(texto),
            dtype=object,
            keep_default_na=False,
            na_values=[""],
            engine="python",
            skip_blank_lines=False,
        )
    except Exception as e:
        raise ErrorDeLectura(
            f"No pude leer el CSV. Revisa que no tenga filas con distinto número de "
            f"columnas.\n\nDetalle: {type(e).__name__}: {e}"
        ) from e


def _perfil(fila: list) -> tuple[str, ...]:
    """Tipo de dato de cada celda, para comparar filas entre sí."""
    tipos = []
    for v in fila:
        if fechas.es_vacio(v):
            tipos.append("vacio")
        elif fechas.tiene_pinta_de_fecha(v):
            tipos.append("fecha")
        elif fechas.tiene_pinta_de_hora(v):
            tipos.append("hora")
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            tipos.append("numero")
        else:
            tipos.append("texto")
    return tuple(tipos)


def detectar_fila_encabezado(crudo: pd.DataFrame, max_filas: int = 15) -> int:
    """Adivina en qué fila están los títulos de las columnas."""
    mejor, mejor_puntaje = 0, float("-inf")
    total_cols = max(1, crudo.shape[1])
    perfiles = [_perfil(list(crudo.iloc[i])) for i in range(len(crudo))]

    for i in range(min(max_filas, len(crudo))):
        fila = list(crudo.iloc[i])
        valores = [str(v).strip() for v in fila if not fechas.es_vacio(v)]
        if len(valores) < 2:
            continue

        puntaje = len(valores) * 2.0
        puntaje += 10.0 * len(valores) / total_cols          # filas completas ganan

        # Palabra completa: si no, "matemáticas" cuenta como "tema" y "valores"
        # como "valor", y una fila de datos gana como si fuera encabezado.
        texto = fechas.normalizar(" ".join(valores))
        palabras = set(re.findall(r"[a-z0-9]+", texto))
        puntaje += 14.0 * len(palabras & set(PALABRAS_ENCABEZADO))

        # Los encabezados son textos cortos; los datos traen fechas y párrafos.
        largo_medio = sum(len(v) for v in valores) / len(valores)
        puntaje += 8.0 if largo_medio <= 35 else -6.0
        puntaje -= 12.0 * sum(1 for t in perfiles[i] if t in ("fecha", "hora"))
        puntaje -= 4.0 * sum(1 for t in perfiles[i] if t == "numero")

        # Señal que no depende del idioma: el encabezado NO se parece a los datos
        # que tiene debajo, mientras que una fila de datos sí.
        siguientes = perfiles[i + 1:i + 4]
        if siguientes:
            distintas = sum(
                1 for col in range(total_cols)
                if all(s[col] != perfiles[i][col] for s in siguientes)
            )
            puntaje += 18.0 * distintas / total_cols

        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = i, puntaje

    return mejor


def _nombres_unicos(valores: list) -> list[str]:
    nombres, vistos = [], {}
    for i, v in enumerate(valores):
        base = "" if fechas.es_vacio(v) else re.sub(r"\s+", " ", str(v)).strip()
        if not base:
            base = f"Columna {i + 1}"
        if base in vistos:
            vistos[base] += 1
            base = f"{base} ({vistos[base]})"
        else:
            vistos[base] = 1
        nombres.append(base)
    return nombres


def aplicar_encabezado(crudo: pd.DataFrame, fila: int) -> pd.DataFrame:
    """Usa `fila` como encabezado y devuelve la tabla limpia."""
    fila = max(0, min(int(fila), max(0, len(crudo) - 1)))
    df = crudo.iloc[fila + 1:].copy()
    df.columns = _nombres_unicos(list(crudo.iloc[fila]))

    df = df.dropna(axis=1, how="all")
    df = df.loc[:, [c for c in df.columns if not df[c].map(fechas.es_vacio).all()]]
    df = df[~df.apply(lambda r: all(fechas.es_vacio(v) for v in r), axis=1)]
    return df.reset_index(drop=True)


def cargar(
    datos: bytes,
    nombre: str,
    hoja: str | None = None,
    fila_encabezado: int | None = None,
    max_filas: int = 3000,
) -> Lectura:
    """Punto de entrada: bytes del archivo → tabla lista para mapear."""
    hojas: list[str] = []
    if es_excel(nombre):
        hojas = listar_hojas(datos, nombre)
        if not hojas:
            raise ErrorDeLectura("El archivo no tiene hojas legibles.")
        if hoja not in hojas:
            hoja = hojas[0]
    else:
        hoja = None

    crudo = leer_crudo(datos, nombre, hoja)
    if crudo.empty:
        raise ErrorDeLectura("La hoja está vacía.")

    avisos: list[str] = []
    if fila_encabezado is None:
        fila_encabezado = detectar_fila_encabezado(crudo)
        if fila_encabezado > 0:
            avisos.append(
                f"Detecté los títulos de columna en la fila {fila_encabezado + 1}; "
                f"ignoré las {fila_encabezado} filas de arriba."
            )

    df = aplicar_encabezado(crudo, fila_encabezado)
    if df.empty:
        raise ErrorDeLectura(
            "No quedaron filas de datos debajo del encabezado. "
            "Ajusta la fila de encabezado en «Ajustes de lectura»."
        )

    if len(df) > max_filas:
        avisos.append(f"La tabla tiene {len(df)} filas; sólo usaré las primeras {max_filas}.")
        df = df.head(max_filas)

    return Lectura(
        df=df,
        hoja=hoja,
        fila_encabezado=fila_encabezado,
        hojas_disponibles=hojas,
        avisos=avisos,
    )
