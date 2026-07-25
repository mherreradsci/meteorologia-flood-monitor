"""Las dos máscaras que descartan falsos positivos. Sin red, con GDAL.

`permanent_water_mask` y `slope_mask` son casi todo orquestación de E/S, pero
esconden dos decisiones numéricas que deciden el mapa: el umbral de ocurrencia
JRC (más su dilatación) y el cálculo de pendiente sobre el DEM.

En vez de mockear rioxarray, estos tests escriben GeoTIFF sintéticos a disco y
dejan correr el código real: `clip_box`, `reproject_match`, el gradiente y la
dilatación. Solo se sustituye la búsqueda STAC, así que no hay red y el
resultado es determinista.

Marcados `raster` porque necesitan rioxarray (rueda con GDAL embebido, sin
apt). El job mínimo de CI no los corre: ver .github/workflows/tests.yml.
"""

from __future__ import annotations

import numpy as np
import pytest

# Todo el módulo depende de GDAL; sin él se saltea entero en vez de fallar.
pytest.importorskip("rioxarray")

from flood_monitor import permanent_water_mask, slope_mask  # noqa: E402
from raster_helpers import (RES, X0, ItemConRaster, bbox_lonlat,  # noqa: E402
                            geotiff, grilla)

pytestmark = pytest.mark.raster

GEOM = {"type": "Point", "coordinates": [-71.49, -30.25]}


# --------------------------------------------------------------------------- #
# permanent_water_mask
# --------------------------------------------------------------------------- #
def test_el_umbral_de_ocurrencia_es_estricto(tmp_path, fake_stac):
    """JRC guarda "% del tiempo con agua"; el criterio es > 50, no >= 50.

    Un píxel con ocurrencia exactamente 50 está en agua la mitad del tiempo:
    no es agua permanente y no debe enmascararse.
    """
    plantilla = grilla(np.zeros((20, 20)))

    fake_stac([ItemConRaster(occurrence=geotiff(tmp_path, "j50.tif",
                                                np.full((20, 20), 50.0)))])
    justo_en_el_borde = permanent_water_mask(GEOM, bbox_lonlat(20, 20), plantilla)

    fake_stac([ItemConRaster(occurrence=geotiff(tmp_path, "j51.tif",
                                                np.full((20, 20), 51.0)))])
    apenas_encima = permanent_water_mask(GEOM, bbox_lonlat(20, 20), plantilla)

    assert not justo_en_el_borde.any()
    assert apenas_encima.all()


def test_un_pixel_de_agua_se_dilata_a_su_entorno(tmp_path, fake_stac):
    """La dilatación con disk(3) absorbe el desalineado JRC/S1 en la costa.

    Un píxel aislado pasa a 29 (el área del disco de radio 3), o sea ~90 m
    de margen a 30 m/px. Si alguien cambia el radio, este número se mueve.
    """
    occ = np.zeros((30, 30))
    occ[15, 15] = 100.0
    fake_stac([ItemConRaster(occurrence=geotiff(tmp_path, "punto.tif", occ))])

    mask = permanent_water_mask(GEOM, bbox_lonlat(30, 30), grilla(np.zeros((30, 30))))

    assert mask.sum() == 29
    assert mask[15, 15]


def test_varios_tiles_se_fusionan(tmp_path, fake_stac):
    """Un AOI puede caer entre dos tiles JRC: se combinan con merge_arrays."""
    izq = geotiff(tmp_path, "izq.tif", np.full((20, 20), 100.0))
    der = geotiff(tmp_path, "der.tif", np.zeros((20, 20)), x0=X0 + 20 * RES)
    fake_stac([ItemConRaster(occurrence=izq), ItemConRaster(occurrence=der)])

    mask = permanent_water_mask(GEOM, bbox_lonlat(20, 40),
                                grilla(np.zeros((20, 40))))

    assert mask[:, :20].all()      # el tile de agua entra entero
    assert not mask[:, 25:].any()  # el seco también (salvo el borde dilatado)


