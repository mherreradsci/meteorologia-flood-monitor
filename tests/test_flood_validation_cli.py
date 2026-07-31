"""Contrato de la CLI de flood_validation. Sin red.

Mismo patrón que test_cli.py (flood_monitor/list_s1_items): fija los
defaults documentados para que no se desalineen solos.
"""

from __future__ import annotations

import pytest

import flood_monitor
from flood_validation import cli


def test_hace_falta_exactamente_un_modo_de_aoi():
    """--aoi/--bbox/--place son mutuamente excluyentes y obligatorios,
    igual que en flood_monitor.py/list_s1_items.py."""
    with pytest.raises(SystemExit):          # ninguno
        cli.parse_args([])

    with pytest.raises(SystemExit):          # dos a la vez
        cli.parse_args(["--place", "Punitaqui", "--bbox",
                        "-71", "-30", "-70", "-29"])


def test_bbox_exige_los_cuatro_valores():
    with pytest.raises(SystemExit):
        cli.parse_args(["--bbox", "-71", "-30"])


def test_los_defaults_son_los_documentados():
    a = cli.parse_args(["--place", "Punitaqui"])

    assert a.region == flood_monitor.DEFAULT_REGION
    assert a.buffer_km == 5.0
    assert a.days == 10
    assert a.start_date_utc is None
    assert a.end_date_utc is None
    assert a.local_time is False
    assert a.susceptibility is None
    assert a.dry_run is False
    assert a.output_dir == cli.DEFAULT_OUTPUT_DIR
    assert a.config_dir == cli.DEFAULT_CONFIG_DIR


def test_fechas_llegan_como_texto_sin_parsear():
    """argparse solo transporta; el parseo real es cosa de windows.py, que
    sabe de zonas horarias y de la asimetría inicio/fin de ventana."""
    a = cli.parse_args(["--place", "Punitaqui",
                        "--start-date-utc", "2026-07-15",
                        "--end-date-utc", "2026-07-22"])

    assert a.start_date_utc == "2026-07-15"
    assert a.end_date_utc == "2026-07-22"


def test_los_numericos_aceptan_negativos():
    """Un bbox en Chile es siempre negativo (lon/lat oeste/sur); si argparse
    los tomara por flags, --bbox sería inusable."""
    a = cli.parse_args(["--bbox", "-71.5", "-30.3", "-71.4", "-30.2"])

    assert a.bbox == [-71.5, -30.3, -71.4, -30.2]


def test_susceptibility_y_dry_run_son_opcionales():
    a = cli.parse_args(["--bbox", "-71.5", "-30.3", "-71.4", "-30.2",
                        "--susceptibility", "/tmp/x.tif", "--dry-run"])

    assert str(a.susceptibility) == "/tmp/x.tif"
    assert a.dry_run is True


def test_output_dir_y_config_dir_no_dependen_del_cwd():
    """A diferencia de OUTPUT_DIR en flood_monitor.py (relativo al cwd desde
    el que se invoca python), estos defaults se resuelven contra la
    ubicación del paquete."""
    assert cli.DEFAULT_OUTPUT_DIR.is_absolute()
    assert cli.DEFAULT_CONFIG_DIR.is_absolute()
    assert cli.DEFAULT_OUTPUT_DIR == cli.REPO_ROOT / "output" / "validation"
    assert cli.DEFAULT_CONFIG_DIR == cli.REPO_ROOT / "config"
