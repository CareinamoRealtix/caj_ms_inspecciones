from datetime import date

import pytest

from app.application.levantamiento_validacion import (
    CodigoCatalogoInvalidoError,
    agrupar_opciones,
    validar_codigos,
)
from app.presentation.api.schemas.inspecciones import LevantamientoRequest, SeleccionOpcion

_ID_OPERACION = "00000000-0000-4000-8000-000000000201"


def _opciones() -> dict[str, dict[str, dict[str, object]]]:
    rows = [
        {
            "tipo_catalogo": "CONDICION_BIEN",
            "codigo": "BUENA",
            "nombre": "Buena",
            "requiere_cantidad": False,
            "permite_descripcion": False,
            "orden": 1,
        },
        {
            "tipo_catalogo": "ESTADO_OCUPACION",
            "codigo": "DESOCUPADO",
            "nombre": "Desocupado",
            "requiere_cantidad": False,
            "permite_descripcion": False,
            "orden": 1,
        },
        {
            "tipo_catalogo": "UBICACION_PUERTA",
            "codigo": "ENTRADA_PRINCIPAL",
            "nombre": "Entrada Principal",
            "requiere_cantidad": False,
            "permite_descripcion": False,
            "orden": 1,
        },
        {
            "tipo_catalogo": "PUERTA_MATERIAL",
            "codigo": "HIERRO",
            "nombre": "Hierro",
            "requiere_cantidad": True,
            "permite_descripcion": False,
            "orden": 1,
        },
        {
            "tipo_catalogo": "VENTANA_TIPO",
            "codigo": "OTROS",
            "nombre": "Otros",
            "requiere_cantidad": True,
            "permite_descripcion": True,
            "orden": 6,
        },
        {
            "tipo_catalogo": "VENTANA_TIPO",
            "codigo": "FRANCESA",
            "nombre": "Francesa",
            "requiere_cantidad": True,
            "permite_descripcion": False,
            "orden": 5,
        },
        {
            "tipo_catalogo": "LIMPIEZA",
            "codigo": "INTERNA",
            "nombre": "Interna",
            "requiere_cantidad": False,
            "permite_descripcion": False,
            "orden": 1,
        },
        {
            "tipo_catalogo": "REPARACION",
            "codigo": "OTRAS_REPARACIONES",
            "nombre": "Otras reparaciones",
            "requiere_cantidad": False,
            "permite_descripcion": True,
            "orden": 9,
        },
    ]
    return agrupar_opciones(rows)  # type: ignore[arg-type]


def _body(**overrides: object) -> LevantamientoRequest:
    data: dict[str, object] = {
        "id_operacion": _ID_OPERACION,
        "condicion_bien": "BUENA",
        "estado_ocupacion": "DESOCUPADO",
        "fecha_levantamiento": date(2026, 9, 8),
    }
    data.update(overrides)
    return LevantamientoRequest(**data)  # type: ignore[arg-type]


def test_validar_codigos_acepta_seleccion_completa_y_valida() -> None:
    body = _body(
        puertas={"ENTRADA_PRINCIPAL": [{"codigo": "HIERRO", "cantidad": 2}]},
        tipos_ventanas=[{"codigo": "FRANCESA", "cantidad": 1}],
    )

    validar_codigos(body, _opciones())


def test_validar_codigos_rechaza_codigo_inexistente() -> None:
    body = _body(condicion_bien="INEXISTENTE")

    with pytest.raises(CodigoCatalogoInvalidoError) as excinfo:
        validar_codigos(body, _opciones())

    assert excinfo.value.tipo_catalogo == "CONDICION_BIEN"
    assert excinfo.value.codigo == "INEXISTENTE"


def test_validar_codigos_rechaza_codigo_de_otro_grupo() -> None:
    body = _body(tipos_ventanas=[{"codigo": "HIERRO", "cantidad": 1}])

    with pytest.raises(CodigoCatalogoInvalidoError) as excinfo:
        validar_codigos(body, _opciones())

    assert excinfo.value.tipo_catalogo == "VENTANA_TIPO"
    assert excinfo.value.codigo == "HIERRO"


def test_validar_codigos_rechaza_cantidad_faltante_cuando_se_requiere() -> None:
    body = _body(tipos_ventanas=[{"codigo": "FRANCESA"}])

    with pytest.raises(CodigoCatalogoInvalidoError, match="cantidad"):
        validar_codigos(body, _opciones())


def test_validar_codigos_rechaza_descripcion_faltante_en_opcion_otros() -> None:
    body = _body(tipos_ventanas=[{"codigo": "OTROS", "cantidad": 1}])

    with pytest.raises(CodigoCatalogoInvalidoError, match="descripción"):
        validar_codigos(body, _opciones())


def test_validar_codigos_rechaza_descripcion_cuando_no_esta_permitida() -> None:
    body = _body(
        tipos_ventanas=[{"codigo": "FRANCESA", "cantidad": 1, "descripcion": "no debería ir"}]
    )

    with pytest.raises(CodigoCatalogoInvalidoError, match="no permite descripción"):
        validar_codigos(body, _opciones())


def test_validar_codigos_rechaza_ubicacion_de_puerta_desconocida() -> None:
    body = _body(puertas={"GARAJE": [{"codigo": "HIERRO", "cantidad": 1}]})

    with pytest.raises(CodigoCatalogoInvalidoError) as excinfo:
        validar_codigos(body, _opciones())

    assert excinfo.value.tipo_catalogo == "UBICACION_PUERTA"
    assert excinfo.value.codigo == "GARAJE"


def test_seleccion_opcion_rechaza_cantidad_no_positiva() -> None:
    with pytest.raises(ValueError, match="greater than 0"):
        SeleccionOpcion(codigo="HIERRO", cantidad=0)


def test_levantamiento_request_rechaza_codigos_duplicados_en_el_mismo_grupo() -> None:
    with pytest.raises(ValueError, match="duplicad"):
        _body(
            tipos_ventanas=[
                {"codigo": "FRANCESA", "cantidad": 1},
                {"codigo": "FRANCESA", "cantidad": 2},
            ]
        )


def test_validar_codigos_acepta_servicios_requeridos_agrupados() -> None:
    body = _body(
        servicios_requeridos={
            "LIMPIEZA": [{"codigo": "INTERNA"}],
            "REPARACION": [{"codigo": "OTRAS_REPARACIONES", "descripcion": "Cañería"}],
        }
    )

    validar_codigos(body, _opciones())


def test_validar_codigos_rechaza_servicio_requerido_en_grupo_equivocado() -> None:
    body = _body(servicios_requeridos={"REPARACION": [{"codigo": "INTERNA"}]})

    with pytest.raises(CodigoCatalogoInvalidoError) as excinfo:
        validar_codigos(body, _opciones())

    assert excinfo.value.tipo_catalogo == "REPARACION"
    assert excinfo.value.codigo == "INTERNA"


def test_servicios_requeridos_rechaza_grupo_desconocido() -> None:
    with pytest.raises(ValueError, match="Grupos no permitidos"):
        _body(servicios_requeridos={"INSPECCION_TECNICA": [{"codigo": "ELECTRICA"}]})


def test_servicios_requeridos_rechaza_lista_plana() -> None:
    with pytest.raises(ValueError):
        _body(servicios_requeridos=[{"codigo": "INTERNA"}])


def test_servicios_requeridos_rechaza_duplicados_dentro_del_grupo() -> None:
    with pytest.raises(ValueError, match="duplicados"):
        _body(servicios_requeridos={"LIMPIEZA": [{"codigo": "INTERNA"}, {"codigo": "INTERNA"}]})
