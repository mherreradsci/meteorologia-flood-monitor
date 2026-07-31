"""main() sin --dry-run: el camino real de la Fase 2, con GeoTIFF sintéticos
en vez de red. Marcado `raster` — separado de test_flood_validation_main.py
(que se queda solo con --dry-run) para no meter rioxarray en el job offline.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("rioxarray")
pytest.importorskip("geopandas")

import flood_monitor  # noqa: E402
from flood_validation import sar_layer  # noqa: E402
from flood_validation.main import main  # noqa: E402
from helpers import utc  # noqa: E402
from raster_helpers import ItemConRaster, bbox_lonlat, geotiff  # noqa: E402

pytestmark = pytest.mark.raster

LADO = 40
POTENCIA_SUELO = 0.16
POTENCIA_AGUA = 0.005


def escena_vh(con_agua=True):
    import numpy as np

    vh = np.full((LADO, LADO), POTENCIA_SUELO, dtype="float32")
    if con_agua:
        vh[10:20, 10:20] = POTENCIA_AGUA
    return vh


class CatalogoFalso:
    def __init__(self, escenas):
        self.escenas = escenas
        self.consultas = []

    def search(self, **kwargs):
        coleccion = kwargs["collections"][0]
        self.consultas.append(coleccion)
        if coleccion == "sentinel-1-rtc":
            items = self.escenas
        else:
            items = []  # sin JRC/DEM: las máscaras degradan solas (ya probado en flood_monitor)
        return type("S", (), {"item_collection": lambda _self: list(items)})()


@pytest.fixture
def catalogo_con_una_escena(monkeypatch, tmp_path):
    item = ItemConRaster(vh=geotiff(tmp_path, "vh.tif", escena_vh()))
    item.datetime = utc(2026, 7, 16, 10, 2, 47)
    item.id = "S1D_escena"
    item.properties = {"sat:relative_orbit": 156, "sat:orbit_state": "descending"}
    catalogo = CatalogoFalso([item])
    monkeypatch.setattr(flood_monitor, "stac_catalog", lambda: catalogo)
    monkeypatch.setattr(sar_layer, "stac_catalog", lambda: catalogo)
    return catalogo


def _correr(tmp_path, *opciones):
    xmin, ymin, xmax, ymax = bbox_lonlat(LADO, LADO)
    out_dir = tmp_path / "salida"
    main(["--bbox", str(xmin), str(ymin), str(xmax), str(ymax),
         "--start-date-utc", "2026-07-15", "--end-date-utc", "2026-07-22",
         "--output-dir", str(out_dir), *opciones])
    return out_dir


def test_corrida_real_escribe_geotiff_geojson_y_manifiesto(
        catalogo_con_una_escena, tmp_path):
    out_dir = _correr(tmp_path)

    tifs = list(out_dir.glob("real_flood_s1_*.tif"))
    geojsons = list(out_dir.glob("real_flood_s1_*.geojson"))
    manifiestos = list(out_dir.glob("run_manifest-*.json"))
    assert len(tifs) == 1
    assert len(geojsons) == 1
    assert len(manifiestos) == 1

    data = json.loads(manifiestos[0].read_text())
    assert data["dry_run"] is False
    assert data["outputs"]["sentinel1"]["tif"] == str(tifs[0])
    assert data["outputs"]["sentinel1"]["geojson"] == str(geojsons[0])
    assert len(data["sensors"]["sentinel1"]["acquisitions"]) == 1
    assert data["sensors"]["sentinel1"]["acquisitions"][0]["item_id"] == \
        "S1D_escena"
    assert data["sensors"]["sentinel1"]["skipped"] == []


def test_sin_escenas_en_la_ventana_igual_escribe_manifiesto(
        monkeypatch, tmp_path):
    catalogo = CatalogoFalso([])
    monkeypatch.setattr(flood_monitor, "stac_catalog", lambda: catalogo)
    monkeypatch.setattr(sar_layer, "stac_catalog", lambda: catalogo)

    out_dir = _correr(tmp_path)

    assert not list(out_dir.glob("real_flood_s1_*.tif"))
    data = json.loads(next(out_dir.glob("run_manifest-*.json")).read_text())
    assert data["sensors"]["sentinel1"]["acquisitions"] == []
    assert "sentinel1" not in data["outputs"]


def test_min_area_px_y_threshold_llegan_a_sar_layer(
        catalogo_con_una_escena, tmp_path, monkeypatch):
    """Cableado de opciones: mismo espíritu que
    test_cada_opcion_llega_a_su_etapa en test_main.py."""
    registro = {}
    original = sar_layer.build_real_flood_layer

    def espia(*args, **kwargs):
        registro["kwargs"] = kwargs
        return original(*args, **kwargs)

    monkeypatch.setattr(sar_layer, "build_real_flood_layer", espia)

    _correr(tmp_path, "--threshold", "-18.5", "--min-area-px", "7",
           "--max-slope", "12")

    assert registro["kwargs"]["threshold"] == -18.5
    assert registro["kwargs"]["min_area_px"] == 7
    assert registro["kwargs"]["max_slope"] == 12.0


def test_sentinel1_desactivado_en_config_no_corre_sar_layer(
        catalogo_con_una_escena, tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "regions.yaml").write_text("""
regions:
  "Región de Coquimbo, Chile":
    display_name: "Coquimbo"
    datasets:
      sentinel1: false
""")
    (config_dir / "validation.yaml").write_text("")

    xmin, ymin, xmax, ymax = bbox_lonlat(LADO, LADO)
    out_dir = tmp_path / "salida"
    main(["--bbox", str(xmin), str(ymin), str(xmax), str(ymax),
         "--start-date-utc", "2026-07-15", "--end-date-utc", "2026-07-22",
         "--output-dir", str(out_dir), "--config-dir", str(config_dir)])

    assert not list(out_dir.glob("real_flood_s1_*.tif"))
    data = json.loads(next(out_dir.glob("run_manifest-*.json")).read_text())
    assert data["sensors"] == {}
    assert data["outputs"] == {}