def test_sin_tiles_jrc_devuelve_none(fake_stac):
    fake_stac([])

    assert permanent_water_mask(GEOM, bbox_lonlat(20, 20),
                                grilla(np.zeros((20, 20)))) is None


def test_el_agua_permanente_falla_suave(monkeypatch, capsys):
    """Sin JRC el mapa sale peor, no sale mal: la corrida sigue.

    Es lo contrario de la búsqueda de imágenes, que sí aborta — sin escena no
    hay nada que calcular, sin máscara sí.
    """
    import flood_monitor

    def explota():
        raise RuntimeError("JRC caído")

    monkeypatch.setattr(flood_monitor, "stac_catalog", explota)

    resultado = permanent_water_mask(GEOM, bbox_lonlat(20, 20),
                                     grilla(np.zeros((20, 20))))

    assert resultado is None
    assert "JRC caído" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# slope_mask
# --------------------------------------------------------------------------- #
def dem_en_rampa(alto: int, ancho: int) -> np.ndarray:
    """DEM que sube 10 m por píxel de 30 m.

    La pendiente es analítica y uniforme: atan(10/30) = 18.4349°, incluso en
    los bordes (np.gradient es exacto sobre una rampa lineal).
    """
    return (np.arange(ancho, dtype="float32") * 10.0)[None, :].repeat(alto, 0)


def test_max_slope_cero_desactiva_la_mascara(fake_stac):
    """`--max-slope 0` debe cortar antes de buscar nada."""
    registro = fake_stac([])

    assert slope_mask(GEOM, bbox_lonlat(20, 20), grilla(np.zeros((20, 20))), 0) is None
    assert "kwargs" not in registro  # ni siquiera se consultó el catálogo


def test_terreno_llano_no_se_enmascara(tmp_path, fake_stac):
    fake_stac([ItemConRaster(data=geotiff(tmp_path, "llano.tif",
                                          np.full((20, 20), 100.0)))])

    mask = slope_mask(GEOM, bbox_lonlat(20, 20), grilla(np.zeros((20, 20))), 5.0)

    assert not mask.any()


def test_una_rampa_empinada_se_descarta_entera(tmp_path, fake_stac):
    """18.43° supera de sobra los 5° por defecto: es sombra de relieve."""
    fake_stac([ItemConRaster(data=geotiff(tmp_path, "rampa.tif",
                                          dem_en_rampa(20, 20)))])

    mask = slope_mask(GEOM, bbox_lonlat(20, 20), grilla(np.zeros((20, 20))), 5.0)

    assert mask.all()


@pytest.mark.parametrize("max_slope, esperado", [(18.0, True), (19.0, False)])
def test_el_umbral_discrimina_alrededor_del_valor_analitico(
        tmp_path, fake_stac, max_slope, esperado):
    """La pendiente de la rampa es exactamente atan(1/3) = 18.4349°.

    Con --max-slope 18 se descarta y con 19 no: fija que el cálculo sea el
    gradiente en metros sobre la grilla UTM, y no grados ni píxeles.
    """
    fake_stac([ItemConRaster(data=geotiff(tmp_path, f"r{max_slope}.tif",
                                          dem_en_rampa(20, 20)))])

    mask = slope_mask(GEOM, bbox_lonlat(20, 20), grilla(np.zeros((20, 20))),
                      max_slope)

    assert mask.any() == esperado


def test_sin_tiles_de_dem_devuelve_none(fake_stac):
    fake_stac([])

    assert slope_mask(GEOM, bbox_lonlat(20, 20),
                      grilla(np.zeros((20, 20))), 5.0) is None


def test_la_pendiente_falla_suave(monkeypatch, capsys):
    import flood_monitor

    def explota():
        raise RuntimeError("DEM inaccesible")

    monkeypatch.setattr(flood_monitor, "stac_catalog", explota)

    resultado = slope_mask(GEOM, bbox_lonlat(20, 20),
                           grilla(np.zeros((20, 20))), 5.0)

    assert resultado is None
    assert "DEM inaccesible" in capsys.readouterr().out
