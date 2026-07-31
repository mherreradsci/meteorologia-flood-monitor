"""susceptibility.load_susceptibility: lectura y rasterización del raster
binario real. Marcado `raster`, sin red.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("rioxarray")

from flood_validation import susceptibility  # noqa: E402
from raster_helpers import bbox_lonlat, geotiff, grilla  # noqa: E402

pytestmark = pytest.mark.raster

LADO = 20


def test_carga_y_rasteriza_sobre_el_template(tmp_path):
    valores = np.zeros((LADO, LADO), dtype="float32")
    valores[5:10, 5:10] = 1.0
    ruta = geotiff(tmp_path, "susceptibilidad.tif", valores)
    template = grilla(np.zeros((LADO, LADO)))

    mask = susceptibility.load_susceptibility(ruta, template,
                                              bbox_lonlat(LADO, LADO))

    assert mask is not None
    assert mask[5:10, 5:10].all()
    assert not mask[0:3, 0:3].any()


def test_todo_seco_da_mascara_vacia(tmp_path):
    valores = np.zeros((LADO, LADO), dtype="float32")
    ruta = geotiff(tmp_path, "seca.tif", valores)
    template = grilla(np.zeros((LADO, LADO)))

    mask = susceptibility.load_susceptibility(ruta, template,
                                              bbox_lonlat(LADO, LADO))

    assert not mask.any()


def test_archivo_inexistente_devuelve_none(tmp_path, capsys):
    template = grilla(np.zeros((LADO, LADO)))

    mask = susceptibility.load_susceptibility(
        tmp_path / "no_existe.tif", template, bbox_lonlat(LADO, LADO))

    assert mask is None
    assert "no existe" in capsys.readouterr().out.lower()


def test_archivo_corrupto_falla_suave(tmp_path, capsys):
    roto = tmp_path / "roto.tif"
    roto.write_bytes(b"esto no es un GeoTIFF")
    template = grilla(np.zeros((LADO, LADO)))

    mask = susceptibility.load_susceptibility(roto, template,
                                              bbox_lonlat(LADO, LADO))

    assert mask is None
    assert "no pude cargar" in capsys.readouterr().out.lower()
