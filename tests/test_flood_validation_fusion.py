"""fusion.py: combina capas de sensor en confianza + tiers, con
plausibilidad de terreno y agua estacional como exclusiones duras.
Marcado `raster` (necesita rioxarray para `template`/`reproject_match`),
sin red — terrain.py y seasonality.py se mockean directo, ya tienen sus
propios tests contra STAC (test_flood_validation_terrain.py,
test_flood_validation_seasonality.py).
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("rioxarray")

from flood_validation import fusion  # noqa: E402
from flood_validation.optical_layer import OpticalLayerResult  # noqa: E402
from flood_validation.sar_layer import SarLayerResult  # noqa: E402
from raster_helpers import X0, grilla  # noqa: E402

pytestmark = pytest.mark.raster

GEOM: dict = {}
BBOX = (0, 0, 1, 1)
PESOS = {"sentinel1": 0.5, "sentinel2": 0.35, "dynamic_world": 0.15}
TIERS = {"high": 0.75, "medium": 0.5, "low": 0.25}


@pytest.fixture(autouse=True)
def sin_terreno_ni_estacional(monkeypatch):
    """Por default ninguno de los dos filtros excluye nada; los tests que
    sí los necesitan los sobreescriben."""
    monkeypatch.setattr(fusion.terrain, "hand_implausible_mask",
                        lambda *a, **kw: None)
    monkeypatch.setattr(fusion.seasonality, "seasonal_water_mask",
                        lambda *a, **kw: None)


def _sar(flood, template):
    return SarLayerResult(flood=flood, template=template)


def _optico(flood, template):
    return OpticalLayerResult(flood=flood, template=template)


def test_ambos_sensores_de_acuerdo_da_confianza_alta():
    template = grilla(np.zeros((10, 10)))
    agua = np.zeros((10, 10), dtype=bool)
    agua[2:5, 2:5] = True

    resultado = fusion.fuse(_sar(agua, template), _optico(agua, template),
                            GEOM, BBOX, fusion_weights=PESOS,
                            confidence_tiers=TIERS)

    assert resultado is not None
    assert resultado.confidence[2:5, 2:5].min() == pytest.approx(1.0)
    assert (resultado.tier[2:5, 2:5] == fusion.TIER_ALTA).all()
    assert set(resultado.sensors_used) == {"sentinel1", "sentinel2"}


def test_un_sensor_ausente_no_baja_la_confianza():
    """Punto de diseño clave: sin Sentinel-2, Sentinel-1 vale por su propio
    peso solo — no se compara contra un total que incluye sensores sin
    dato para esta ventana."""
    template = grilla(np.zeros((10, 10)))
    agua = np.zeros((10, 10), dtype=bool)
    agua[2:5, 2:5] = True

    resultado = fusion.fuse(_sar(agua, template), None, GEOM, BBOX,
                            fusion_weights=PESOS, confidence_tiers=TIERS)

    assert resultado.confidence[2:5, 2:5].min() == pytest.approx(1.0)
    assert resultado.sensors_used == ["sentinel1"]


def test_sensores_en_desacuerdo_da_confianza_intermedia():
    template = grilla(np.zeros((10, 10)))
    agua_s1 = np.zeros((10, 10), dtype=bool)
    agua_s1[2:5, 2:5] = True
    agua_s2 = np.zeros((10, 10), dtype=bool)  # S2 no ve agua ahí

    resultado = fusion.fuse(_sar(agua_s1, template), _optico(agua_s2, template),
                            GEOM, BBOX, fusion_weights=PESOS,
                            confidence_tiers=TIERS)

    esperado = PESOS["sentinel1"] / (PESOS["sentinel1"] + PESOS["sentinel2"])
    assert resultado.confidence[3, 3] == pytest.approx(esperado)


def test_ningun_sensor_disponible_devuelve_none(capsys):
    resultado = fusion.fuse(None, None, GEOM, BBOX, fusion_weights=PESOS,
                            confidence_tiers=TIERS)

    assert resultado is None
    assert "ningún sensor tiene datos" in capsys.readouterr().out


def test_terreno_implausible_excluye_pese_a_que_los_sensores_dicen_agua(
        monkeypatch):
    template = grilla(np.zeros((10, 10)))
    agua = np.zeros((10, 10), dtype=bool)
    agua[2:5, 2:5] = True
    terreno = np.zeros((10, 10), dtype=bool)
    terreno[2:5, 2:5] = True
    monkeypatch.setattr(fusion.terrain, "hand_implausible_mask",
                        lambda *a, **kw: terreno)

    resultado = fusion.fuse(_sar(agua, template), _optico(agua, template),
                            GEOM, BBOX, fusion_weights=PESOS,
                            confidence_tiers=TIERS)

    assert resultado.confidence[2:5, 2:5].max() == 0.0
    assert resultado.tier[2:5, 2:5].max() == fusion.TIER_SECA
    assert resultado.terrain_excluded_px == 9


def test_agua_estacional_excluye_pese_a_que_los_sensores_dicen_agua(
        monkeypatch):
    template = grilla(np.zeros((10, 10)))
    agua = np.zeros((10, 10), dtype=bool)
    agua[2:5, 2:5] = True
    estacional = np.zeros((10, 10), dtype=bool)
    estacional[2:5, 2:5] = True
    monkeypatch.setattr(fusion.seasonality, "seasonal_water_mask",
                        lambda *a, **kw: estacional)

    resultado = fusion.fuse(_sar(agua, template), _optico(agua, template),
                            GEOM, BBOX, fusion_weights=PESOS,
                            confidence_tiers=TIERS)

    assert resultado.confidence[2:5, 2:5].max() == 0.0
    assert resultado.seasonal_excluded_px == 9


def test_peso_cero_no_hace_votar_a_ese_sensor():
    template = grilla(np.zeros((10, 10)))
    agua_s1 = np.zeros((10, 10), dtype=bool)
    agua_s2 = np.zeros((10, 10), dtype=bool)
    agua_s2[2:5, 2:5] = True  # solo S2 ve agua acá
    pesos = {**PESOS, "sentinel2": 0.0}

    resultado = fusion.fuse(_sar(agua_s1, template), _optico(agua_s2, template),
                            GEOM, BBOX, fusion_weights=pesos,
                            confidence_tiers=TIERS)

    assert resultado.confidence[2:5, 2:5].max() == 0.0
    assert resultado.sensors_used == ["sentinel1"]


def test_grillas_distintas_se_reproyectan_a_la_de_mas_peso():
    """S1 (más peso) y S2 en grillas UTM distintas: el resultado final
    tiene que quedar en la grilla de S1, con S2 reproyectado sobre ella."""
    template_s1 = grilla(np.zeros((20, 20)))
    agua_s1 = np.zeros((20, 20), dtype=bool)
    agua_s1[5:15, 5:15] = True

    template_s2 = grilla(np.zeros((20, 20)), x0=X0 + 60.0)  # corrida 2 px
    agua_s2 = np.zeros((20, 20), dtype=bool)
    agua_s2[5:15, 5:15] = True

    resultado = fusion.fuse(_sar(agua_s1, template_s1),
                            _optico(agua_s2, template_s2),
                            GEOM, BBOX, fusion_weights=PESOS,
                            confidence_tiers=TIERS)

    assert resultado.template is template_s1
    # El interior del parche, lejos del corrimiento de 2 px, sigue con
    # confianza alta pese al desalineado entre las dos grillas.
    assert resultado.confidence[8:12, 8:12].min() == pytest.approx(1.0, abs=0.01)
