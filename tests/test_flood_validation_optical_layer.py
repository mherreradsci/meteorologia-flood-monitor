"""optical_layer.py: unión de escenas Sentinel-2 dentro de la ventana, AWEI
+ máscara SCL. Marcado `raster`, sin red — mismo truco que
test_flood_validation_sar_layer.py: se sustituye `stac_catalog` por un
catálogo que sirve GeoTIFF sintéticos por banda, y el resto corre de
verdad.

Reflectancias sintéticas (DN, se dividen por 10000 en el código): un
"agua" y un "seco" elegidos a mano para que las dos variantes de AWEI
coincidan en el signo (ver el cálculo en los comentarios), así los tests no
dependen de los valores exactos de la fórmula, solo de que separen agua de
tierra.

    agua: green=1000 swir1=200  nir=200  swir2=100 blue=800
      AWEInsh = 4*(0.10-0.02) - (0.25*0.02+2.75*0.01) = 0.2875  (>0)
      AWEIsh  = 0.08+2.5*0.10 -1.5*(0.02+0.02) -0.25*0.01 = 0.2675  (>0)
    seco: green=1500 swir1=2500 nir=3000 swir2=2000 blue=1200
      AWEInsh = 4*(0.15-0.25) - (0.25*0.30+2.75*0.20) = -1.025  (<0)
      AWEIsh  = 0.12+2.5*0.15 -1.5*(0.30+0.25) -0.25*0.20 = -0.38  (<0)
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("rioxarray")
pytest.importorskip("geopandas")

from flood_validation import optical_layer  # noqa: E402
from helpers import utc  # noqa: E402
from raster_helpers import ItemConRaster, bbox_lonlat, geotiff  # noqa: E402

pytestmark = pytest.mark.raster

LADO = 20
AGUA = {"B03": 1000.0, "B11": 200.0, "B08": 200.0, "B12": 100.0, "B02": 800.0}
SECO = {"B03": 1500.0, "B11": 2500.0, "B08": 3000.0, "B12": 2000.0, "B02": 1200.0}
SCL_CLARO = 6      # agua, clase SCL "water"
SCL_NUBE = 9       # cloud high probability
START = utc(2026, 7, 15)
END = utc(2026, 7, 22, 23, 59, 59)


def escena_bandas(parche_agua, parche_nube=None):
    """Devuelve dict banda->array DN, con `parche_agua` en valores de agua
    y el resto en valores de suelo seco; `parche_nube` (opcional) marca esa
    región como SCL_NUBE en vez de SCL_CLARO."""
    bandas = {b: np.full((LADO, LADO), SECO[b], dtype="float32")
             for b in AGUA}
    if parche_agua is not None:
        for b in AGUA:
            bandas[b][parche_agua] = AGUA[b]
    scl = np.full((LADO, LADO), SCL_CLARO, dtype="float32")
    if parche_nube is not None:
        scl[parche_nube] = SCL_NUBE
    return bandas, scl


class CatalogoFalso:
    def __init__(self, escenas):
        self.escenas = escenas
        self.consultas = []

    def search(self, **kwargs):
        self.consultas.append(kwargs["collections"][0])
        return type("S", (), {
            "item_collection": lambda _self: list(self.escenas)})()


@pytest.fixture
def instalar_catalogo(monkeypatch):
    def hacerlo(escenas):
        catalogo = CatalogoFalso(escenas)
        monkeypatch.setattr(optical_layer, "stac_catalog", lambda: catalogo)
        return catalogo
    return hacerlo


def _item(nombre, dt, tmp_path, parche_agua=None, parche_nube=None,
         cloud_cover=10.0, bandas_rotas=False):
    bandas, scl = escena_bandas(parche_agua, parche_nube)
    if bandas_rotas:
        assets = {"B03": "/no/existe/B03.tif"}
    else:
        assets = {b: geotiff(tmp_path, f"{nombre}_{b}.tif", arr)
                  for b, arr in bandas.items()}
        assets["SCL"] = geotiff(tmp_path, f"{nombre}_SCL.tif", scl)
    it = ItemConRaster(**assets)
    it.datetime = dt
    it.id = nombre
    it.properties = {"eo:cloud_cover": cloud_cover}
    return it


def _bbox():
    return bbox_lonlat(LADO, LADO)


# --------------------------------------------------------------------------- #
# Búsqueda de ventana / degradación
# --------------------------------------------------------------------------- #
def test_sin_escenas_devuelve_none(instalar_catalogo, capsys):
    instalar_catalogo([])

    result = optical_layer.build_optical_water_layer({}, _bbox(), START, END)

    assert result is None
    assert "sin escenas" in capsys.readouterr().out


def test_escena_totalmente_nublada_se_saltea(instalar_catalogo, tmp_path, capsys):
    it = _item("S2_nube", utc(2026, 7, 16), tmp_path,
              parche_agua=(slice(5, 15), slice(5, 15)),
              parche_nube=(slice(0, LADO), slice(0, LADO)))  # todo nublado
    instalar_catalogo([it])

    result = optical_layer.build_optical_water_layer({}, _bbox(), START, END)

    assert result is None
    salida = capsys.readouterr().out
    assert "sin píxeles despejados" in salida


def test_escena_rota_se_saltea_y_no_rompe_la_corrida(
        instalar_catalogo, tmp_path, capsys):
    ok = _item("S2_ok", utc(2026, 7, 16), tmp_path,
              parche_agua=(slice(5, 15), slice(5, 15)))
    rota = _item("S2_rota", utc(2026, 7, 18), tmp_path, bandas_rotas=True)
    instalar_catalogo([ok, rota])

    result = optical_layer.build_optical_water_layer({}, _bbox(), START, END)

    assert result is not None
    assert result.skipped == ["S2_rota"]
    assert [a.item_id for a in result.acquisitions] == ["S2_ok"]
    assert "no pude usar la escena S2_rota" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Detección AWEI + máscara SCL
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("variant", ["nsh", "sh", "both"])
def test_detecta_agua_y_no_tierra_seca(instalar_catalogo, tmp_path, variant):
    it = _item("S2_a", utc(2026, 7, 16), tmp_path,
              parche_agua=(slice(5, 15), slice(5, 15)))
    instalar_catalogo([it])

    result = optical_layer.build_optical_water_layer(
        {}, _bbox(), START, END, awei_variant=variant)

    assert result is not None
    assert result.flood[5:15, 5:15].all()
    assert not result.flood[0:3, 0:3].any()
    assert result.acquisitions[0].awei_variant == variant


def test_nube_sobre_el_parche_de_agua_no_cuenta(instalar_catalogo, tmp_path):
    """Reflectancia de agua, pero SCL dice nube: no debe votar agua — es
    justo lo que evita que una escena nublada reporte falsos positivos."""
    it = _item("S2_a", utc(2026, 7, 16), tmp_path,
              parche_agua=(slice(5, 15), slice(5, 15)),
              parche_nube=(slice(5, 15), slice(5, 15)))
    instalar_catalogo([it])

    result = optical_layer.build_optical_water_layer({}, _bbox(), START, END)

    # El resto de la grilla es tierra seca y despejada, así que la escena
    # sí se procesa (no hay razón para saltearla) — solo que el único
    # parche con reflectancia de agua queda tapado por la nube.
    assert result is not None
    assert not result.flood.any()


def test_dos_escenas_se_unen(instalar_catalogo, tmp_path):
    a = _item("S2_a", utc(2026, 7, 16), tmp_path,
             parche_agua=(slice(2, 6), slice(2, 6)))
    b = _item("S2_b", utc(2026, 7, 19), tmp_path,
             parche_agua=(slice(14, 18), slice(14, 18)))
    instalar_catalogo([b, a])  # sin orden: debe ordenar por fecha igual

    result = optical_layer.build_optical_water_layer({}, _bbox(), START, END)

    assert result is not None
    assert result.flood[2:6, 2:6].all()
    assert result.flood[14:18, 14:18].all()
    assert [acq.item_id for acq in result.acquisitions] == ["S2_a", "S2_b"]


def test_clear_pct_y_cloud_cover_quedan_en_acquisitions(
        instalar_catalogo, tmp_path):
    it = _item("S2_a", utc(2026, 7, 16), tmp_path,
              parche_agua=(slice(5, 15), slice(5, 15)),
              parche_nube=(slice(0, 5), slice(0, 20)),  # 5 filas nubladas de 20
              cloud_cover=42.5)
    instalar_catalogo([it])

    result = optical_layer.build_optical_water_layer({}, _bbox(), START, END)

    acq = result.acquisitions[0]
    assert acq.cloud_cover_pct == 42.5
    assert acq.clear_pct == pytest.approx(75.0, abs=0.5)  # 15/20 filas despejadas
