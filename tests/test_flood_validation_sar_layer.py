"""sar_layer.py: unión de escenas Sentinel-1 dentro de la ventana. Marcado
`raster`, sin red — mismo truco que test_main.py: se sustituye solo
`stac_catalog` por un catálogo que sirve GeoTIFF sintéticos, y el resto del
pipeline (lectura, dB, Otsu, máscaras, detección, unión, escritura) corre de
verdad.

`build_real_flood_layer` llama a `permanent_water_mask`/`slope_mask`, que
están definidas en flood_monitor.py y ahí resuelven `stac_catalog()` contra
el nombre en SU propio módulo — parchear solo `sar_layer.stac_catalog` no
las alcanza (la misma lección que ya deja conftest.py sobre
`list_s1_items`). Por eso el fake se instala en los dos módulos a la vez.
"""

from __future__ import annotations

import pytest

pytest.importorskip("rioxarray")
pytest.importorskip("geopandas")

import flood_monitor  # noqa: E402
from flood_validation import sar_layer  # noqa: E402
from helpers import FakeItem, utc  # noqa: E402
from raster_helpers import ItemConRaster, bbox_lonlat, geotiff  # noqa: E402

pytestmark = pytest.mark.raster

LADO = 40
POTENCIA_SUELO = 0.16    # ~ -8 dB: terreno seco
POTENCIA_AGUA = 0.005    # ~ -23 dB: reflector especular
START = utc(2026, 7, 15)
END = utc(2026, 7, 22, 23, 59, 59)


def escena_vh(parche: tuple[slice, slice] | None) -> "np.ndarray":
    import numpy as np

    vh = np.full((LADO, LADO), POTENCIA_SUELO, dtype="float32")
    if parche is not None:
        vh[parche] = POTENCIA_AGUA
    return vh


class CatalogoFalso:
    """Como el de test_main.py, pero con una LISTA de escenas Sentinel-1 —
    acá la búsqueda de ventana devuelve todas, no una sola."""

    def __init__(self, escenas, jrc=None, dem=None):
        self.escenas, self.jrc, self.dem = escenas, jrc, dem
        self.consultas = []

    def search(self, **kwargs):
        coleccion = kwargs["collections"][0]
        self.consultas.append(coleccion)
        if coleccion == "sentinel-1-rtc":
            items = self.escenas
        elif coleccion == "jrc-gsw":
            items = [self.jrc] if self.jrc else []
        else:
            items = [self.dem] if self.dem else []
        return type("S", (), {"item_collection": lambda _self: list(items)})()


@pytest.fixture
def instalar_catalogo(monkeypatch):
    def hacerlo(escenas, jrc=None, dem=None):
        catalogo = CatalogoFalso(escenas, jrc, dem)
        # permanent_water_mask/slope_mask viven en flood_monitor.py y
        # resuelven stac_catalog() en SU namespace; search_s1_window vive en
        # sar_layer.py e importó su propio nombre. Los dos hay que parchear.
        monkeypatch.setattr(flood_monitor, "stac_catalog", lambda: catalogo)
        monkeypatch.setattr(sar_layer, "stac_catalog", lambda: catalogo)
        return catalogo
    return hacerlo


def _item(nombre, dt, parche, tmp_path, x0=None):
    kwargs = {} if x0 is None else {"x0": x0}
    it = ItemConRaster(vh=geotiff(tmp_path, f"{nombre}.tif",
                                  escena_vh(parche), **kwargs))
    it.datetime = dt
    it.id = nombre
    it.properties = {"sat:relative_orbit": 156, "sat:orbit_state": "descending"}
    return it


# --------------------------------------------------------------------------- #
# Búsqueda de ventana
# --------------------------------------------------------------------------- #
def test_sin_escenas_devuelve_none(instalar_catalogo, capsys):
    instalar_catalogo([])
    xmin, ymin, xmax, ymax = bbox_lonlat(LADO, LADO)

    result = sar_layer.build_real_flood_layer(
        {}, (xmin, ymin, xmax, ymax), START, END)

    assert result is None
    assert "sin escenas" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Unión de varias escenas
# --------------------------------------------------------------------------- #
def test_la_union_combina_parches_de_escenas_distintas(
        instalar_catalogo, tmp_path):
    """Dos escenas con agua en lugares distintos: ninguna por separado cubre
    ambos parches, la unión sí — es el punto entero de la Fase 2 frente a
    elegir una sola imagen."""
    a = _item("S1_a", utc(2026, 7, 16, 10, 2), (slice(5, 15), slice(5, 15)),
             tmp_path)
    b = _item("S1_b", utc(2026, 7, 19, 10, 2), (slice(25, 35), slice(25, 35)),
             tmp_path)
    instalar_catalogo([b, a])  # sin orden: build_real_flood_layer debe ordenar

    xmin, ymin, xmax, ymax = bbox_lonlat(LADO, LADO)
    result = sar_layer.build_real_flood_layer(
        {}, (xmin, ymin, xmax, ymax), START, END)

    assert result is not None
    assert result.flood[5:15, 5:15].all()
    assert result.flood[25:35, 25:35].all()
    assert not result.flood[35:40, 0:5].any()   # resto seco
    assert [a.item_id for a in result.acquisitions] == ["S1_a", "S1_b"]
    assert result.skipped == []


