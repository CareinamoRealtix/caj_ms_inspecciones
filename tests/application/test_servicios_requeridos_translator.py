import pytest

from app.application.servicios_requeridos_translator import (
    ServicioSinTraduccionError,
    ServiciosRequeridosTranslator,
)


@pytest.mark.parametrize(
    ("tipo_servicio", "codigo", "tipo_esperado", "subcategoria_esperada"),
    [
        ("LIMPIEZA", "INTERNA", "LIMPIEZA", "Limpieza"),
        ("LIMPIEZA", "EXTERNA", "LIMPIEZA", "Limpieza"),
        ("LIMPIEZA", "RETIRO_ENSERES", "LIMPIEZA", "Retiro de Enseres"),
        ("LIMPIEZA", "LIMPIEZA_PISCINA", "LIMPIEZA", "Limpieza de Piscina"),
        ("CERRAJERIA_MATERIAL", "HIERRO", "CERRAJERIA", "Hierro"),
        ("CERRAJERIA_MATERIAL", "VIDRIO_ALUMINIO", "CERRAJERIA", "Vidrio/Aluminio"),
        ("REPARACION", "OTRAS_REPARACIONES", "REPARACIONES", "Otras reparaciones"),
        (
            "INSPECCION_TECNICA",
            "AIRE_ACONDICIONADO",
            "INSPECCIONES_ESPECIALES",
            "Inspección Aire Acondicionado",
        ),
    ],
)
def test_traducir_conocidos(
    tipo_servicio: str, codigo: str, tipo_esperado: str, subcategoria_esperada: str
) -> None:
    translator = ServiciosRequeridosTranslator()

    tipo_externo, subcategoria = translator.traducir(tipo_servicio, codigo)

    assert tipo_externo == tipo_esperado
    assert subcategoria == subcategoria_esperada


def test_inspeccion_tecnica_se_traduce_a_inspecciones_especiales() -> None:
    """ms-requerimientos no tiene un grupo INSPECCION_TECNICA: la etiqueta que ellos
    usan para eso es INSPECCIONES_ESPECIALES."""
    translator = ServiciosRequeridosTranslator()

    tipo_externo, _ = translator.traducir("INSPECCION_TECNICA", "ELECTRICA")

    assert tipo_externo == "INSPECCIONES_ESPECIALES"


def test_traducir_codigo_desconocido_lanza_error() -> None:
    translator = ServiciosRequeridosTranslator()

    with pytest.raises(ServicioSinTraduccionError):
        translator.traducir("LIMPIEZA", "CODIGO_NUEVO_SIN_MAPEAR")


def test_traducir_tipo_servicio_desconocido_lanza_error() -> None:
    translator = ServiciosRequeridosTranslator()

    with pytest.raises(ServicioSinTraduccionError):
        translator.traducir("GRUPO_INEXISTENTE", "CODIGO")
