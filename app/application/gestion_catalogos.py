"""Valores temporales y enumeraciones para los filtros de gestión."""

from enum import StrEnum


class AlertaGestion(StrEnum):
    TERMINO = "TERMINO"
    VENCIDA = "VENCIDA"
    PROXIMA = "PROXIMA"


# Paleta de colores del indicador visual de Estado de Alerta (HU5 - Control de
# Inspecciones): rojo = vencida, amarillo = próxima a vencer, verde = en término.
COLOR_ALERTA_GESTION: dict[AlertaGestion, str] = {
    AlertaGestion.VENCIDA: "#dc3545",
    AlertaGestion.PROXIMA: "#ffc107",
    AlertaGestion.TERMINO: "#28a745",
}
