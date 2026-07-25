"""`read_vh_db`: de potencia lineal a decibelios. Sin red, con GDAL.

`to_db` ya se prueba aislada en test_detection.py; acá se verifica el cableado
completo sobre un GeoTIFF real: recorte, colapso de la banda, conversión y
tratamiento de los píxeles inválidos. Si esta función devolviera potencia
lineal en vez de dB, todos los umbrales del pipeline (que hablan en dB)
quedarían sin sentido y ningún otro test lo notaría.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("rioxarray")

from flood_monitor import read_vh_db  # noqa: E402
from raster_helpers import (RES, ItemConRaster, bbox_lonlat,  # noqa: E402
                            geotiff)

pytestmark = pytest.mark.raster


def test_convierte_potencia_lineal_a_decibelios(tmp_path):
    """10*log10: 1.0 -> 0 dB, 0.1 -> -10 dB, 0.01 -> -20 dB."""
    potencia = np.full((10, 10), 1.0, dtype="float32")
    potencia[0, :] = 0.1
    potencia[1, :] = 0.01
    item = ItemConRaster(vh=geotiff(tmp_path, "vh.tif", potencia))

    vh_db = read_vh_db(item, bbox_lonlat(10, 10))

    np.testing.assert_allclose(vh_db.values[0, :], -10.0, atol=1e-4)
    np.testing.assert_allclose(vh_db.values[1, :], -20.0, atol=1e-4)
    np.testing.assert_allclose(vh_db.values[5, :], 0.0, atol=1e-4)


def test_los_ceros_terminan_en_nan(tmp_path):
    """log10(0) no existe: `to_db` los marca con DB_NODATA y `read_vh_db`
    convierte ese centinela en NaN, que es lo que el resto del pipeline
    entiende como "sin dato"."""
    potencia = np.full((10, 10), 1.0, dtype="float32")
    potencia[3:6, 3:6] = 0.0
    item = ItemConRaster(vh=geotiff(tmp_path, "ceros.tif", potencia))

    vh_db = read_vh_db(item, bbox_lonlat(10, 10))

    assert np.isnan(vh_db.values[3:6, 3:6]).all()
    assert np.isfinite(vh_db.values[0, 0])


def test_el_centinela_no_sobrevive_como_numero(tmp_path):
    """DB_NODATA (-9999) nunca debe quedar como valor real: sería el píxel
    más oscuro posible y entraría como agua en cualquier umbral."""
    potencia = np.full((8, 8), 1.0, dtype="float32")
    potencia[0, 0] = 0.0
    item = ItemConRaster(vh=geotiff(tmp_path, "centinela.tif", potencia))

    vh_db = read_vh_db(item, bbox_lonlat(8, 8))

    assert not (vh_db.values < -100).any()


def test_devuelve_una_grilla_2d_georreferenciada(tmp_path):
    """La banda se colapsa (`squeeze`) y el CRS sobrevive: el resto del
    pipeline usa `.rio.transform()` y `.rio.crs` para escribir el GeoTIFF y
    reproyectar las máscaras."""
    item = ItemConRaster(vh=geotiff(tmp_path, "grid.tif",
                                    np.full((12, 12), 1.0)))

    vh_db = read_vh_db(item, bbox_lonlat(12, 12))

    assert vh_db.ndim == 2
    assert vh_db.rio.crs.to_epsg() == 32719
    assert abs(vh_db.rio.resolution()[0]) == RES


def test_recorta_al_bbox_pedido(tmp_path):
    """El AOI llega en lon/lat aunque el ráster esté en UTM: `clip_box` hace
    la conversión. Sin recorte se descargaría y procesaría la escena entera."""
    item = ItemConRaster(vh=geotiff(tmp_path, "grande.tif",
                                    np.full((40, 40), 1.0)))

    entero = read_vh_db(item, bbox_lonlat(40, 40))
    recortado = read_vh_db(item, bbox_lonlat(10, 10))

    assert recortado.shape[0] < entero.shape[0]
    assert recortado.shape[1] < entero.shape[1]
