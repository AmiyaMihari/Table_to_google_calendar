"""Exportación a .ics (recomendado) y al CSV que importa Google Calendar.

El .ics es mejor que el CSV por tres razones: no hay ambigüedad de formato de
fecha, soporta horarios y recordatorios, y lleva un UID estable — si el archivo
se vuelve a importar, Google actualiza los eventos en lugar de duplicarlos.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .modelo import Evento

PRODID = "-//Exportar Plan de Trabajo a Google Calendar//SUAyED//ES"

CABECERA_CSV = [
    "Subject", "Start Date", "Start Time", "End Date", "End Time",
    "All Day Event", "Description", "Location", "Private",
]

FORMATOS_CSV = {
    "MM/DD/YYYY (recomendado para Google)": "%m/%d/%Y",
    "DD/MM/YYYY": "%d/%m/%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
}


# --------------------------------------------------------------------------- #
# ICS
# --------------------------------------------------------------------------- #

def _escapar(texto: str) -> str:
    return (
        str(texto)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _plegar(linea: str) -> str:
    """RFC 5545: máximo 75 octetos por línea; las siguientes empiezan con espacio."""
    if len(linea.encode("utf-8")) <= 74:
        return linea
    partes, actual = [], b""
    for caracter in linea:
        bytes_car = caracter.encode("utf-8")
        limite = 74 if not partes else 73
        if len(actual) + len(bytes_car) > limite:
            partes.append(actual)
            actual = b""
        actual += bytes_car
    partes.append(actual)
    return "\r\n ".join(p.decode("utf-8") for p in partes)


def _a_utc(momento: datetime, zona: str) -> str:
    try:
        tz = ZoneInfo(zona)
    except Exception:
        tz = timezone.utc
    return momento.replace(tzinfo=tz).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def a_ics(
    eventos: list[Evento],
    zona: str = "America/Mexico_City",
    duracion_horas: float = 2.0,
    recordatorio_min: int | None = None,
    nombre_calendario: str = "Actividades",
) -> bytes:
    sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lineas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escapar(nombre_calendario)}",
        f"X-WR-TIMEZONE:{zona}",
    ]

    for ev in eventos:
        if not ev.valido:
            continue
        lineas.append("BEGIN:VEVENT")
        lineas.append(f"UID:{ev.uid()}@tabla-a-google-calendar")
        lineas.append(f"DTSTAMP:{sello}")

        if ev.todo_el_dia:
            # En un evento de día completo, DTEND es exclusivo (día siguiente).
            fin = ev.fin_efectivo + timedelta(days=1)
            lineas.append(f"DTSTART;VALUE=DATE:{ev.fecha_inicio.strftime('%Y%m%d')}")
            lineas.append(f"DTEND;VALUE=DATE:{fin.strftime('%Y%m%d')}")
        else:
            lineas.append(f"DTSTART:{_a_utc(ev.inicio_dt(), zona)}")
            lineas.append(f"DTEND:{_a_utc(ev.fin_dt(duracion_horas), zona)}")

        lineas.append(f"SUMMARY:{_escapar(ev.titulo)}")
        if ev.descripcion:
            lineas.append(f"DESCRIPTION:{_escapar(ev.descripcion)}")
        if ev.lugar:
            lineas.append(f"LOCATION:{_escapar(ev.lugar)}")
        lineas.append("TRANSP:TRANSPARENT" if ev.todo_el_dia else "TRANSP:OPAQUE")

        if recordatorio_min:
            lineas += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escapar(ev.titulo)}",
                f"TRIGGER:-PT{int(recordatorio_min)}M",
                "END:VALARM",
            ]
        lineas.append("END:VEVENT")

    lineas.append("END:VCALENDAR")
    return ("\r\n".join(_plegar(l) for l in lineas) + "\r\n").encode("utf-8")


# --------------------------------------------------------------------------- #
# CSV de Google Calendar
# --------------------------------------------------------------------------- #

def a_csv_google(eventos: list[Evento], formato: str = "%m/%d/%Y",
                 duracion_horas: float = 2.0) -> bytes:
    import csv
    import io

    buffer = io.StringIO(newline="")
    escritor = csv.DictWriter(buffer, fieldnames=CABECERA_CSV)
    escritor.writeheader()

    for ev in eventos:
        if not ev.valido:
            continue
        if ev.todo_el_dia:
            escritor.writerow({
                "Subject": ev.titulo,
                "Start Date": ev.fecha_inicio.strftime(formato),
                "Start Time": "",
                "End Date": ev.fin_efectivo.strftime(formato),
                "End Time": "",
                "All Day Event": "True",
                "Description": ev.descripcion,
                "Location": ev.lugar,
                "Private": "False",
            })
        else:
            inicio, fin = ev.inicio_dt(), ev.fin_dt(duracion_horas)
            escritor.writerow({
                "Subject": ev.titulo,
                "Start Date": inicio.strftime(formato),
                "Start Time": inicio.strftime("%I:%M %p"),
                "End Date": fin.strftime(formato),
                "End Time": fin.strftime("%I:%M %p"),
                "All Day Event": "False",
                "Description": ev.descripcion,
                "Location": ev.lugar,
                "Private": "False",
            })

    return buffer.getvalue().encode("utf-8-sig")


# --------------------------------------------------------------------------- #
# Enlaces "Añadir a Google Calendar"
# --------------------------------------------------------------------------- #

def enlace_google(ev: Evento, zona: str = "America/Mexico_City",
                  duracion_horas: float = 2.0) -> str:
    """Liga que abre Google Calendar con el evento ya llenado, listo para guardar.

    No requiere permisos ni configuración de ningún tipo, y funciona en celular
    (a diferencia de importar un .ics, que Google sólo permite desde computadora).
    """
    from urllib.parse import quote

    if ev.todo_el_dia:
        fin = ev.fin_efectivo + timedelta(days=1)
        rango = f"{ev.fecha_inicio.strftime('%Y%m%d')}/{fin.strftime('%Y%m%d')}"
    else:
        rango = f"{_a_utc(ev.inicio_dt(), zona)}/{_a_utc(ev.fin_dt(duracion_horas), zona)}"

    partes = [("action", "TEMPLATE"), ("text", ev.titulo), ("dates", rango)]
    if ev.descripcion:
        partes.append(("details", ev.descripcion))
    if ev.lugar:
        partes.append(("location", ev.lugar))

    # En `dates` la barra separa inicio y fin: codificarla rompe la liga.
    consulta = "&".join(
        f"{k}={quote(str(v), safe='/' if k == 'dates' else '')}" for k, v in partes
    )
    return f"https://calendar.google.com/calendar/render?{consulta}"


def nombre_archivo(materia: str, extension: str) -> str:
    import re
    base = re.sub(r"[^\w\s-]", "", materia or "actividades").strip() or "actividades"
    return re.sub(r"[\s]+", "_", base).lower() + f"_calendario.{extension}"
