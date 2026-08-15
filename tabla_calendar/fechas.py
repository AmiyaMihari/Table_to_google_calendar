"""Lectura tolerante de fechas y horas escritas por humanos (en español).

Los planes de trabajo de SUAyED traen las fechas de mil formas distintas:
celdas de Excel con fecha real, "19- feb-25", "21 de agosto de 2025",
"del 21 al 25 de agosto", "16:00 a 18:00 hrs"... Este módulo las normaliza.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

MESES = {
    "ene": 1, "enero": 1,
    "feb": 2, "febrero": 2,
    "mar": 3, "marzo": 3,
    "abr": 4, "abril": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "junio": 6,
    "jul": 7, "julio": 7,
    "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "septiembre": 9, "setiembre": 9,
    "oct": 10, "octubre": 10,
    "nov": 11, "noviembre": 11,
    "dic": 12, "diciembre": 12,
}

# Sólo para borrarlos del texto de una fecha («Jueves 3 de septiembre»): aquí no
# se lee ningún horario que se repita por días de la semana.
DIAS_SEMANA = (
    "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo",
)

# Excel guarda las fechas como número de días desde esta base.
_BASE_EXCEL = date(1899, 12, 30)

_ACENTOS = str.maketrans("áéíóúàèìòùäëïöüñÁÉÍÓÚÑÜ", "aeiouaeiouaeiounAEIOUNU")

_VACIOS = {"", "nan", "nat", "none", "null", "-", "--", "n/a", "na", "s/f", "sin fecha"}


def es_vacio(valor) -> bool:
    """True si el valor no aporta información (None, NaN, celda vacía, guion...)."""
    if valor is None:
        return True
    if isinstance(valor, float) and valor != valor:  # NaN
        return True
    if isinstance(valor, (datetime, date, time)):
        return False
    return str(valor).strip().translate(_ACENTOS).lower() in _VACIOS


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y sin espacios de más."""
    return re.sub(r"\s+", " ", str(texto).translate(_ACENTOS).lower()).strip()


# --------------------------------------------------------------------------- #
# Fechas
# --------------------------------------------------------------------------- #

_RE_ISO = re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b")
_RE_NUM = re.compile(r"\b(\d{1,2})\s*[-/.]\s*(\d{1,2})(?:\s*[-/.]\s*(\d{2,4}))?\b")
_RE_DIA_MES = re.compile(
    r"\b(\d{1,2})\s*[-/. ]\s*([a-z]{3,12})\.?(?:\s*[-/. ]\s*(\d{2,4}))?\b"
)
_RE_MES_DIA = re.compile(
    r"\b([a-z]{3,12})\.?\s*[-/. ]\s*(\d{1,2})\b(?:\s*[-/., ]\s*(\d{2,4}))?"
)


def _anio_completo(y: int | None, anio_defecto: int | None) -> int | None:
    if y is None:
        return anio_defecto
    if y < 100:
        return 2000 + y
    return y


