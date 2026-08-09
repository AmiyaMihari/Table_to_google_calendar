"""El evento de calendario y cómo se arma a partir de una fila de la tabla."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pandas as pd

from . import fechas

MODO_DIA = "dia"        # todo el día (entregas)
MODO_HORA = "hora"      # con horario (asesorías, videoconferencias)
MODO_AUTO = "auto"      # con horario si la fila trae hora, si no todo el día

PLANTILLAS = {
    MODO_DIA: "{materia} · {unidad} · {titulo}",
    MODO_HORA: "{materia} · {titulo}",
    MODO_AUTO: "{materia} · {unidad} · {titulo}",
}
PLANTILLA_POR_DEFECTO = PLANTILLAS[MODO_DIA]

# Palabras que ya identifican la unidad por sí solas: si el valor de la columna
# es "Unidad 1" se deja tal cual; si es sólo "1" se muestra como "U1".
_PALABRAS_UNIDAD = (
    "unidad", "modulo", "módulo", "tema", "semana", "bloque", "sesion", "sesión",
    "eje", "parcial", "u",
)


@dataclass
class Evento:
    titulo: str = ""
    descripcion: str = ""
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    hora_inicio: time | None = None
    hora_fin: time | None = None
    lugar: str = ""
    origen: str = ""
    fila: int = 0
    problema: str = ""

    @property
    def todo_el_dia(self) -> bool:
        return self.hora_inicio is None

    @property
    def valido(self) -> bool:
        return bool(self.titulo) and self.fecha_inicio is not None

    @property
    def fin_efectivo(self) -> date:
        return self.fecha_fin or self.fecha_inicio

    def uid(self) -> str:
        """Identificador estable: reimportar el mismo archivo no duplica eventos."""
        semilla = f"{self.titulo}|{self.fecha_inicio}|{self.hora_inicio}"
        return hashlib.sha1(semilla.encode("utf-8")).hexdigest()[:24]

    def inicio_dt(self) -> datetime:
        return datetime.combine(self.fecha_inicio, self.hora_inicio or time(0, 0))

    def fin_dt(self, duracion_horas: float = 2.0) -> datetime:
        if self.hora_inicio is None:
            return datetime.combine(self.fin_efectivo, time(0, 0))
        fin_hora = self.hora_fin
        if fin_hora is None:
            return self.inicio_dt() + timedelta(hours=duracion_horas)
        base = datetime.combine(self.fin_efectivo, fin_hora)
        if base <= self.inicio_dt():
            base += timedelta(days=1)
        return base

    def resumen_fecha(self) -> str:
        if self.fecha_inicio is None:
            return "—"
        txt = self.fecha_inicio.strftime("%d/%m/%Y")
        if self.fecha_fin and self.fecha_fin != self.fecha_inicio:
            txt += f" → {self.fecha_fin.strftime('%d/%m/%Y')}"
        if self.hora_inicio:
            txt += f"  {self.hora_inicio.strftime('%H:%M')}"
            if self.hora_fin:
                txt += f"–{self.hora_fin.strftime('%H:%M')}"
        return txt


# Word guarda las viñetas de las fuentes Symbol y Wingdings como caracteres de
# uso privado (U+E000–U+F8FF): dentro del PDF se ven como un punto, pero fuera
# no significan nada y el calendario los pinta como cuadritos. Se cambian por
# una viñeta de verdad. Pasa igual si alguien copia la tabla del PDF a Excel,
# así que la limpieza vive aquí y no en `pdf.py`.
_RE_USO_PRIVADO = re.compile(r"[-]+")


def _texto(valor) -> str:
    if fechas.es_vacio(valor):
        return ""
    if isinstance(valor, float) and valor == int(valor):
        return str(int(valor))
    return re.sub(r"\s+", " ", _RE_USO_PRIVADO.sub("•", str(valor))).strip()


def formatear_unidad(valor) -> str:
    """Normaliza el valor de la columna «Unidad» para que se lea bien en el título.

    "Unidad 1" → "Unidad 1" (ya se explica solo);  1 → "U1";  "Tema 3" → "Tema 3".
    """
    texto = _texto(valor)
    if not texto:
        return ""
    primera = fechas.normalizar(texto).split()[0].rstrip(".:")
    if primera in _PALABRAS_UNIDAD:
        return texto
    if re.fullmatch(r"\d{1,2}", texto):
        return f"U{texto}"
    return texto


def render_plantilla(plantilla: str, valores: dict[str, str]) -> str:
    """Aplica la plantilla saltándose los separadores de los campos vacíos.

    Con "{materia} · U{unidad} · {titulo}" y sin unidad, devuelve
    "Ética · Actividad 1" en lugar de "Ética · U · Actividad 1".
    """
    piezas = re.split(r"(\{[a-zA-Z_]+\})", plantilla)
    resultado, separador = "", ""
    for pieza in piezas:
        if pieza.startswith("{") and pieza.endswith("}"):
            valor = str(valores.get(pieza[1:-1], "")).strip()
            if valor:
                # El texto pegado al campo ("U" en "U{unidad}") es parte del valor,
                # no un separador: se conserva aunque el campo abra el título.
                prefijo = re.search(r"\S*$", separador).group(0)
                union = separador[: len(separador) - len(prefijo)]
                resultado = (resultado + union if resultado else "") + prefijo + valor
                separador = ""
        else:
            separador = pieza
    return re.sub(r"\s+", " ", resultado).strip(" ·-—|:,")


def construir_eventos(
    df: pd.DataFrame,
    mapeo: dict[str, str | None],
    *,
    materia: str = "",
    plantilla: str | None = None,
    dayfirst: bool = True,
    anio_defecto: int | None = None,
    modo: str = MODO_AUTO,
    duracion_horas: float = 2.0,
    rellenar_unidad: bool = True,
    origen: str = "",
) -> list[Evento]:
    """Convierte la tabla mapeada en una lista de eventos (válidos y con problema)."""
    datos = df.copy()
    if plantilla is None:
        plantilla = PLANTILLAS.get(modo, PLANTILLA_POR_DEFECTO)

    col_unidad = mapeo.get("unidad")
    if rellenar_unidad and col_unidad and col_unidad in datos.columns:
        # Las celdas combinadas de Excel dejan huecos debajo del primer valor.
        datos[col_unidad] = datos[col_unidad].where(
            ~datos[col_unidad].map(fechas.es_vacio)
        ).ffill()

    def celda(fila, campo):
        col = mapeo.get(campo)
        if not col or col not in datos.columns:
            return None
        return fila[col]

    eventos: list[Evento] = []
    for pos, (_, fila) in enumerate(datos.iterrows(), start=1):
        unidad = formatear_unidad(celda(fila, "unidad"))
        titulo_base = _texto(celda(fila, "titulo"))
        descripcion = _texto(celda(fila, "descripcion"))
        lugar = _texto(celda(fila, "lugar"))
        crudo_fecha = celda(fila, "fecha")
        crudo_hora = celda(fila, "hora")

        if not titulo_base and not descripcion and fechas.es_vacio(crudo_fecha):
            continue  # fila vacía o de relleno

        if not titulo_base:
            titulo_base = descripcion[:80] or "Actividad"

        fecha_inicio = fechas.parse_fecha(crudo_fecha, dayfirst, anio_defecto)
        fecha_fin = fechas.parse_fecha_fin(crudo_fecha, dayfirst, anio_defecto)
        col_fin = mapeo.get("fecha_fin")
        if col_fin and col_fin in datos.columns:
            fecha_fin = fechas.parse_fecha(fila[col_fin], dayfirst, anio_defecto) or fecha_fin
        if fecha_fin and fecha_inicio and fecha_fin < fecha_inicio:
            fecha_fin = None

        hora_inicio = hora_fin = None
        if modo in (MODO_AUTO, MODO_HORA):
            hora_inicio, hora_fin = fechas.parse_hora(crudo_hora)
            if hora_inicio is None and not fechas.es_vacio(crudo_fecha):
                # A veces la hora viene pegada a la fecha: "21/08/2025 16:00".
                hora_inicio, hora_fin = fechas.hora_de_fecha(crudo_fecha)
            # Columna aparte para la hora de fin ("Start Time" / "End Time").
            col_hfin = mapeo.get("hora_fin")
            if col_hfin and col_hfin in datos.columns:
                fin_propio, _ = fechas.parse_hora(fila[col_hfin])
                hora_fin = fin_propio or hora_fin
        if modo == MODO_DIA:
            hora_inicio = hora_fin = None
        if hora_inicio is not None and hora_fin is None:
            fin = (datetime.combine(date.today(), hora_inicio)
                   + timedelta(hours=duracion_horas)).time()
            hora_fin = fin if fin > hora_inicio else None

        problema = ""
        if fecha_inicio is None:
            crudo = _texto(crudo_fecha)
            problema = (
                f"No entendí la fecha «{crudo}»" if crudo else "La fila no trae fecha"
            )
        elif modo == MODO_HORA and hora_inicio is None:
            problema = "Sin horario: quedará como evento de todo el día"

        eventos.append(
            Evento(
                titulo=render_plantilla(
                    plantilla,
                    {"materia": materia, "unidad": unidad, "titulo": titulo_base},
                ) or titulo_base,
                descripcion=descripcion,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                hora_inicio=hora_inicio,
                hora_fin=hora_fin,
                lugar=lugar,
                origen=origen,
                fila=pos,
                problema=problema,
            )
        )

    return eventos
