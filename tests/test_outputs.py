"""`save_outputs`: los archivos que se lleva el usuario. Sin red, con GDAL.

Lo importante acá es la única transformación de coordenadas del pipeline: la
máscara se calcula en UTM y el GeoJSON se escribe en EPSG:4326. Si esa
reproyección estuviera mal, los polígonos caerían lejos del AOI y el resto de
la suite seguiría en verde — el mapa "funciona", solo que del lugar
equivocado.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

pytest.importorskip("rioxarray")
pytest.importorskip("geopandas")
matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")   # sin pantalla: hay que fijarlo antes de importar pyplot

from rasterio.warp import transform  # noqa: E402

import flood_monitor  # noqa: E402
from flood_monitor import save_outputs  # noqa: E402
from helpers import FakeItem, utc  # noqa: E402
from raster_helpers import CRS, RES, X0, Y0, bbox_lonlat, grilla  # noqa: E402

pytestmark = pytest.mark.raster

TAG = "prueba_Tongoy_20260716T100247Z_abc123_20260725T000000"
ESCENA = FakeItem(utc(2026, 7, 16, 10, 2, 47))


@pytest.fixture
def salida(tmp_path, monkeypatch):
    """`OUTPUT_DIR` es un global relativo al cwd; lo apuntamos a tmp_path.

    (De paso queda documentado por qué correr el script desde `src/` o desde
    la raíz manda los resultados a carpetas distintas.)
    """
    monkeypatch.setattr(flood_monitor, "OUTPUT_DIR", tmp_path)
    return tmp_path


def escena_con_parche(alto=20, ancho=20):
    """VH en dB más una máscara con un parche de 5x5 píxeles."""
    vh_db = grilla(np.full((alto, ancho), -8.0))
    flood = np.zeros((alto, ancho), dtype=bool)
    flood[5:10, 5:10] = True
    return vh_db, flood


def test_escribe_los_tres_archivos_con_el_tag(salida):
    """El tag es lo que hace trazable cada corrida; tiene que ir en todos."""
    vh_db, flood = escena_con_parche()

    save_outputs(vh_db, flood, ESCENA, bbox_lonlat(20, 20), TAG)

    assert (salida / f"flood_mask_{TAG}.tif").exists()
    assert (salida / f"flood_mask_{TAG}.geojson").exists()
    assert (salida / f"quicklook_{TAG}.png").exists()


def test_el_geojson_sale_en_lonlat_y_en_el_lugar_correcto(salida):
    """La máscara está en UTM 19S; el GeoJSON debe salir en EPSG:4326.

    El parche cae sobre Tongoy: si la reproyección se saltara o se invirtiera,
    las coordenadas se irían a cientos de km (o quedarían en metros, del orden
    de 260000), y esto lo detecta.
    """
    vh_db, flood = escena_con_parche()

    save_outputs(vh_db, flood, ESCENA, bbox_lonlat(20, 20), TAG)

    gj = json.loads((salida / f"flood_mask_{TAG}.geojson").read_text())
    xs, ys = zip(*gj["features"][0]["geometry"]["coordinates"][0])

    # Centro esperado del parche, convertido con una ruta independiente
    # (rasterio.warp) de la que usa el código (geopandas/pyproj).
    cx, cy = X0 + 7.5 * RES, Y0 - 7.5 * RES
    (lon_esp,), (lat_esp,) = transform(CRS, "EPSG:4326", [cx], [cy])

    assert np.mean(xs) == pytest.approx(lon_esp, abs=1e-3)
    assert np.mean(ys) == pytest.approx(lat_esp, abs=1e-3)
    assert -71.6 < np.mean(xs) < -71.4 and -30.4 < np.mean(ys) < -30.1


def test_cada_parche_separado_da_un_poligono(salida):
    """La vectorización no debe fusionar parches que no se tocan: cada uno es
    una zona anegada distinta en el GeoJSON."""
    vh_db = grilla(np.full((20, 20), -8.0))
    flood = np.zeros((20, 20), dtype=bool)
    flood[2:5, 2:5] = True
    flood[12:16, 12:16] = True    # bien separado del primero

    save_outputs(vh_db, flood, ESCENA, bbox_lonlat(20, 20), TAG)

    gj = json.loads((salida / f"flood_mask_{TAG}.geojson").read_text())
    assert len(gj["features"]) == 2


def test_sin_detecciones_no_escribe_geojson_pero_sí_el_resto(salida, capsys):
    """Una corrida sin anegamiento es un resultado válido, no un error: se
    avisa y se siguen escribiendo el ráster y el quicklook."""
    vh_db = grilla(np.full((20, 20), -8.0))
    sin_agua = np.zeros((20, 20), dtype=bool)

    save_outputs(vh_db, sin_agua, ESCENA, bbox_lonlat(20, 20), TAG)

    assert not (salida / f"flood_mask_{TAG}.geojson").exists()
    assert (salida / f"flood_mask_{TAG}.tif").exists()
    assert (salida / f"quicklook_{TAG}.png").exists()
    assert "Sin polígonos" in capsys.readouterr().out


def test_el_geotiff_es_binario_uint8(salida):
    """1 = anegado, 0 = no, 255 = sin dato. Es lo que documenta el README y
    lo que espera QGIS al abrirlo."""
    import rioxarray

    vh_db, flood = escena_con_parche()
    save_outputs(vh_db, flood, ESCENA, bbox_lonlat(20, 20), TAG)

    tif = rioxarray.open_rasterio(salida / f"flood_mask_{TAG}.tif")
    assert tif.dtype == "uint8"
    assert set(np.unique(tif.values)) <= {0, 1}
    assert int(tif.values.sum()) == 25   # el parche de 5x5


def test_con_referencia_el_quicklook_suma_un_panel(salida):
    """Con --change el quicklook trae 3 paneles (referencia, actual,
    detección) en vez de 2: se nota en el ancho de la imagen."""
    vh_db, flood = escena_con_parche()
    ref_db = grilla(np.full((20, 20), -6.0))
    ref_item = FakeItem(utc(2026, 7, 10, 10, 2))

    save_outputs(vh_db, flood, ESCENA, bbox_lonlat(20, 20), TAG)
    dos_paneles = matplotlib.image.imread(salida / f"quicklook_{TAG}.png").shape

    save_outputs(vh_db, flood, ESCENA, bbox_lonlat(20, 20), TAG,
                 ref_db=ref_db, ref_item=ref_item)
    tres_paneles = matplotlib.image.imread(salida / f"quicklook_{TAG}.png").shape

    assert tres_paneles[1] > dos_paneles[1]
    assert tres_paneles[1] / dos_paneles[1] == pytest.approx(1.5, abs=0.05)
