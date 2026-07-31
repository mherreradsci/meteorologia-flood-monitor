"""outputs.py — escritura de GeoTIFF/GeoJSON compartida por las capas de
sensor (sar_layer.py, optical_layer.py, y las que sigan).

Mismo método que `flood_monitor.save_outputs` (rasterio.features.shapes +
reproyección a EPSG:4326), pero sin el quicklook PNG ni el mapa HTML: eso
llega con report.py en la Fase 6, cuando hay fusión de sensores que mostrar
y no solo una capa intermedia por sensor.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def write_geotiff_geojson(template, flood: np.ndarray, output_dir: Path,
                          tag: str, prefix: str) -> dict[str, Path | None]:
    """Escribe `<prefix>_<tag>.tif` (binario) y, si hay polígonos,
    `<prefix>_<tag>.geojson` (EPSG:4326). `template` es cualquier DataArray
    de rioxarray con el CRS/transform de la grilla de `flood` — la capa
    que lo produjo, no necesariamente `flood` en sí."""
    import geopandas as gpd
    import rasterio.features
    from shapely.geometry import shape as shp_shape

    output_dir.mkdir(parents=True, exist_ok=True)

    tif = output_dir / f"{prefix}_{tag}.tif"
    mask_da = template.copy(data=flood.astype("uint8"))
    mask_da.rio.write_nodata(255, inplace=True)
    mask_da.rio.to_raster(tif, dtype="uint8", compress="deflate")

    transform = template.rio.transform()
    shapes = rasterio.features.shapes(flood.astype("uint8"), mask=flood,
                                      transform=transform)
    geoms = [shp_shape(g) for g, v in shapes if v == 1]
    geojson = None
    if geoms:
        gdf = gpd.GeoDataFrame(geometry=geoms, crs=template.rio.crs)
        gdf = gdf.to_crs("EPSG:4326")
        geojson = output_dir / f"{prefix}_{tag}.geojson"
        gdf.to_file(geojson, driver="GeoJSON")

    print(f"[+] {prefix}: GeoTIFF {tif}" +
         (f", GeoJSON {geojson} ({len(geoms)} polígonos)" if geoms
          else " (sin polígonos de anegamiento para vectorizar)"))
    return {"tif": tif, "geojson": geojson}
