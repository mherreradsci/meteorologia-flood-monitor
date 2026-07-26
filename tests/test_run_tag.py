"""Trazabilidad del nombre de salida y conversión a dB. Sin red.

Con --end-date-utc se acumulan corridas de distintas fechas en el mismo
`output/`: que el tag lleve el timestamp de la escena es lo que permite
saber, mirando solo el nombre, qué imagen produjo cada archivo.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from flood_monitor import DB_NODATA, build_run_tag, slugify, to_db
from helpers import FakeItem, utc

BBOX = (-71.5449, -30.3021, -71.4409, -30.2123)
ESCENA = FakeItem(utc(2026, 7, 16, 10, 2, 47))


def _args(**kw):
    base = {"place": None, "aoi": None,
            "region": "Región de Coquimbo, Chile"}
    return argparse.Namespace(**{**base, **kw})


def test_el_tag_lleva_el_timestamp_de_la_escena_no_el_de_hoy():
    """Una corrida histórica queda auto-etiquetada con su fecha de imagen."""
    tag = build_run_tag(_args(place="Tongoy"), BBOX, ESCENA)

    assert tag.startswith("Región_de_Coquimbo,_Chile_Tongoy_")
    assert "20260716T100247Z" in tag


def test_dos_corridas_de_la_misma_escena_no_se_pisan():
    """Reprocesar la misma fecha debe conservar la salida anterior."""
    a = build_run_tag(_args(place="Tongoy"), BBOX, ESCENA)
    b = build_run_tag(_args(place="Tongoy"), BBOX, ESCENA)

    assert a != b
    assert "20260716T100247Z" in a and "20260716T100247Z" in b


def test_con_bbox_el_aoi_se_identifica_por_coordenadas():
    """Es el único modo sin ningún nombre asociado."""
    tag = build_run_tag(_args(), BBOX, ESCENA)

    assert tag.startswith("bbox_-71.5449_-30.3021_-71.4409_-30.2123_")


def test_con_aoi_el_nombre_sale_del_geojson():
    """El archivo ya nombra la zona; su envolvente no la distingue (dos
    polígonos distintos pueden compartir bbox) y además es ilegible."""
    ruta = Path("../aoi/Chile-Region_de_Coquimbo-La_huiguera-Chungungo.geojson")

    tag = build_run_tag(_args(aoi=ruta), BBOX, ESCENA)

    # Sin directorio ni extensión, y sin rastro de las coordenadas.
    assert tag.startswith(
        "aoi_Chile-Region_de_Coquimbo-La_huiguera-Chungungo_")
    assert "20260716T100247Z" in tag
    assert ".geojson" not in tag
    assert "-71.5449" not in tag


def test_el_nombre_del_aoi_se_normaliza_como_el_de_place():
    """Un GeoJSON con espacios en el nombre no debe romper el archivo de
    salida: pasa por el mismo slugify que --place."""
    tag = build_run_tag(_args(aoi=Path("/data/Mi  Zona Norte.geojson")),
                        BBOX, ESCENA)

    assert tag.startswith("aoi_Mi_Zona_Norte_")


def test_slugify_conserva_tildes_y_enie():
    # Los nombres de región chilenos los llevan; perderlos haría ilegible
    # el nombre del archivo.
    assert slugify("Región de Coquimbo") == "Región_de_Coquimbo"
    # Los espacios seguidos colapsan en un solo '_' (\s+), y los de los
    # extremos se recortan: nombres de archivo prolijos aunque el --place
    # venga con espacios de más.
    assert slugify(" La  Higuera ") == "La_Higuera"
    assert slugify("a/b") == "a-b"          # '/' rompería la ruta


def test_to_db_convierte_potencia_lineal():
    out = to_db(np.array([1.0, 0.1, 0.01], dtype="float32"))
    np.testing.assert_allclose(out, [0.0, -10.0, -20.0], atol=1e-5)


def test_to_db_marca_ceros_y_negativos_como_nodata():
    """log10(<=0) no existe: esos píxeles quedan fuera del análisis."""
    out = to_db(np.array([0.0, -0.5], dtype="float32"))

    assert (out == DB_NODATA).all()
