"""Andamiaje para los tests marcados `raster`: grillas y GeoTIFF sintéticos.

Vive aparte de `helpers.py` a propósito: eso importa rioxarray, y `helpers.py`
lo usan también los tests del job mínimo de CI, que corre sin GDAL. Solo lo
importan módulos marcados `raster`.

La grilla imita la de una escena Sentinel-1 RTC sobre la Región de Coquimbo:
UTM 19S a 30 m/px. El origen elegido cae sobre Tongoy (-30.257, -71.493), así
que las coordenadas que salen en lon/lat son reconocibles a simple vista.
"""

from __future__ import annotations

import numpy as np
import xarray as xr
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

import rioxarray  # noqa: F401  (registra el accessor .rio)

CRS = "EPSG:32719"
RES = 30.0
X0, Y0 = 260_000.0, 6_650_000.0


def grilla(values: np.ndarray, x0: float = X0, y0: float = Y0):
    """DataArray georreferenciado sobre la grilla de referencia."""
    alto, ancho = values.shape
    da = xr.DataArray(
        values.astype("float32"), dims=("y", "x"),
        coords={"y": y0 - np.arange(alto) * RES - RES / 2,
                "x": x0 + np.arange(ancho) * RES + RES / 2},
    )
    return (da.rio.write_crs(CRS)
              .rio.write_transform(from_origin(x0, y0, RES, RES)))


def geotiff(tmp_path, nombre: str, values: np.ndarray, x0: float = X0) -> str:
    """Escribe un GeoTIFF chico y devuelve su ruta."""
    ruta = tmp_path / nombre
    grilla(values, x0=x0).rio.to_raster(ruta)
    return str(ruta)


def bbox_lonlat(alto: int, ancho: int) -> tuple:
    """El bbox en lon/lat que cubre la grilla.

    Es lo que reciben las funciones del pipeline: el AOI siempre viaja en
    EPSG:4326, aunque los rásters estén en UTM.
    """
    return transform_bounds(CRS, "EPSG:4326",
                            X0, Y0 - alto * RES, X0 + ancho * RES, Y0)


class ItemConRaster:
    """Item STAC mínimo cuyos assets apuntan a archivos locales."""

    def __init__(self, **assets: str):
        self.id = "FAKE_RASTER"
        self.assets = {k: type("A", (), {"href": v})()
                       for k, v in assets.items()}
