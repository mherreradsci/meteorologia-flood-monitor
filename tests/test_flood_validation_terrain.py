"""terrain.py: HAND (Height Above Nearest Drainage) desde Copernicus DEM
con pysheds. Marcado `raster`, sin red.

`_hand_from_padded_dem` se prueba directo, sin pasar por el fetch STAC: se
arma a mano una grilla ya "con margen" (HAND_PAD_PX de cada lado) y se
verifica que el recorte interior reproduzca la altura analítica de un
valle en V sintético — construcción y umbral de cauce verificados
empíricamente antes de escribir este test (ver la nota en terrain.py sobre
por qué reproyectar directo a la grilla del AOI, como hace slope_mask, no
alcanza acá: pysheds asigna dirección de flujo inválida a las celdas del
borde de la grilla analizada).
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("rioxarray")
pytest.importorskip("pysheds")

from flood_validation import terrain  # noqa: E402
from raster_helpers import RES, bbox_lonlat, grilla  # noqa: E402

pytestmark = pytest.mark.raster

GEOM = {"type": "Point", "coordinates": [-71.49, -30.25]}
CELL_KM2 = (RES * RES) / 1e6


def _valle_padded(alto_template: int, ancho_template: int,
                  paso_m: float = 10.0):
    """Valle en V ya sobre la grilla con margen (HAND_PAD_PX por lado en
    las dos dimensiones, igual que la grilla real que arma
    `_read_dem_padded`): elevación = |fila - centro| * paso_m, uniforme en
    columnas — cada columna es un problema de flujo 1D independiente
    (verificado empíricamente), así que el resultado no depende del ancho.
    El cauce cae en el medio del template, no del borde con margen.
    """
    pad = terrain.HAND_PAD_PX
    alto_padded = alto_template + 2 * pad
    ancho_padded = ancho_template + 2 * pad
    centro_padded = pad + alto_template // 2
    dem = (np.abs(np.arange(alto_padded) - centro_padded) *
          paso_m)[:, None].repeat(ancho_padded, 1).astype("float32")
    return grilla(dem)


def test_hand_interior_reproduce_la_altura_analitica_del_valle():
    """Cada columna es una cadena de flujo 1D independiente que converge en
    el centro: la acumulación en el cauce es la altura total de la
    columna (toda le drena), y la de sus vecinas inmediatas es solo la
    mitad de la cadena de cada lado — no altura_total - 1. Un umbral apenas
    debajo de la altura total aísla una sola fila de cauce por columna, en
    las `ancho_padded` columnas (todas comparten el mismo patrón de
    elevación por fila, incluido el margen)."""
    alto_template, ancho_template = 40, 20
    dem_padded = _valle_padded(alto_template, ancho_template)
    alto_padded = alto_template + 2 * terrain.HAND_PAD_PX
    ancho_padded = ancho_template + 2 * terrain.HAND_PAD_PX

    umbral_km2 = (alto_padded - 0.5) * CELL_KM2

    interior, n_streams = terrain._hand_from_padded_dem(
        dem_padded, (alto_template, ancho_template), umbral_km2)

    assert interior.shape == (alto_template, ancho_template)
    assert n_streams == ancho_padded  # una celda de cauce por columna (con margen)

    centro_template = alto_template // 2
    esperado = np.abs(np.arange(alto_template) - centro_template) * 10.0
    columna_interior = 10  # lejos de los bordes de columna, por las dudas
    np.testing.assert_allclose(interior[:, columna_interior], esperado,
                               atol=0.01)


def test_umbral_de_drenaje_mas_permisivo_agrega_mas_cauce():
    """Con un umbral bien más bajo, más filas de cada lado del valle
    califican como cauce."""
    alto_template, ancho_template = 40, 20
    dem_padded = _valle_padded(alto_template, ancho_template)
    alto_padded = alto_template + 2 * terrain.HAND_PAD_PX

    estricto = (alto_padded - 0.5) * CELL_KM2  # solo la fila central
    permisivo = 10.0 * CELL_KM2  # varias filas de cada lado

    _, n_estricto = terrain._hand_from_padded_dem(
        dem_padded, (alto_template, ancho_template), estricto)
    _, n_permisivo = terrain._hand_from_padded_dem(
        dem_padded, (alto_template, ancho_template), permisivo)

    assert n_permisivo > n_estricto


# --------------------------------------------------------------------------- #
# compute_hand — fetch STAC (fallo suave)
# --------------------------------------------------------------------------- #
def test_sin_tiles_de_dem_devuelve_none(fake_stac):
    fake_stac([], modulo=terrain)
    plantilla = grilla(np.zeros((20, 20)))

    assert terrain.compute_hand(GEOM, bbox_lonlat(20, 20), plantilla) is None


def test_compute_hand_falla_suave(monkeypatch, capsys):
    def explota():
        raise RuntimeError("DEM inaccesible")

    monkeypatch.setattr(terrain, "stac_catalog", explota)
    plantilla = grilla(np.zeros((20, 20)))

    resultado = terrain.compute_hand(GEOM, bbox_lonlat(20, 20), plantilla)

    assert resultado is None
    assert "DEM inaccesible" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# hand_implausible_mask
# --------------------------------------------------------------------------- #
def test_hand_threshold_m_cero_desactiva_el_filtro(monkeypatch):
    """Misma convención que --max-slope 0 en flood_monitor.py: ni siquiera
    intenta calcular HAND."""
    registro = {"llamado": False}

    def fake_compute_hand(*args, **kwargs):
        registro["llamado"] = True
        return np.zeros((5, 5), dtype="float32")

    monkeypatch.setattr(terrain, "compute_hand", fake_compute_hand)

    resultado = terrain.hand_implausible_mask(
        {}, (0, 0, 1, 1), None, hand_threshold_m=0)

    assert resultado is None
    assert registro["llamado"] is False


def test_mascara_excluye_por_encima_del_umbral_y_no_donde_falta_el_dato(
        monkeypatch):
    hand = np.array([[0.0, 10.0], [20.0, np.nan]], dtype="float32")
    monkeypatch.setattr(terrain, "compute_hand", lambda *a, **kw: hand)

    mask = terrain.hand_implausible_mask(
        {}, (0, 0, 1, 1), None, hand_threshold_m=15.0)

    assert mask.tolist() == [[False, False], [True, False]]  # NaN no se excluye


def test_mascara_none_si_compute_hand_no_pudo(monkeypatch):
    monkeypatch.setattr(terrain, "compute_hand", lambda *a, **kw: None)

    assert terrain.hand_implausible_mask({}, (0, 0, 1, 1), None) is None
