"""main() sin --dry-run: el camino real de las Fases 2-3, con GeoTIFF
sintéticos en vez de red. Marcado `raster` — separado de
test_flood_validation_main.py (que se queda solo con --dry-run) para no
meter rioxarray en el job offline.

`sar_layer.py`, `optical_layer.py`, `terrain.py` y `seasonality.py`
importaron cada uno su propia referencia a `stac_catalog` (`from
flood_monitor import stac_catalog`, o junto con otros nombres), así que
parchear solo `flood_monitor.stac_catalog` no alcanza para ninguno — la
misma lección que ya deja conftest.py sobre `list_s1_items`. Sentinel-2
está prendido por default en `regions.yaml`, así que CUALQUIER test que
corra `main()` sin `--dry-run` sin parchear `optical_layer.stac_catalog`
termina pegándole a la Planetary Computer real (pasó una vez: una corrida
de ~6 minutos donde debía tardar segundos). Con la Fase 4, `main()` invoca
además `fusion.fuse()`, que llama a `terrain.hand_implausible_mask` y
`seasonality.seasonal_water_mask` — pasó *de nuevo*, esta vez con esos dos
módulos sin parchear (suite completa de ~13s a ~53s). Los cinco módulos se
parchean siempre juntos acá, aunque un test individual no vaya a ejercitar
los cinco.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("rioxarray")
pytest.importorskip("geopandas")

import flood_monitor  # noqa: E402
from flood_validation import (optical_layer, sar_layer,  # noqa: E402
                              seasonality, terrain)
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
    def __init__(self, escenas_s1=(), escenas_s2=()):
        self.escenas_s1 = list(escenas_s1)
        self.escenas_s2 = list(escenas_s2)
        self.consultas = []

    def search(self, **kwargs):
        coleccion = kwargs["collections"][0]
        self.consultas.append(coleccion)
        if coleccion == "sentinel-1-rtc":
            items = self.escenas_s1
        elif coleccion == "sentinel-2-l2a":
            items = self.escenas_s2
        else:
            items = []  # sin JRC/DEM: las máscaras degradan solas (ya probado en flood_monitor)
        return type("S", (), {"item_collection": lambda _self: list(items)})()


def _instalar(monkeypatch, catalogo):
    monkeypatch.setattr(flood_monitor, "stac_catalog", lambda: catalogo)
    monkeypatch.setattr(sar_layer, "stac_catalog", lambda: catalogo)
    monkeypatch.setattr(optical_layer, "stac_catalog", lambda: catalogo)
    monkeypatch.setattr(terrain, "stac_catalog", lambda: catalogo)
    monkeypatch.setattr(seasonality, "stac_catalog", lambda: catalogo)


@pytest.fixture
def catalogo_con_una_escena(monkeypatch, tmp_path):
    item = ItemConRaster(vh=geotiff(tmp_path, "vh.tif", escena_vh()))
    item.datetime = utc(2026, 7, 16, 10, 2, 47)
    item.id = "S1D_escena"
    item.properties = {"sat:relative_orbit": 156, "sat:orbit_state": "descending"}
    catalogo = CatalogoFalso(escenas_s1=[item])
    _instalar(monkeypatch, catalogo)
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
    catalogo = CatalogoFalso()
    _instalar(monkeypatch, catalogo)

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
      sentinel2: false
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


# --------------------------------------------------------------------------- #
# Fase 3: Sentinel-2, a través de main()
# --------------------------------------------------------------------------- #
AGUA_S2 = {"B03": 1000.0, "B11": 200.0, "B08": 200.0, "B12": 100.0, "B02": 800.0}
SECO_S2 = {"B03": 1500.0, "B11": 2500.0, "B08": 3000.0, "B12": 2000.0, "B02": 1200.0}


def _escena_s2(nombre, dt, tmp_path, parche_agua=None):
    import numpy as np

    bandas = {b: np.full((LADO, LADO), SECO_S2[b], dtype="float32")
             for b in AGUA_S2}
    if parche_agua is not None:
        for b in AGUA_S2:
            bandas[b][parche_agua] = AGUA_S2[b]
    scl = np.full((LADO, LADO), 6.0, dtype="float32")  # SCL "water", despejado
    assets = {b: geotiff(tmp_path, f"{nombre}_{b}.tif", arr)
             for b, arr in bandas.items()}
    assets["SCL"] = geotiff(tmp_path, f"{nombre}_SCL.tif", scl)
    it = ItemConRaster(**assets)
    it.datetime = dt
    it.id = nombre
    it.properties = {"eo:cloud_cover": 5.0}
    return it


def test_sentinel2_escribe_geotiff_geojson_y_manifiesto(monkeypatch, tmp_path):
    s2 = _escena_s2("S2_a", utc(2026, 7, 17), tmp_path,
                    parche_agua=(slice(5, 15), slice(5, 15)))
    catalogo = CatalogoFalso(escenas_s2=[s2])
    _instalar(monkeypatch, catalogo)

    out_dir = _correr(tmp_path)

    tifs = list(out_dir.glob("real_flood_s2_*.tif"))
    assert len(tifs) == 1
    data = json.loads(next(out_dir.glob("run_manifest-*.json")).read_text())
    assert data["outputs"]["sentinel2"]["tif"] == str(tifs[0])
    assert len(data["sensors"]["sentinel2"]["acquisitions"]) == 1
    assert data["sensors"]["sentinel2"]["acquisitions"][0]["item_id"] == "S2_a"
    # Sin escenas S1 en este catálogo: la corrida no debería fallar por eso.
    assert data["sensors"]["sentinel1"]["acquisitions"] == []


def test_awei_variant_llega_a_optical_layer(monkeypatch, tmp_path):
    """Cableado de --awei-variant: mismo espíritu que
    test_min_area_px_y_threshold_llegan_a_sar_layer."""
    s2 = _escena_s2("S2_a", utc(2026, 7, 17), tmp_path)
    catalogo = CatalogoFalso(escenas_s2=[s2])
    _instalar(monkeypatch, catalogo)

    registro = {}
    original = optical_layer.build_optical_water_layer

    def espia(*args, **kwargs):
        registro["kwargs"] = kwargs
        return original(*args, **kwargs)

    monkeypatch.setattr(optical_layer, "build_optical_water_layer", espia)

    _correr(tmp_path, "--awei-variant", "nsh")

    assert registro["kwargs"]["awei_variant"] == "nsh"


def test_sin_awei_variant_usa_el_de_la_region(monkeypatch, tmp_path):
    """Sin --awei-variant, usa el default de regions.yaml (config/
    regions.yaml trae 'sh' para Coquimbo)."""
    s2 = _escena_s2("S2_a", utc(2026, 7, 17), tmp_path)
    catalogo = CatalogoFalso(escenas_s2=[s2])
    _instalar(monkeypatch, catalogo)

    registro = {}
    original = optical_layer.build_optical_water_layer

    def espia(*args, **kwargs):
        registro["kwargs"] = kwargs
        return original(*args, **kwargs)

    monkeypatch.setattr(optical_layer, "build_optical_water_layer", espia)

    _correr(tmp_path)

    assert registro["kwargs"]["awei_variant"] == "sh"


# --------------------------------------------------------------------------- #
# Fase 4: fusión, a través de main()
# --------------------------------------------------------------------------- #
def test_fusion_escribe_geotiff_geojson_y_manifiesto(monkeypatch, tmp_path):
    s1 = ItemConRaster(vh=geotiff(tmp_path, "vh.tif", escena_vh()))
    s1.datetime = utc(2026, 7, 16, 10, 2, 47)
    s1.id = "S1D_escena"
    s1.properties = {"sat:relative_orbit": 156, "sat:orbit_state": "descending"}

    s2 = _escena_s2("S2_a", utc(2026, 7, 17), tmp_path,
                    parche_agua=(slice(10, 20), slice(10, 20)))
    catalogo = CatalogoFalso(escenas_s1=[s1], escenas_s2=[s2])
    _instalar(monkeypatch, catalogo)

    out_dir = _correr(tmp_path)

    tifs = list(out_dir.glob("real_flood_fused_*.tif"))
    assert len(tifs) == 1
    data = json.loads(next(out_dir.glob("run_manifest-*.json")).read_text())
    assert data["fusion"] is not None
    assert set(data["fusion"]["sensors_used"]) == {"sentinel1", "sentinel2"}
    assert data["fusion"]["tif"] == str(tifs[0])
    # Sin DEM/JRC en este catálogo falso, terrain/seasonality degradan
    # solos (ya probado por separado) — acá solo importa que no rompan
    # la corrida y que la fusión llegue a escribirse igual.
    assert data["fusion"]["terrain_excluded_px"] == 0
    assert data["fusion"]["seasonal_excluded_px"] == 0


def test_sin_ningun_sensor_fusion_queda_none_en_el_manifiesto(
        monkeypatch, tmp_path):
    catalogo = CatalogoFalso()
    _instalar(monkeypatch, catalogo)

    out_dir = _correr(tmp_path)

    assert not list(out_dir.glob("real_flood_fused_*.tif"))
    data = json.loads(next(out_dir.glob("run_manifest-*.json")).read_text())
    assert data["fusion"] is None


# --------------------------------------------------------------------------- #
# Fase 5: susceptibilidad + métricas, a través de main()
# --------------------------------------------------------------------------- #
def test_susceptibilidad_se_resuelve_y_las_metricas_se_escriben(
        monkeypatch, tmp_path):
    import numpy as np

    from raster_helpers import grilla

    s1 = ItemConRaster(vh=geotiff(tmp_path, "vh.tif", escena_vh()))
    s1.datetime = utc(2026, 7, 16, 10, 2, 47)
    s1.id = "S1D_escena"
    s1.properties = {"sat:relative_orbit": 156, "sat:orbit_state": "descending"}
    catalogo = CatalogoFalso(escenas_s1=[s1])
    _instalar(monkeypatch, catalogo)

    # Producto de susceptibilidad sintético: mismo bbox/grilla que la
    # escena S1, coincidiendo con su parche de agua (10:20, 10:20).
    susc_root = tmp_path / "proyecciones" / "outputs" / "coquimbo"
    gfs_dir = susc_root / "gfs"
    gfs_dir.mkdir(parents=True)
    susc_valores = np.zeros((LADO, LADO), dtype="float32")
    susc_valores[10:20, 10:20] = 1.0
    grilla(susc_valores).rio.to_raster(
        gfs_dir / "mapa_anegamientos_gfs_extension_20260714_00utc_20260714-010000.tif")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "regions.yaml").write_text(f"""
