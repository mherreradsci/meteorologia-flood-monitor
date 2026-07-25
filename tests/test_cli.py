"""Contrato de la línea de comandos. Sin red.

Los defaults están documentados en README.md y CLAUDE.md; estos tests los
fijan para que la documentación no se desactualice sola.
"""

from __future__ import annotations

import pytest

import flood_monitor
import list_s1_items


def parsear(argv, modulo=flood_monitor, monkeypatch=None):
    monkeypatch.setattr("sys.argv", ["prog", *argv])
    return modulo.parse_args()


# --------------------------------------------------------------------------- #
# Exclusividad de los modos de AOI
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("modulo", [flood_monitor, list_s1_items],
                         ids=["flood_monitor", "list_s1_items"])
def test_hace_falta_exactamente_un_modo_de_aoi(modulo, monkeypatch):
    """--aoi / --bbox / --place son mutuamente excluyentes y obligatorios.

    Los dos scripts comparten la convención; si uno se desalinea, correr el
    mismo comando en cada uno daría AOIs distintos.
    """
    with pytest.raises(SystemExit):          # ninguno
        parsear([], modulo, monkeypatch)

    with pytest.raises(SystemExit):          # dos a la vez
        parsear(["--place", "Tongoy", "--bbox", "-71", "-30", "-70", "-29"],
                modulo, monkeypatch)


def test_bbox_exige_los_cuatro_valores(monkeypatch):
    with pytest.raises(SystemExit):
        parsear(["--bbox", "-71", "-30"], flood_monitor, monkeypatch)


# --------------------------------------------------------------------------- #
# Defaults documentados
# --------------------------------------------------------------------------- #
def test_los_defaults_son_los_documentados(monkeypatch):
    a = parsear(["--place", "Tongoy"], flood_monitor, monkeypatch)

    assert a.days == 10
    assert a.buffer_km == 5.0
    assert a.min_area_px == 20
    assert a.ref_days == 45
    assert a.change_delta == 3.0
    assert a.max_slope == 5.0
    assert a.region == flood_monitor.DEFAULT_REGION
    # Sin valor, ambos caen a su comportamiento automático: Otsu para el
    # umbral, "ahora" para el corte.
    assert a.threshold is None
    assert a.end_date is None
    assert a.change is False


def test_end_date_llega_como_texto_sin_parsear(monkeypatch):
    """argparse solo transporta; el parseo es de parse_end_date, que sabe de
    zonas horarias y del final del día."""
    a = parsear(["--place", "Tongoy", "--end-date", "2026-07-16"],
                flood_monitor, monkeypatch)

    assert a.end_date == "2026-07-16"


def test_los_numericos_aceptan_negativos(monkeypatch):
    """Los umbrales en dB son negativos: si argparse los tomara por flags,
    `--threshold -18` sería inusable."""
    a = parsear(["--bbox", "-71.5", "-30.3", "-71.4", "-30.2",
                 "--threshold", "-18.5"], flood_monitor, monkeypatch)

    assert a.threshold == -18.5
    assert a.bbox == [-71.5, -30.3, -71.4, -30.2]


def test_defaults_del_script_hermano(monkeypatch):
    a = parsear(["--place", "Tongoy"], list_s1_items, monkeypatch)

    assert a.num_items == 10
    assert a.end_date is None
    assert a.days_back is None   # sin límite: todo el archivo
    assert a.region == flood_monitor.DEFAULT_REGION
