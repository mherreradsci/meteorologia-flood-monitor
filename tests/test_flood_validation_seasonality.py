"""seasonality.py: agua estacional/de riego vía JRC GSW seasonality.
Marcado `raster`, sin red — mismo truco que test_masks.py.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("rioxarray")

from flood_validation import seasonality  # noqa: E402
from raster_helpers import ItemConRaster, bbox_lonlat, geotiff, grilla  # noqa: E402

pytestmark = pytest.mark.raster

GEOM = {"type": "Point", "coordinates": [-71.49, -30.25]}


def test_agua_estacional_se_detecta_sobre_el_umbral(tmp_path, fake_stac):
    seas = np.zeros((20, 20), dtype="float32")
    seas[5:10, 5:10] = 3.0  # canal de riego: 3 meses/año
    fake_stac([ItemConRaster(seasonality=geotiff(tmp_path, "seas.tif", seas))],
             modulo=seasonality)

    mask = seasonality.seasonal_water_mask(GEOM, bbox_lonlat(20, 20),
                                           grilla(np.zeros((20, 20))))

    assert mask[5:10, 5:10].all()
    assert not mask[15:20, 15:20].any()


def test_un_mes_de_ruido_no_cuenta(tmp_path, fake_stac):
    seas = np.zeros((20, 20), dtype="float32")
    seas[5:10, 5:10] = 1.0  # un mes: más ruido de detección que patrón
    fake_stac([ItemConRaster(seasonality=geotiff(tmp_path, "seas.tif", seas))],
             modulo=seasonality)

    mask = seasonality.seasonal_water_mask(GEOM, bbox_lonlat(20, 20),
                                           grilla(np.zeros((20, 20))),
                                           min_months=2)

    assert not mask.any()


def test_min_months_es_configurable(tmp_path, fake_stac):
    seas = np.full((20, 20), 4.0, dtype="float32")
    fake_stac([ItemConRaster(seasonality=geotiff(tmp_path, "seas.tif", seas))],
             modulo=seasonality)

    estricta = seasonality.seasonal_water_mask(
        GEOM, bbox_lonlat(20, 20), grilla(np.zeros((20, 20))), min_months=5)
    assert not estricta.any()  # 4 < 5, nada califica

    laxa = seasonality.seasonal_water_mask(
        GEOM, bbox_lonlat(20, 20), grilla(np.zeros((20, 20))), min_months=3)
    assert laxa.all()  # 4 >= 3, todo califica


def test_sin_tiles_de_jrc_devuelve_none(fake_stac):
    fake_stac([], modulo=seasonality)

    assert seasonality.seasonal_water_mask(
        GEOM, bbox_lonlat(20, 20), grilla(np.zeros((20, 20)))) is None


def test_falla_suave(monkeypatch, capsys):
    def explota():
        raise RuntimeError("JRC caído")

    monkeypatch.setattr(seasonality, "stac_catalog", explota)

    resultado = seasonality.seasonal_water_mask(
        GEOM, bbox_lonlat(20, 20), grilla(np.zeros((20, 20))))

    assert resultado is None
    assert "JRC caído" in capsys.readouterr().out
