"""Extracción de tablas desde el PDF del plan de trabajo.

El PDF no se lee como un CSV: `pdfplumber` devuelve decenas de tablas por
documento, la de actividades viene partida en todas las páginas, la descripción
se rompe en cientos de filas de continuación y la rejilla de columnas se
desplaza de una página a otra. Aquí se reconstruyen las dos tablas que
interesan —actividades y videoconferencias en vivo— y se devuelven como
candidatas para que el usuario elija.

Lo que **no** hace este módulo: interpretar fechas (eso es `fechas`), decidir
qué columna es cuál (eso es `deteccion`) ni construir eventos (eso es `modelo`).
Su única salida es un DataFrame rectangular con los nombres de columna que trae
el propio PDF.

Los planes reales vienen en dos formatos distintos, y el módulo tiene que
aguantar los dos:

- **Familia A** — `UNIDAD | ACTIVIDAD | DESCRIPCIÓN | FECHA DE ENTREGA |
  PONDERACIÓN`. El encabezado va partido en dos líneas («FECHA DE» arriba,
  «ENTREGA» abajo) y se repite en cada página; una actividad ocupa una fila y
  decenas de filas de continuación.
- **Familia B** — `Unidad | N° Actividad | Fecha de entrega | Descripción |
  Valor`. Una fila por actividad, y la tabla sigue en la página siguiente **sin
  repetir el encabezado**.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from . import fechas

try:
    import pdfplumber
    DISPONIBLE = True
except ImportError:  # pragma: no cover - depende del entorno
    pdfplumber = None
    DISPONIBLE = False

TIPO_ACTIVIDADES = "actividades"
TIPO_VIDEOCONFERENCIAS = "videoconferencias"

# Debajo de esto una página no tiene texto de verdad: es una imagen escaneada.
_MINIMO_CARACTERES_POR_PAGINA = 50

# Una celda de fecha no pasa de un renglón; una descripción son cientos de
# caracteres. Ver `_indice_de_fecha`.
_MAX_LARGO_FECHA = 80

# Filas de cierre que no son datos ("Suma total de Actividades  60%"). Se
# reconocen por la redacción y no por la cifra: cuánto suman las actividades lo
# decide cada profesor, así que no hay ningún total que dar por sentado.
_PIES = ("suma total", "total de actividades", "total de horas")

# La tabla de exámenes (`PARCIAL | UNIDADES | VALOR | FECHA DE APLICACIÓN`) se
# descarta a propósito: son las mismas fechas para todas las materias y duran
# varios días, así que no valen como evento.
_EXCLUIDAS = ("parcial", "rango", "calificacion", "concepto", "requisitos")


class ErrorDePDF(Exception):
    """Problema al leer el PDF, con un mensaje entendible para el usuario."""


@dataclass
class Candidata:
    """Una tabla reconstruida, lista para que el usuario la acepte o la descarte."""

    df: pd.DataFrame
    tipo: str
    paginas: list[int] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    # Sólo en videoconferencias: cuando el plan trae una tabla por grupo, el
    # número por sí solo no dice nada — al alumno le suena su asesor.
    grupo: str = ""
    asesor: str = ""
    # Dato del documento entero, no de esta tabla; va aquí para que quien elija
    # una candidata lo tenga a mano sin volver a abrir el PDF.
    materia: str = ""

    @property
    def modo(self) -> str:
        # Import local: `modelo` importa `fechas`, y no queremos un ciclo.
        from .modelo import MODO_DIA, MODO_HORA
        return MODO_HORA if self.tipo == TIPO_VIDEOCONFERENCIAS else MODO_DIA

    @property
    def filas_con_fecha(self) -> int:
        col = _columna_de_fecha(self.df)
        if col is None:
            return 0
        return sum(1 for v in self.df[col] if fechas.parse_fecha(v, True, 2026))

    @property
    def confianza(self) -> float:
        """Proporción de filas con una fecha que se entiende (0.0 – 1.0)."""
        if self.df.empty:
            return 0.0
        return self.filas_con_fecha / len(self.df)

    @property
    def nombre(self) -> str:
        """Nombre corto, para identificar de dónde salió cada evento."""
        partes = ["Actividades" if self.tipo == TIPO_ACTIVIDADES
                  else "Videoconferencias"]
        if self.grupo:
            partes.append(f"grupo {self.grupo}")
        if self.asesor:
            partes.append(self.asesor)
        return " · ".join(partes)

    def etiqueta(self) -> str:
        """Nombre largo, para que el usuario elija entre las candidatas."""
        icono = "📝" if self.tipo == TIPO_ACTIVIDADES else "🎥"
        return f"{icono} {self.nombre} — {len(self.df)} filas, {_rango_paginas(self.paginas)}"


def es_pdf(nombre: str) -> bool:
    return nombre.lower().endswith(".pdf")


def _rango_paginas(paginas: list[int]) -> str:
    if not paginas:
        return "sin páginas"
    if len(paginas) == 1:
        return f"pág. {paginas[0]}"
    return f"págs. {min(paginas)}–{max(paginas)}"


# --------------------------------------------------------------------------- #
# Reconocer de qué es cada tabla
# --------------------------------------------------------------------------- #

def _texto_celda(valor) -> str:
    if valor is None:
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def _firma(fila: list) -> str:
    return fechas.normalizar(" ".join(_texto_celda(c) for c in fila))


def _tipo_de_encabezado(fila: list) -> str | None:
    """Qué tabla es, mirando su fila de encabezado. None si no interesa."""
    t = _firma(fila)
    if not t or any(p in t for p in _EXCLUIDAS):
        return None

    hay_fecha = "fecha" in t
    # La tabla de videos grabados (`SESIÓN | TEMA A TRATAR | OBSERVACIONES`) no
    # trae fecha, y por eso queda fuera sola: son videos para ver cuando toque,
    # no sesiones en vivo. Es justo lo que se quiere ignorar.
    if not hay_fecha:
        return None

    if "videoconferencia" in t or "sesion" in t:
        return TIPO_VIDEOCONFERENCIAS
    if ("unidad" in t or "actividad" in t) and ("descripcion" in t or "actividad" in t):
        return TIPO_ACTIVIDADES
    return None


def _nombres_columna(encabezado: list) -> list[str]:
    """Nombres únicos para las columnas, descartando las celdas vacías.

    Compactar el encabezado igual que las filas es lo que hace que las dos
    cosas se puedan alinear: la rejilla de `pdfplumber` trae columnas de sobra
    (15 donde hay 5) y sus índices no significan nada.
    """
    nombres, vistos = [], {}
    for bruto in encabezado:
        base = _texto_celda(bruto)
        if not base:
            continue
        if base in vistos:
            vistos[base] += 1
            base = f"{base} ({vistos[base]})"
        else:
            vistos[base] = 1
        nombres.append(base)
    return nombres


def _indice_por_nombre(columnas: list[str], *palabras: str) -> int | None:
    for i, col in enumerate(columnas):
        if any(p in fechas.normalizar(col) for p in palabras):
            return i
    return None


def _columna_de_fecha(df: pd.DataFrame) -> str | None:
    i = _indice_por_nombre(list(df.columns), "fecha")
    return None if i is None else df.columns[i]


# --------------------------------------------------------------------------- #
# Reconstruir las filas
# --------------------------------------------------------------------------- #

def _compactar(fila: list) -> list[str]:
    """Quita celdas vacías y colapsa duplicados seguidos.

    La rejilla que devuelve `pdfplumber` tiene columnas de sobra y desplazadas:
    el mismo campo cae en el índice 5, 7 u 11 según la página. Lo único estable
    es el **orden** de los valores dentro de la fila, así que se trabaja con la
    fila compactada. Los duplicados seguidos salen de las celdas que ocupan dos
    columnas de la rejilla ("23 de junio 2026 | 23 de junio 2026").
    """
    valores = [_texto_celda(c) for c in fila]
    salida: list[str] = []
    for v in valores:
        if not v:
            continue
        if salida and salida[-1] == v:
            continue
        salida.append(v)
    return salida


def _es_pie(celdas: list[str]) -> bool:
    t = fechas.normalizar(" ".join(celdas))
    return any(p in t for p in _PIES)


def _indice_de_fecha(celdas: list[str], anio: int, preferido: int | None = None) -> int | None:
    """Cuál de las celdas es la fecha de la fila.

    Se exige que la celda sea **corta**: las descripciones de estos planes
    mencionan fechas a mansalva («que vence el 3 de agosto», «El 22 de enero de
    2020 se firmó un pagaré»), y sin este límite el párrafo entero se llevaba el
    papel de columna de fecha y desplazaba toda la fila. Una celda de fecha de
    verdad no pasa de un renglón, ni siquiera con el horario pegado
    ("20 de agosto de 2025 a las 20:00 a 22:00 hrs").
    """
    candidatas = [
        i for i, c in enumerate(celdas)
        if len(c) <= _MAX_LARGO_FECHA and fechas.parse_fecha(c, True, anio) is not None
    ]
    if not candidatas:
        return None
    if preferido is None:
        return candidatas[0]
    return min(candidatas, key=lambda i: (abs(i - preferido), i))


def _abre_registro(celdas: list[str], anio: int) -> bool:
    """¿Esta fila empieza un registro nuevo, o continúa el anterior?

    Una fila de datos trae al menos dos celdas y una de ellas es una fecha; las
    de continuación traen un solo trozo de párrafo. Pedir las dos cosas evita
    que una descripción que mencione una fecha («entregar antes del 15 de
    mayo») parta la actividad en dos.
    """
    return len(celdas) >= 2 and _indice_de_fecha(celdas, anio) is not None


def _colocar(valores: list[str], columnas: list[int], fila: list[str], derecha: bool) -> None:
    """Reparte `valores` entre `columnas`, resolviendo el desajuste de cuenta.

    Si sobran columnas se alinea a la derecha, porque lo que falta suelen ser
    las primeras (el número de grupo sólo viene en la fila de arriba). Si
    sobran valores se alinea a la izquierda y la cola se junta en la última,
    para no perder texto por el camino.
    """
    if not valores or not columnas:
        return
    if len(valores) < len(columnas):
        columnas = columnas[-len(valores):] if derecha else columnas[:len(valores)]
    elif len(valores) > len(columnas):
        cabeza = valores[:len(columnas) - 1]
        valores = cabeza + [" ".join(valores[len(columnas) - 1:])]
    for valor, columna in zip(valores, columnas):
        fila[columna] = valor


def _repartir(celdas: list[str], columnas: list[str], anio: int) -> list[str]:
    """Coloca las celdas compactadas en las columnas del encabezado.

    La fecha ancla la fila: se reconoce por su contenido y se lleva a la
    columna que se llame «fecha». Lo que va antes y lo que va después conserva
    su orden alrededor de ese ancla, así que a una fila con una celda de menos
    no se le corren todas las demás.
    """
    fila = [""] * len(columnas)
    i_columna = _indice_por_nombre(columnas, "fecha")
    i_celda = _indice_de_fecha(celdas, anio, preferido=i_columna)
    if i_columna is None and i_celda is not None:
        i_columna = min(i_celda, len(columnas) - 1)

    if i_celda is None or i_columna is None:
        _colocar(list(celdas), list(range(len(columnas))), fila, derecha=False)
        return fila

    fila[i_columna] = celdas[i_celda]
    _colocar(celdas[:i_celda], list(range(i_columna)), fila, derecha=True)
    _colocar(celdas[i_celda + 1:], list(range(i_columna + 1, len(columnas))),
             fila, derecha=False)
    return fila


def _armar(columnas: list[str], filas: list[list], anio: int) -> pd.DataFrame:
    """Convierte las filas crudas de una tabla en un DataFrame limpio."""
    registros: list[list[str]] = []

    # Las continuaciones se pegan siempre a la misma columna, la de la
    # descripción. Elegir "la más larga de esta fila" fallaba en la primera
    # continuación, cuando la descripción aún era más corta que el nombre de la
    # actividad y el párrafo acababa dentro del título.
    i_desc = _indice_por_nombre(columnas, "descripcion", "tema", "videoconferencia")

    for cruda in filas:
        celdas = _compactar(cruda)
        if not celdas or _es_pie(celdas):
            continue
        if _abre_registro(celdas, anio):
            registros.append(_repartir(celdas, columnas, anio))
        elif registros:
            texto = " ".join(celdas)
            j = i_desc if i_desc is not None else max(
                range(len(columnas)), key=lambda k: len(registros[-1][k])
            )
            registros[-1][j] = (registros[-1][j] + " " + texto).strip()

    return pd.DataFrame(registros, columns=columnas)


# --------------------------------------------------------------------------- #
# Recorrer el documento
# --------------------------------------------------------------------------- #

def _unir_encabezado(tabla: list[list]) -> tuple[list, list[list]]:
    """Junta el encabezado partido en dos filas («FECHA DE» / «ENTREGA»).

    La segunda fila es continuación del encabezado —y no un dato— cuando todo
    lo que trae encaja debajo de una celda del encabezado que quedó a medias.
    """
    if len(tabla) < 2:
        return tabla[0], tabla[1:]

    cabecera, segunda = tabla[0], tabla[1]
    trozos = [_texto_celda(c) for c in segunda]
    llenas = [t for t in trozos if t]
    # Pocas celdas, cortas y sin fecha: es el resto del encabezado.
    if llenas and len(llenas) <= 2 and all(len(t) <= 20 for t in llenas) \
            and not any(fechas.tiene_pinta_de_fecha(t) for t in llenas):
        unida = list(cabecera)
        for i, trozo in enumerate(trozos):
            if not trozo or i >= len(unida):
                continue
            base = _texto_celda(unida[i])
            unida[i] = f"{base} {trozo}".strip()
        return unida, tabla[2:]

    return cabecera, tabla[1:]


def _grupo_de(filas: list[list]) -> str:
    """El número de grupo de una tabla de videoconferencias, si lo trae.

    Se descartan los años, que también son cuatro cifras y aparecen en la misma
    tabla («20 de agosto de 2025»).
    """
    for fila in filas:
        for celda in _compactar(fila):
            if re.fullmatch(r"\d{4}", celda) and not 1900 <= int(celda) <= 2100:
                return celda
    return ""


def _asesor_de(df: pd.DataFrame) -> str:
    """El nombre del asesor de una tabla de videoconferencias, si lo trae.

    Viene en su propia columna («ASESOR», «ASESORA», «ASESOR (A)») y sólo en la
    primera fila, porque la celda está combinada hacia abajo.
    """
    i = _indice_por_nombre(list(df.columns), "asesor", "profesor", "docente")
    if i is None:
        return ""
    for valor in df[df.columns[i]]:
        texto = _texto_celda(valor)
        if texto:
            return texto
    return ""


def _continua_la_tabla(tabla: list[list], abierto: dict, pagina: int, anio: int) -> bool:
    """¿Esta tabla sin encabezado es la continuación de la que venía?

    Pasa en la familia B: la tabla sigue en la página siguiente y ya no repite
    los títulos. Se pide que la página sea consecutiva y que la tabla traiga
    filas con fecha, para no tragarse los recuadros sueltos que `pdfplumber`
    detecta dentro de las celdas.
    """
    if pagina - abierto["paginas"][-1] > 1:
        return False
    if any(p in _firma(tabla[0]) for p in _EXCLUIDAS):
        return False
    return any(_abre_registro(_compactar(f), anio) for f in tabla)


# El nombre de la materia vive en la portada, debajo de «Datos de la
# asignatura». Ojo: más abajo hay otro «Nombre:», el del asesor, y por eso no
# vale quedarse con el primero que aparezca.
_RE_NOMBRE = re.compile(r"^\s*nombre\s*:\s*(.+)$", re.IGNORECASE)

# Palabras que en un título español van en minúscula aunque no abran.
_MINUSCULAS = {
    "de", "del", "la", "las", "el", "los", "y", "e", "en", "a", "al", "con",
    "por", "para", "o", "u", "sobre",
}


def _titular(texto: str) -> str:
    """«MATEMATICAS FINANCIERAS» → «Matematicas Financieras».

    Los planes escriben la materia en mayúsculas y así acabaría gritando en
    cada evento del calendario.
    """
    palabras = texto.lower().split()
    return " ".join(
        p if i and p in _MINUSCULAS else p[:1].upper() + p[1:]
        for i, p in enumerate(palabras)
    )


def _limpiar_materia(texto: str) -> str:
    # En algunos planes la clave va pegada en la misma línea:
    # "Nombre: MATEMATICAS FINANCIERAS Clave: 2231/1154".
    texto = re.split(r"\b(?:clave|plan|semestre|tipo)\s*:", texto, flags=re.IGNORECASE)[0]
    texto = re.sub(r"\s+", " ", texto).strip(" :-·")
    if not 3 <= len(texto) <= 80:
        return ""
    return _titular(texto) if texto == texto.upper() else texto


def _materia_de(pdf) -> str:
    """El nombre de la asignatura, sacado de la portada del plan."""
    lineas: list[str] = []
    for pagina in pdf.pages[:2]:
        lineas.extend((pagina.extract_text() or "").split("\n"))

    inicio = next(
        (i for i, l in enumerate(lineas) if "datos de la asignatura" in fechas.normalizar(l)),
        None,
    )
    ventana = lineas[inicio:inicio + 8] if inicio is not None else lineas[:12]
    for linea in ventana:
        if "datos del asesor" in fechas.normalizar(linea):
            break
        encontrado = _RE_NOMBRE.match(linea)
        if encontrado:
            return _limpiar_materia(encontrado.group(1))
    return ""


def _paginas_con_texto(pdf) -> int:
    return sum(1 for p in pdf.pages if len(p.extract_text() or "") >= _MINIMO_CARACTERES_POR_PAGINA)


def extraer(datos: bytes, anio_defecto: int = 2026) -> list[Candidata]:
    """Bytes de un PDF → lista de tablas candidatas, la mejor primero."""
    if not DISPONIBLE:
        raise ErrorDePDF(
            "Falta la librería para leer PDF. Instálala con: pip install pdfplumber"
        )

    import io

    try:
        pdf = pdfplumber.open(io.BytesIO(datos))
    except Exception as e:
        raise ErrorDePDF(
            "No pude abrir el PDF. Verifica que no esté protegido con contraseña "
            f"ni dañado.\n\nDetalle: {type(e).__name__}: {e}"
        ) from e

    with pdf:
        if _paginas_con_texto(pdf) == 0:
            raise ErrorDePDF(
                "Este PDF es una imagen escaneada: no tiene texto que se pueda "
                "leer, sólo la foto de la página. Copia la tabla a Excel o a "
                "Google Sheets y sube ese archivo."
            )

        materia = _materia_de(pdf)

        # Un grupo abierto por tipo: la tabla sigue en la página siguiente,
        # repita el encabezado (familia A) o no lo repita (familia B).
        abiertos: dict[str, dict] = {}
        cerrados: list[dict] = []

        for pagina in pdf.pages:
            for tabla in pagina.extract_tables():
                if not tabla:
                    continue
                encabezado, cuerpo = _unir_encabezado(tabla)
                tipo = _tipo_de_encabezado(encabezado)

                if tipo is not None:
                    abierto = abiertos.get(tipo)
                    firma = _firma(encabezado)
                    if abierto is not None and abierto["firma"] == firma:
                        abierto["filas"].extend(cuerpo)          # familia A
                        abierto["paginas"].append(pagina.page_number)
                        continue
                    if abierto is not None:
                        cerrados.append(abierto)
                    abiertos[tipo] = {
                        "tipo": tipo, "firma": firma,
                        "columnas": _nombres_columna(encabezado),
                        "filas": list(cuerpo), "paginas": [pagina.page_number],
                    }
                    continue

                # Sin encabezado propio: ¿es la continuación de una tabla que
                # venía de la página anterior? (familia B).
                for abierto in abiertos.values():
                    if _continua_la_tabla(tabla, abierto, pagina.page_number, anio_defecto):
                        abierto["filas"].extend(tabla)
                        abierto["paginas"].append(pagina.page_number)
                        break

        cerrados.extend(abiertos.values())

    candidatas: list[Candidata] = []
    for bruto in cerrados:
        df = _armar(bruto["columnas"], bruto["filas"], anio_defecto)
        if df.empty:
            continue
        es_video = bruto["tipo"] == TIPO_VIDEOCONFERENCIAS
        candidata = Candidata(
            df=df,
            tipo=bruto["tipo"],
            paginas=sorted(set(bruto["paginas"])),
            grupo=_grupo_de(bruto["filas"]) if es_video else "",
            asesor=_asesor_de(df) if es_video else "",
            materia=materia,
        )
        if candidata.confianza < 1.0:
            faltan = len(df) - candidata.filas_con_fecha
            candidata.avisos.append(
                f"{faltan} de {len(df)} filas se quedaron sin una fecha que yo entienda."
            )
        candidatas.append(candidata)

    # Primero las actividades, y dentro de cada tipo las más fiables.
    candidatas.sort(key=lambda c: (c.tipo != TIPO_ACTIVIDADES, -c.confianza, -len(c.df)))
    return candidatas