def test_grillas_desalineadas_se_reproyectan_a_la_de_referencia(
        instalar_catalogo, tmp_path):
    """La segunda escena viene con un origen corrido (simula una órbita
    distinta): si no se reproyectara contra la referencia, el parche
    aparecería desplazado o el array ni siquiera alinearía para el OR."""
    a = _item("S1_a", utc(2026, 7, 16, 10, 2), (slice(5, 15), slice(5, 15)),
             tmp_path)
    # 60 m de corrimiento = 2 px a 30 m/px.
    from raster_helpers import X0
    b = _item("S1_b", utc(2026, 7, 19, 10, 2), (slice(25, 35), slice(25, 35)),
             tmp_path, x0=X0 + 60.0)
    instalar_catalogo([a, b])

    xmin, ymin, xmax, ymax = bbox_lonlat(LADO, LADO)
    result = sar_layer.build_real_flood_layer(
        {}, (xmin, ymin, xmax, ymax), START, END)

    assert result is not None
    # Sigue viendo los dos parches sobre la grilla de referencia (la de A),
    # con margen de un par de píxeles por el remuestreo bilineal del borde.
    assert result.flood[7:13, 7:13].all()
    assert result.flood[27:33, 27:33].all()


def test_una_escena_que_falla_se_saltea_y_las_demas_siguen(
        instalar_catalogo, tmp_path, capsys):
    a = _item("S1_ok", utc(2026, 7, 16, 10, 2), (slice(5, 15), slice(5, 15)),
             tmp_path)
    rota = ItemConRaster(vh="/no/existe/vh.tif")
    rota.datetime = utc(2026, 7, 18, 10, 2)
    rota.id = "S1_rota"
    rota.properties = {"sat:relative_orbit": 156, "sat:orbit_state": "descending"}
    instalar_catalogo([a, rota])

    xmin, ymin, xmax, ymax = bbox_lonlat(LADO, LADO)
    result = sar_layer.build_real_flood_layer(
        {}, (xmin, ymin, xmax, ymax), START, END)

    assert result is not None
    assert result.skipped == ["S1_rota"]
    assert [a.item_id for a in result.acquisitions] == ["S1_ok"]
    assert "no pude usar la escena S1_rota" in capsys.readouterr().out


def test_si_todas_las_escenas_fallan_devuelve_none(instalar_catalogo, capsys):
    rota = ItemConRaster(vh="/no/existe/vh.tif")
    rota.datetime = utc(2026, 7, 18, 10, 2)
    rota.id = "S1_rota"
    rota.properties = {"sat:relative_orbit": 156, "sat:orbit_state": "descending"}
    instalar_catalogo([rota])

    xmin, ymin, xmax, ymax = bbox_lonlat(LADO, LADO)
    result = sar_layer.build_real_flood_layer(
        {}, (xmin, ymin, xmax, ymax), START, END)

    assert result is None
    assert "ninguna escena de la ventana se pudo leer" in capsys.readouterr().out


def test_agua_permanente_se_calcula_una_sola_vez_no_por_escena(
        instalar_catalogo, tmp_path):
    """JRC/DEM son propiedades del terreno: buscarlos por escena sería
    trabajo repetido e innecesario. Con dos escenas debe haber una sola
    consulta a jrc-gsw."""
    a = _item("S1_a", utc(2026, 7, 16, 10, 2), (slice(5, 15), slice(5, 15)),
             tmp_path)
    b = _item("S1_b", utc(2026, 7, 19, 10, 2), (slice(25, 35), slice(25, 35)),
             tmp_path)
    catalogo = instalar_catalogo([a, b])

    xmin, ymin, xmax, ymax = bbox_lonlat(LADO, LADO)
    sar_layer.build_real_flood_layer(
        {}, (xmin, ymin, xmax, ymax), START, END)

    assert catalogo.consultas.count("jrc-gsw") == 1
    assert catalogo.consultas.count("cop-dem-glo-30") == 1
    assert catalogo.consultas.count("sentinel-1-rtc") == 1  # una sola búsqueda de ventana

# La escritura de GeoTIFF/GeoJSON vive en outputs.py (compartida con
# optical_layer.py) — ver test_flood_validation_outputs.py.
