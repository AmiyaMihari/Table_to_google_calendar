"""Exportar Plan de Trabajo a Google Calendar — convierte planes de trabajo en eventos de calendario."""

__version__ = "2.0.0"

from . import deteccion, exportar, fechas, tablas  # noqa: F401
from .modelo import Evento, construir_eventos  # noqa: F401
