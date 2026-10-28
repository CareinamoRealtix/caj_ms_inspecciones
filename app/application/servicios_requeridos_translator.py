"""Traduce el catálogo interno de servicios requeridos (inspecciones.servicio) al
tipo_servicio/subcategoria que espera el webhook de ms-requerimientos (órdenes de
servicio). Los dos catálogos evolucionan por separado y sus nombres no siempre
coinciden (ej. nuestro INSPECCION_TECNICA es su INSPECCIONES_ESPECIALES), así que la
traducción vive en un solo lugar en vez de intentar mantener los nombres sincronizados.
"""
from __future__ import annotations

from typing import ClassVar


class ServicioSinTraduccionError(Exception):
    """Un tipo_servicio/codigo interno no tiene traducción configurada hacia
    ms-requerimientos. Se lanza en vez de enviar datos adivinados: un catálogo nuevo o
    un código nuevo debe traducirse explícitamente antes de reportarse."""

    def __init__(self, tipo_servicio: str, codigo: str) -> None:
        super().__init__(
            f"No hay traducción configurada hacia ms-requerimientos para "
            f"'{tipo_servicio}.{codigo}'"
        )
        self.tipo_servicio = tipo_servicio
        self.codigo = codigo


class ServiciosRequeridosTranslator:
    """Traduce (tipo_servicio, codigo) internos a (tipo_servicio, subcategoria) externos.

    El mapeo de subcategoria se intuyó a partir de los catálogos que el equipo de
    ms-requerimientos compartió por chat (capturas de pantalla, no un contrato
    formal) — si su catálogo cambia, esta tabla debe actualizarse a mano.
    """

    _TIPO_SERVICIO_EXTERNO: ClassVar[dict[str, str]] = {
        "LIMPIEZA": "LIMPIEZA",
        "CERRAJERIA_MATERIAL": "CERRAJERIA",
        "REPARACION": "REPARACIONES",
        "INSPECCION_TECNICA": "INSPECCIONES_ESPECIALES",
    }

    _SUBCATEGORIA_EXTERNA: ClassVar[dict[tuple[str, str], str]] = {
        # LIMPIEZA: su catálogo no distingue interna/externa, ambas caen en "Limpieza".
        ("LIMPIEZA", "INTERNA"): "Limpieza",
        ("LIMPIEZA", "EXTERNA"): "Limpieza",
        ("LIMPIEZA", "RETIRO_ENSERES"): "Retiro de Enseres",
        ("LIMPIEZA", "LIMPIEZA_PISCINA"): "Limpieza de Piscina",
        ("CERRAJERIA_MATERIAL", "HIERRO"): "Hierro",
        ("CERRAJERIA_MATERIAL", "MULTILOCK"): "Multilock",
        ("CERRAJERIA_MATERIAL", "MADERA"): "Madera",
        ("CERRAJERIA_MATERIAL", "VIDRIO_ALUMINIO"): "Vidrio/Aluminio",
        ("REPARACION", "FILTRACIONES"): "Filtraciones/Impermeabilización",
        ("REPARACION", "TRABAJOS_ELECTRICOS"): "Trabajos eléctricos",
        ("REPARACION", "TRABAJOS_PLOMERIA"): "Trabajos de Plomería",
        ("REPARACION", "REPARACION_PUERTAS"): "Reemplazo o Reparación de Puertas",
        ("REPARACION", "REPARACION_VENTANAS"): "Reemplazo o Reparación de Ventanas",
        ("REPARACION", "TRABAJOS_CERCADO"): "Trabajos de Cercado",
        ("REPARACION", "REPARACION_TECHOS"): "Reparación de Techos",
        ("REPARACION", "REPARACION_PAREDES"): "Reparación de Paredes",
        ("REPARACION", "OTRAS_REPARACIONES"): "Otras reparaciones",
        # INSPECCION_TECNICA: ellos la agrupan bajo INSPECCIONES_ESPECIALES. Su catálogo
        # también tiene una cuarta opción, "Inspección Técnica de Ingeniería", que no
        # existe en el nuestro — nunca la produciremos, y no hace falta mapearla.
        ("INSPECCION_TECNICA", "ELECTRICA"): "Inspección Eléctrica",
        ("INSPECCION_TECNICA", "PLOMERIA"): "Inspección de Plomería",
        ("INSPECCION_TECNICA", "AIRE_ACONDICIONADO"): "Inspección Aire Acondicionado",
    }

    def traducir(self, tipo_servicio: str, codigo: str) -> tuple[str, str]:
        """Devuelve (tipo_servicio_externo, subcategoria_externa) o lanza
        ServicioSinTraduccionError si el par no está mapeado."""
        tipo_externo = self._TIPO_SERVICIO_EXTERNO.get(tipo_servicio)
        subcategoria_externa = self._SUBCATEGORIA_EXTERNA.get((tipo_servicio, codigo))
        if tipo_externo is None or subcategoria_externa is None:
            raise ServicioSinTraduccionError(tipo_servicio, codigo)
        return tipo_externo, subcategoria_externa