def _construir(y: int | None, m: int | None, d: int | None) -> date | None:
    if not y or not m or not d:
        return None
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _limpiar_texto_fecha(texto: str) -> str:
    t = normalizar(texto)
    t = re.sub(r"\b(" + "|".join(DIAS_SEMANA) + r")\b", " ", t)
    # "entrega:", "fecha límite:", "hasta el", etc.
    t = re.sub(r"\b(entrega|fecha|limite|hasta|antes|el|los|a las|hrs?|horas?)\b", " ", t)
    t = re.sub(r"\bde[l]?\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _parse_texto(t: str, dayfirst: bool, anio_defecto: int | None) -> date | None:
    m = _RE_ISO.search(t)
    if m:
        return _construir(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = _RE_DIA_MES.search(t)
    if m and (MESES.get(m.group(2)) or MESES.get(m.group(2)[:3])):
        mes = MESES.get(m.group(2)) or MESES[m.group(2)[:3]]
        anio = _anio_completo(int(m.group(3)) if m.group(3) else None, anio_defecto)
        return _construir(anio, mes, int(m.group(1)))

    m = _RE_MES_DIA.search(t)
    if m and (MESES.get(m.group(1)) or MESES.get(m.group(1)[:3])):
        mes = MESES.get(m.group(1)) or MESES[m.group(1)[:3]]
        anio = _anio_completo(int(m.group(3)) if m.group(3) else None, anio_defecto)
        return _construir(anio, mes, int(m.group(2)))

    m = _RE_NUM.search(t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        anio = _anio_completo(int(m.group(3)) if m.group(3) else None, anio_defecto)
        if a > 12 and b <= 12:
            dia, mes = a, b
        elif b > 12 and a <= 12:
            dia, mes = b, a
        else:
            dia, mes = (a, b) if dayfirst else (b, a)
        return _construir(anio, mes, dia)

    return None


def parse_fecha(valor, dayfirst: bool = True, anio_defecto: int | None = None) -> date | None:
    """Convierte casi cualquier cosa en una fecha. Devuelve None si no se puede.

    `dayfirst` decide 03/04/2025 → 3 de abril (True) o 4 de marzo (False).
    `anio_defecto` completa fechas escritas sin año ("21 de agosto").
    """
    if es_vacio(valor):
        return None

    # Objetos de fecha (celdas de Excel leídas correctamente, Timestamp de pandas).
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if hasattr(valor, "to_pydatetime"):
        try:
            return valor.to_pydatetime().date()
        except Exception:
            pass

    # Número de serie de Excel (rango razonable: 1954 – 2064).
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        if 20000 <= float(valor) <= 80000:
            return _BASE_EXCEL + timedelta(days=int(valor))
        return None

    t = _limpiar_texto_fecha(str(valor))
    if not t:
        return None

    # Rangos: "21 al 25 de agosto" → tomamos el inicio, pero el mes/año viven
    # en la parte derecha, así que la parseamos primero y le cambiamos el día.
    partes = re.split(r"\s+al?\s+|\s+a\s+", t)
    if len(partes) >= 2:
        fin = _parse_texto(partes[-1], dayfirst, anio_defecto)
        if fin is not None:
            dia_ini = re.search(r"\b(\d{1,2})\b", partes[0])
            if dia_ini:
                inicio = _construir(fin.year, fin.month, int(dia_ini.group(1)))
                if inicio is not None:
                    return inicio
            return fin

    return _parse_texto(t, dayfirst, anio_defecto)


def parse_fecha_fin(valor, dayfirst: bool = True, anio_defecto: int | None = None) -> date | None:
    """Igual que `parse_fecha`, pero de un rango devuelve el final."""
    if es_vacio(valor) or isinstance(valor, (datetime, date)):
        return parse_fecha(valor, dayfirst, anio_defecto)
    t = _limpiar_texto_fecha(str(valor))
    partes = re.split(r"\s+al?\s+|\s+a\s+", t)
    if len(partes) >= 2:
        return _parse_texto(partes[-1], dayfirst, anio_defecto)
    return None


# --------------------------------------------------------------------------- #
# Horas
# --------------------------------------------------------------------------- #

_RE_HORA = re.compile(
    r"(?<!\d)(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?|hrs?\.?|horas?)?(?!\d)"
)

# Para no confundir los números de una fecha con horas ("21/08/2025 16:00").
#
# El "ni antes ni después dos puntos" de la forma día/mes es imprescindible: sin
# él, el "00-18" de "17:00-18:00" pasa por fecha, se borra, y del rango horario
# sólo queda "17: :00", que se lee como medianoche. Un evento a las 00:00 y sin
# ningún aviso, que es la peor forma de fallar. Los rangos con guion son la
# forma normal de escribir el horario en la mitad de los planes de trabajo.
_RE_FECHA_INCRUSTADA = re.compile(
    r"\b\d{4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,2}\b"
    r"|(?<!:)\b\d{1,2}\s*[-/.]\s*\d{1,2}(?:\s*[-/.]\s*\d{2,4})?\b(?!:)"
    r"|\b\d{1,2}\s*(?:de\s+)?[-/. ]\s*(?:" + "|".join(sorted(MESES, key=len, reverse=True)) +
    r")[a-z]*\.?(?:\s*(?:de\s+)?[-/. ]?\s*\d{2,4})?\b"
)

# "de 4 a 6 pm": un número suelto sólo cuenta si abre un rango contra una hora real.
_RE_INICIO_RANGO = re.compile(r"(?<!\d)(\d{1,2})(?:[:.](\d{2}))?\s*(?:-|–|a|al|hasta)\s*$")


def _aplicar_meridiano(hora: int, marca: str | None) -> int:
    if not marca:
        return hora
    marca = marca.replace(".", "").replace(" ", "")
    if marca.startswith("p") and hora < 12:
        return hora + 12
    if marca.startswith("a") and hora == 12:
        return 0
    return hora


def parse_hora(valor) -> tuple[time | None, time | None]:
    """Extrae (hora_inicio, hora_fin) de textos tipo "16:00 a 18:00 hrs"."""
    if es_vacio(valor):
        return None, None

    if isinstance(valor, datetime):
        return valor.time(), None
    if isinstance(valor, time):
        return valor, None
    if hasattr(valor, "to_pytimedelta"):  # pandas Timedelta
        try:
            segs = int(valor.total_seconds())
            return time(segs // 3600 % 24, segs % 3600 // 60), None
        except Exception:
            pass
    # Fracción de día de Excel (0.5 = 12:00).
    if isinstance(valor, float) and not isinstance(valor, bool) and 0 < valor < 1:
        minutos = round(valor * 24 * 60)
        return time(minutos // 60 % 24, minutos % 60), None

    t = _RE_FECHA_INCRUSTADA.sub(" ", normalizar(valor))
    if not t.strip():
        return None, None

    # Sólo cuentan las horas "fuertes": las que traen minutos (16:00) o marca (6 pm).
    crudas: list[tuple[int, int, str | None]] = []
    for m in _RE_HORA.finditer(t):
        h, mi, marca = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if h > 24 or mi > 59 or (m.group(2) is None and marca is None):
            continue
        if not crudas:
            apertura = _RE_INICIO_RANGO.search(t[:m.start()])
            if apertura:
                crudas.append((int(apertura.group(1)) % 24, int(apertura.group(2) or 0), None))
        crudas.append((h % 24, mi, marca))

    if not crudas:
        return None, None

    # "de 4 a 6 pm": la marca sólo aparece al final, aplica a las dos.
    marca_global = next((c[2] for c in reversed(crudas) if c[2]), None)
    horas = [time(_aplicar_meridiano(h, marca or marca_global), mi) for h, mi, marca in crudas[:2]]

    inicio = horas[0]
    fin = horas[1] if len(horas) > 1 else None
    # "de 10 a 1" casi siempre significa 10:00 – 13:00.
    if fin is not None and fin < inicio and fin.hour < 12:
        fin = time(fin.hour + 12, fin.minute)
    return inicio, fin


def hora_de_fecha(valor) -> tuple[time | None, time | None]:
    """Hora escondida dentro del valor de fecha ("21/08/2025 16:00").

    Una celda de Excel con fecha pura llega como medianoche; eso NO es un
    horario, así que se descarta.
    """
    if isinstance(valor, datetime):
        t = valor.time()
        return (t, None) if (t.hour or t.minute) else (None, None)
    if isinstance(valor, (date, int, float, bool)):
        return None, None
    return parse_hora(valor)


def tiene_pinta_de_fecha(valor, dayfirst: bool = True) -> bool:
    return parse_fecha(valor, dayfirst=dayfirst, anio_defecto=2025) is not None


def tiene_pinta_de_hora(valor) -> bool:
    return parse_hora(valor)[0] is not None
