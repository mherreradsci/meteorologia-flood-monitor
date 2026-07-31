"""outputs.write_geotiff_geojson: escritura de GeoTIFF/GeoJSON compartida
entre sar_layer.py y optical_layer.py. Marcado `raster`, sin red — grilla
sintética directa, sin pasar por ningún catálogo STAC.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("rioxarray")
pytest.importorskip("geopandas")

from flood_validation import outputs  # noqa: E402
from raster_helpers import grilla  # noqa: E402

pytestmark = pytest.mark.raster

LADO = 20


def test_escribe_los_dos_archivos(tmp_path):
    import rioxarray

    template = grilla(np.zeros((LADO, LADO), dtype="float32"))
    flood = np.zeros((LADO, LADO), dtype=bool)
    flood[5:10, 5:10] = True

    paths = outputs.write_geotiff_geojson(
        template, flood, tmp_path, "tag_de_prueba", prefix="real_flood_s1")

    assert paths["tif"].exists()
    assert paths["geojson"].exists()
    assert paths["tif"].name == "real_flood_s1_tag_de_prueba.tif"
    escrito = rioxarray.open_rasterio(paths["tif"]).values.squeeze()
    assert int(escrito.sum()) == int(flood.sum())


def test_sin_agua_no_escribe_geojson(tmp_path):
    template = grilla(np.zeros((LADO, LADO), dtype="float32"))
    flood = np.zeros((LADO, LADO), dtype=bool)

    paths = outputs.write_geotiff_geojson(
        template, flood, tmp_path, "tag_seco", prefix="real_flood_s2")

    assert paths["tif"].exists()
    assert paths["geojson"] is None


def test_el_prefijo_distingue_las_salidas_de_cada_sensor(tmp_path):
    """S1 y S2 comparten tag de corrida: el prefijo es lo único que evita
    que uno pise al otro en el mismo output_dir."""
    template = grilla(np.zeros((LADO, LADO), dtype="float32"))
    flood = np.zeros((LADO, LADO), dtype=bool)
    flood[2:4, 2:4] = True

    p1 = outputs.write_geotiff_geojson(template, flood, tmp_path, "t",
                                       prefix="real_flood_s1")
    p2 = outputs.write_geotiff_geojson(template, flood, tmp_path, "t",
                                       prefix="real_flood_s2")

    assert p1["tif"] != p2["tif"]
    assert p1["tif"].exists() and p2["tif"].exists()


# --------------------------------------------------------------------------- #
# write_tiered_geotiff_geojson (fusion.py, Fase 4)
# --------------------------------------------------------------------------- #
def test_tiered_escribe_geotiff_y_geojson_con_propiedad_tier(tmp_path):
    import geopandas as gpd
    import rioxarray

    template = grilla(np.zeros((LADO, LADO), dtype="float32"))
    tier = np.zeros((LADO, LADO), dtype="uint8")
    tier[2:5, 2:5] = 3   # alta
    tier[10:12, 10:12] = 1   # baja
    labels = {1: "baja", 2: "media", 3: "alta"}

    paths = outputs.write_tiered_geotiff_geojson(
        template, tier, tmp_path, "tag", prefix="real_flood_fused",
        tier_labels=labels)

    assert paths["tif"].exists()
    escrito = rioxarray.open_rasterio(paths["tif"]).values.squeeze()
    assert int(escrito.max()) == 3

    gdf = gpd.read_file(paths["geojson"])
    assert set(gdf["tier"]) == {1, 3}
    assert set(gdf["tier_label"]) == {"baja", "alta"}


def test_tiered_sin_nada_por_encima_de_seca_no_escribe_geojson(tmp_path):
    template = grilla(np.zeros((LADO, LADO), dtype="float32"))
    tier = np.zeros((LADO, LADO), dtype="uint8")

    paths = outputs.write_tiered_geotiff_geojson(
        template, tier, tmp_path, "tag_seco", prefix="real_flood_fused",
        tier_labels={1: "baja", 2: "media", 3: "alta"})

    assert paths["tif"].exists()
    assert paths["geojson"] is None
