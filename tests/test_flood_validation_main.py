"""main() de punta a punta en modo --dry-run. Sin red: usa --bbox, que no
geocodifica (a diferencia de --place, que llamaría a Nominatim).

Mismo espíritu que test_main.py para flood_monitor.py: lo que verifica es lo
que ningún test aislado puede ver — que el valor de cada flag llegue a la
etapa que corresponde y que el manifiesto termine reflejando la corrida.
"""

from __future__ import annotations

import json

import pytest

from flood_validation.main import main

BBOX = ["--bbox", "-71.5", "-30.3", "-71.4", "-30.2"]


def test_dry_run_escribe_manifiesto(tmp_path):
    out_dir = tmp_path / "salida"
    main([*BBOX, "--start-date-utc", "2026-07-15",
         "--end-date-utc", "2026-07-22", "--dry-run",
         "--output-dir", str(out_dir)])

    manifiestos = list(out_dir.glob("run_manifest-*.json"))
    assert len(manifiestos) == 1

    data = json.loads(manifiestos[0].read_text())
    assert data["dry_run"] is True
    assert data["aoi"]["mode"] == "bbox"
    assert data["aoi"]["bbox"] == [-71.5, -30.3, -71.4, -30.2]
    assert data["window"]["start_utc"].startswith("2026-07-15")
    assert data["window"]["end_utc"].startswith("2026-07-22")
    assert set(data["sensors_enabled"]) == {"sentinel1", "sentinel2",
                                            "dynamic_world"}
    assert len(data["config_hash"]) == 16
    assert data["python_version"]


def test_dos_corridas_no_se_pisan(tmp_path):
    out_dir = tmp_path / "salida"
    main([*BBOX, "--end-date-utc", "2026-07-22", "--dry-run",
         "--output-dir", str(out_dir)])
    main([*BBOX, "--end-date-utc", "2026-07-22", "--dry-run",
         "--output-dir", str(out_dir)])

    assert len(list(out_dir.glob("run_manifest-*.json"))) == 2


def test_susceptibility_explicito_queda_en_el_manifiesto(tmp_path):
    out_dir = tmp_path / "salida"
    tif = tmp_path / "extension_gfs.tif"
    tif.write_bytes(b"")

    main([*BBOX, "--end-date-utc", "2026-07-22", "--dry-run",
         "--output-dir", str(out_dir), "--susceptibility", str(tif)])

    data = json.loads(next(out_dir.glob("run_manifest-*.json")).read_text())
    assert data["susceptibility"]["explicit_path"] == str(tif)


def test_sin_dry_run_avisa_que_no_esta_implementado(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main([*BBOX, "--end-date-utc", "2026-07-22",
             "--output-dir", str(tmp_path)])

    assert not list(tmp_path.glob("run_manifest-*.json"))


def test_region_desconocida_sin_default_falla_temprano(tmp_path):
    """No debería llegar a resolver la ventana ni a tocar el AOI si la
    región no tiene config y regions.yaml tampoco trae 'default'."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "regions.yaml").write_text("regions: {}\n")
    (config_dir / "validation.yaml").write_text("")

    with pytest.raises(SystemExit):
        main([*BBOX, "--end-date-utc", "2026-07-22", "--dry-run",
             "--config-dir", str(config_dir),
             "--output-dir", str(tmp_path / "salida")])