regions:
  "Región de Coquimbo, Chile":
    display_name: "Coquimbo"
    susceptibility:
      source_root: "{susc_root}"
      sufijo_preferido: gfs
""")
    (config_dir / "validation.yaml").write_text("")

    xmin, ymin, xmax, ymax = bbox_lonlat(LADO, LADO)
    out_dir = tmp_path / "salida"
    main(["--bbox", str(xmin), str(ymin), str(xmax), str(ymax),
         "--start-date-utc", "2026-07-15", "--end-date-utc", "2026-07-22",
         "--output-dir", str(out_dir), "--config-dir", str(config_dir)])

    metricas = list(out_dir.glob("validation_metrics-*.json"))
    assert len(metricas) == 1
    data = json.loads(next(out_dir.glob("run_manifest-*.json")).read_text())
    assert data["validation"] is not None
    assert data["validation"]["cycle_sufijo"] == "gfs"
    assert data["validation"]["metrics_path"] == str(metricas[0])

    m = json.loads(metricas[0].read_text())
    assert m["confusion_matrix"]["tp"] > 0
    assert m["cycle_utc"] == "2026-07-14T00:00:00+00:00"


def test_sin_ciclo_que_cubra_la_ventana_validation_queda_none(
        monkeypatch, tmp_path):
    s1 = ItemConRaster(vh=geotiff(tmp_path, "vh.tif", escena_vh()))
    s1.datetime = utc(2026, 7, 16, 10, 2, 47)
    s1.id = "S1D_escena"
    s1.properties = {"sat:relative_orbit": 156, "sat:orbit_state": "descending"}
    catalogo = CatalogoFalso(escenas_s1=[s1])
    _instalar(monkeypatch, catalogo)

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "regions.yaml").write_text(f"""
regions:
  "Región de Coquimbo, Chile":
    display_name: "Coquimbo"
    susceptibility:
      source_root: "{tmp_path / 'sin_nada'}"
      sufijo_preferido: gfs
""")
    (config_dir / "validation.yaml").write_text("")

    xmin, ymin, xmax, ymax = bbox_lonlat(LADO, LADO)
    out_dir = tmp_path / "salida"
    main(["--bbox", str(xmin), str(ymin), str(xmax), str(ymax),
         "--start-date-utc", "2026-07-15", "--end-date-utc", "2026-07-22",
         "--output-dir", str(out_dir), "--config-dir", str(config_dir)])

    assert not list(out_dir.glob("validation_metrics-*.json"))
    data = json.loads(next(out_dir.glob("run_manifest-*.json")).read_text())
    assert data["validation"] is None
