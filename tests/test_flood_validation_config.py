"""Config loader de flood_validation (regions.yaml / validation.yaml). Sin
red.

Dos frentes: unit tests con YAML sintético en tmp_path (forma de las
dataclasses, fallbacks), y un smoke test sobre los config/*.yaml reales del
repo — mismo espíritu que el test parametrizado de test_aoi.py sobre
aoi/*.geojson: esos archivos son documentación que CI protege.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flood_validation import cli, config

REPO_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


# --------------------------------------------------------------------------- #
# regions.yaml
# --------------------------------------------------------------------------- #
def test_carga_una_region_con_todos_los_campos(tmp_path):
    (tmp_path / "regions.yaml").write_text("""
regions:
  "Región de Prueba":
    display_name: "Prueba"
    map_center: [-71.2, -30.1]
    zoom: 10
    susceptibility:
      source_root: "../otro-repo/outputs/prueba"
      sufijo_preferido: ifs
    datasets:
      sentinel1: true
      sentinel2: false
      dynamic_world: true
    hand_threshold_m: 3.5
    awei_variant: nsh
    confidence_threshold: 0.6
""")
    regions = config.load_regions_config(tmp_path / "regions.yaml")
    r = regions["Región de Prueba"]

    assert r.display_name == "Prueba"
    assert r.map_center == (-71.2, -30.1)
    assert r.zoom == 10
    assert r.susceptibility.source_root == "../otro-repo/outputs/prueba"
    assert r.susceptibility.sufijo_preferido == "ifs"
    assert r.datasets.sentinel1 is True
    assert r.datasets.sentinel2 is False
    assert r.datasets.dynamic_world is True
    assert r.hand_threshold_m == 3.5
    assert r.awei_variant == "nsh"
    assert r.confidence_threshold == 0.6


def test_campos_faltantes_usan_los_defaults_de_la_dataclass(tmp_path):
    (tmp_path / "regions.yaml").write_text("""
regions:
  "Región Mínima":
    display_name: "Mínima"
""")
    regions = config.load_regions_config(tmp_path / "regions.yaml")
    r = regions["Región Mínima"]

    assert r.map_center is None
    assert r.zoom == 12
    assert r.susceptibility.source_root is None
    assert r.susceptibility.sufijo_preferido == "gfs"
    assert r.datasets.sentinel1 is True
    assert r.datasets.dynamic_world is False
    assert r.hand_threshold_m == 5.0
    assert r.awei_variant == "sh"


def test_resolve_region_config_usa_default_si_no_matchea(tmp_path, capsys):
    (tmp_path / "regions.yaml").write_text("""
regions:
  "Región Conocida":
    display_name: "Conocida"
default:
  display_name: "default"
  zoom: 9
""")
    regions = config.load_regions_config(tmp_path / "regions.yaml")

    r = config.resolve_region_config("Región Desconocida", regions)

    assert r.display_name == "default"
    assert r.zoom == 9
    assert "Región Desconocida" in capsys.readouterr().out


def test_resolve_region_config_sin_default_falla(tmp_path):
    (tmp_path / "regions.yaml").write_text("""
regions:
  "Región Conocida":
    display_name: "Conocida"
""")
    regions = config.load_regions_config(tmp_path / "regions.yaml")

    with pytest.raises(SystemExit):
        config.resolve_region_config("Región Desconocida", regions)


def test_config_inexistente_falla_con_mensaje_claro(tmp_path):
    with pytest.raises(SystemExit):
        config.load_regions_config(tmp_path / "no_existe.yaml")


# --------------------------------------------------------------------------- #
# validation.yaml
# --------------------------------------------------------------------------- #
def test_carga_validation_config(tmp_path):
    (tmp_path / "validation.yaml").write_text("""
stac_collections:
  sentinel1: sentinel-1-rtc
  sentinel2: sentinel-2-l2a
fusion_weights:
  sentinel1: 0.6
  sentinel2: 0.3
  dynamic_world: 0.1
confidence_tiers:
  high: 0.8
  medium: 0.5
  low: 0.2
basemap: osm
buffer_tolerance_m: 250.0
""")
    v = config.load_validation_config(tmp_path / "validation.yaml")

    assert v.stac_collections == {"sentinel1": "sentinel-1-rtc",
                                  "sentinel2": "sentinel-2-l2a"}
    assert v.fusion_weights.sentinel1 == 0.6
    assert v.confidence_tiers["high"] == 0.8
    assert v.basemap == "osm"
    assert v.buffer_tolerance_m == 250.0


def test_validation_config_vacio_usa_defaults(tmp_path):
    (tmp_path / "validation.yaml").write_text("")

    v = config.load_validation_config(tmp_path / "validation.yaml")

    assert v.basemap == "esri"
    assert v.buffer_tolerance_m == 100.0
    assert v.fusion_weights.sentinel1 == 0.5


# --------------------------------------------------------------------------- #
# config/*.yaml reales del repo — documentación que CI protege
# --------------------------------------------------------------------------- #
def test_regions_yaml_del_repo_carga_y_resuelve_coquimbo():
    regions = config.load_regions_config(REPO_CONFIG_DIR / "regions.yaml")

    r = config.resolve_region_config("Región de Coquimbo, Chile", regions)

    assert r.susceptibility.source_root == \
        "../meteorologia-flood-projections/outputs/coquimbo"
    assert r.susceptibility.sufijo_preferido == "gfs"
    assert "default" in regions


def test_validation_yaml_del_repo_carga():
    v = config.load_validation_config(REPO_CONFIG_DIR / "validation.yaml")

    assert v.stac_collections["sentinel1"] == "sentinel-1-rtc"
    assert v.stac_collections["sentinel2"] == "sentinel-2-l2a"
    assert 0.0 < v.confidence_tiers["low"] < v.confidence_tiers["medium"] \
        < v.confidence_tiers["high"] <= 1.0


def test_cli_defaults_apuntan_a_ese_mismo_config_dir():
    assert cli.DEFAULT_CONFIG_DIR == REPO_CONFIG_DIR
