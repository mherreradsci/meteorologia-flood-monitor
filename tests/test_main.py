"""`main()`: el pegamento, ejercitado de punta a punta. Sin red, con GDAL.

Cada etapa ya tiene sus tests aislados; lo que acá se verifica es el cableado
entre ellas, que es lo único que ningún otro test puede ver: que el valor de
cada opción de la CLI llegue a la función que corresponde, y que las ramas de
`--change` hagan lo que dicen.

Para que sirva de algo, no se mockean las etapas: se sustituye solo el
catálogo STAC (la frontera de red) por uno que sirve GeoTIFF sintéticos, y el
pipeline real corre entero — lectura, dB, Otsu, máscaras, detección,
vectorización y escritura.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

pytest.importorskip("rioxarray")
pytest.importorskip("geopandas")
matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

import flood_monitor  # noqa: E402
import list_s1_items  # noqa: E402
from helpers import FakeItem, utc  # noqa: E402
from raster_helpers import ItemConRaster, bbox_lonlat, geotiff  # noqa: E402

pytestmark = pytest.mark.raster

LADO = 40                       # píxeles de la escena sintética
POTENCIA_SUELO = 0.16           # ~ -8 dB: terreno seco
POTENCIA_AGUA = 0.005           # ~ -23 dB: reflector especular
ESCENA_DT = utc(2026, 7, 16, 10, 2, 47)
REF_DT = utc(2026, 7, 10, 10, 2, 55)


def escena_vh(con_agua=True) -> np.ndarray:
    """Potencia lineal: fondo seco y un parche de agua de 10x10 px."""
    vh = np.full((LADO, LADO), POTENCIA_SUELO, dtype="float32")
    if con_agua:
        vh[10:20, 10:20] = POTENCIA_AGUA
    return vh


class CatalogoFalso:
    """Despacha por colección, como hace el Planetary Computer real.

    `main()` consulta cuatro veces: la escena, la referencia (solo con
    --change, reconocible porque lleva `query`), JRC y el DEM.
    """

    def __init__(self, escena, referencia=None, jrc=None, dem=None):
        self.escena, self.referencia = escena, referencia
        self.jrc, self.dem = jrc, dem
        self.consultas = []

    def search(self, **kwargs):
        coleccion = kwargs["collections"][0]
        self.consultas.append(coleccion)
        if coleccion == "sentinel-1-rtc":
            if "query" in kwargs:      # búsqueda de referencia
                items = [self.referencia] if self.referencia else []
            else:
                items = [self.escena]
        elif coleccion == "jrc-gsw":
            items = [self.jrc] if self.jrc else []
        else:                          # cop-dem-glo-30
            items = [self.dem] if self.dem else []
        return type("S", (), {"item_collection": lambda _self: list(items)})()


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    """Monta un pipeline completo sobre rásters sintéticos."""
    def montar(*, con_agua=True, con_referencia=False, jrc=None, dem=None):
        escena = ItemConRaster(vh=geotiff(tmp_path, "vh.tif",
                                          escena_vh(con_agua)))
        escena.datetime = ESCENA_DT
        escena.id = "S1D_escena"
        escena.properties = {"sat:relative_orbit": 156,
                             "sat:orbit_state": "descending"}

        referencia = None
        if con_referencia:
            # Referencia seca donde la escena tiene agua: se oscureció, así
            # que el criterio de cambio la conserva.
            referencia = ItemConRaster(vh=geotiff(tmp_path, "ref.tif",
                                                  escena_vh(con_agua=False)))
            referencia.datetime = REF_DT
            referencia.id = "S1C_referencia"
            referencia.properties = dict(escena.properties)

        catalogo = CatalogoFalso(escena, referencia,
                                 jrc=jrc(tmp_path) if jrc else None,
                                 dem=dem(tmp_path) if dem else None)
        monkeypatch.setattr(flood_monitor, "stac_catalog", lambda: catalogo)
        monkeypatch.setattr(flood_monitor, "OUTPUT_DIR", tmp_path)
        return catalogo
    return montar


def correr(monkeypatch, *opciones):
    """Invoca main() como si fuera la línea de comandos."""
    xmin, ymin, xmax, ymax = bbox_lonlat(LADO, LADO)
    monkeypatch.setattr("sys.argv", [
        "flood_monitor.py", "--bbox", str(xmin), str(ymin), str(xmax),
        str(ymax), *opciones])
    flood_monitor.main()


def correr_con_aoi(monkeypatch, tmp_path, nombre):
    """Igual que `correr`, pero entrando por --aoi: escribe un GeoJSON con
    el bbox de la escena sintética y lo pasa por la CLI.

    El archivo va a un subdirectorio para no mezclarse con las salidas, que
    `salidas()` busca en la raíz de tmp_path.
    """
    xmin, ymin, xmax, ymax = bbox_lonlat(LADO, LADO)
    carpeta = tmp_path / "aoi"
    carpeta.mkdir(exist_ok=True)
    ruta = carpeta / f"{nombre}.geojson"
    ruta.write_text(json.dumps({
        "type": "Polygon",
        "coordinates": [[[xmin, ymin], [xmax, ymin], [xmax, ymax],
                         [xmin, ymax], [xmin, ymin]]],
    }))
    monkeypatch.setattr("sys.argv", ["flood_monitor.py", "--aoi", str(ruta)])
    flood_monitor.main()


def espiar(monkeypatch, nombre):
    """Envuelve una etapa para registrar con qué la llamaron, sin
    reemplazarla: el pipeline sigue corriendo de verdad."""
    registro = {}
    original = getattr(flood_monitor, nombre)

    def envoltura(*args, **kwargs):
        registro["args"], registro["kwargs"] = args, kwargs
        return original(*args, **kwargs)

    monkeypatch.setattr(flood_monitor, nombre, envoltura)
    return registro


def salidas(tmp_path):
    return {p.suffix: p for p in tmp_path.iterdir() if p.name.count("_") > 2}


# --------------------------------------------------------------------------- #
# Corrida completa
# --------------------------------------------------------------------------- #
def test_una_corrida_completa_escribe_las_salidas(pipeline, monkeypatch,
                                                  tmp_path, capsys):
    """De la CLI al GeoJSON, con todas las etapas reales en el medio."""
    pipeline()

    correr(monkeypatch)

    archivos = salidas(tmp_path)
    assert {".tif", ".geojson", ".png"} <= set(archivos)
    # El tag lleva el timestamp de la escena, no el de hoy: es lo que hace
    # trazable una corrida histórica.
    assert "20260716T100247Z" in archivos[".tif"].name
    assert "[✓] Listo." in capsys.readouterr().out


def test_con_aoi_los_archivos_llevan_el_nombre_del_geojson(
        pipeline, monkeypatch, tmp_path):
    """El nombre del AOI tiene que sobrevivir hasta el disco.

    `build_run_tag` se prueba aparte, pero solo acá se ve que `args.aoi`
    llega hasta él (con --bbox el mismo AOI produce coordenadas, así que un
    cableado equivocado no rompería ninguna otra etapa).
    """
    pipeline()

    correr_con_aoi(monkeypatch, tmp_path,
                   "Chile-Region_de_Coquimbo-Tongoy-Playa")

    tif = salidas(tmp_path)[".tif"].name
    assert "aoi_Chile-Region_de_Coquimbo-Tongoy-Playa_" in tif
    assert "20260716T100247Z" in tif


def test_detecta_el_agua_y_no_el_suelo_seco(pipeline, monkeypatch, tmp_path):
    """El parche de 10x10 px de baja retrodispersión debe salir en el
    GeoJSON; un AOI enteramente seco no debe producir polígonos."""
    pipeline()
    correr(monkeypatch)
    assert (".geojson" in salidas(tmp_path))

    for p in tmp_path.iterdir():
        if p.is_file():
            p.unlink()

    pipeline(con_agua=False)
    correr(monkeypatch)
    assert ".geojson" not in salidas(tmp_path)


# --------------------------------------------------------------------------- #
# Cableado de las opciones
# --------------------------------------------------------------------------- #
def test_cada_opcion_llega_a_su_etapa(pipeline, monkeypatch):
    """El riesgo que ningún test aislado cubre: cruzar dos parámetros.

    Cada función se prueba por separado con valores propios, así que pasar
    --max-slope donde va --min-area-px no rompería nada más que el resultado.
    """
    pipeline()
    busqueda = espiar(monkeypatch, "search_latest_s1")
    umbral = espiar(monkeypatch, "water_threshold")
    pendiente = espiar(monkeypatch, "slope_mask")
    deteccion = espiar(monkeypatch, "detect_flood")

    correr(monkeypatch, "--days", "15", "--threshold", "-18.5",
           "--max-slope", "12", "--min-area-px", "7", "--change-delta", "4.5")

    assert busqueda["args"][1] == 15          # --days
    assert umbral["args"][1] == -18.5         # --threshold
    assert pendiente["args"][3] == 12.0       # --max-slope
    assert deteccion["args"][4] == 7          # --min-area-px
    assert deteccion["args"][6] == 4.5        # --change-delta


def test_end_date_se_traduce_a_la_fecha_de_corte(pipeline, monkeypatch):
    """La CLI transporta texto; el corte que llega a la búsqueda es el
    datetime ya resuelto al final del día en UTC."""
    pipeline()
    busqueda = espiar(monkeypatch, "search_latest_s1")

    correr(monkeypatch, "--end-date", "2026-07-17")

    corte = busqueda["args"][2]
    assert (corte.year, corte.month, corte.day) == (2026, 7, 17)
    assert (corte.hour, corte.minute, corte.second) == (23, 59, 59)


# --------------------------------------------------------------------------- #
# Las tres ramas de --change
# --------------------------------------------------------------------------- #
def test_sin_change_no_se_busca_referencia(pipeline, monkeypatch):
    """Sin la opción no hay segunda descarga: es la mitad del tiempo de una
    corrida."""
    catalogo = pipeline()

    correr(monkeypatch)

    assert catalogo.consultas.count("sentinel-1-rtc") == 1


def test_con_change_sin_referencia_sigue_solo_con_umbral(pipeline, monkeypatch,
                                                         tmp_path, capsys):
    """Que no haya una escena previa de la misma órbita no aborta la corrida:
    avisa y degrada a solo-umbral, como las máscaras."""
    pipeline(con_referencia=False)

    correr(monkeypatch, "--change")

    salida = capsys.readouterr().out
    assert "Sin referencia" in salida
    assert "[✓] Listo." in salida
    assert ".geojson" in salidas(tmp_path)


def test_con_change_y_referencia_el_quicklook_trae_tres_paneles(
        pipeline, monkeypatch, tmp_path):
    """Con referencia, `save_outputs` recibe ref_db y ref_item y dibuja el
    panel extra: es la señal visible de que la rama se recorrió entera."""
    pipeline(con_referencia=True)
    correr(monkeypatch, "--change")
    con_ref = matplotlib.image.imread(salidas(tmp_path)[".png"]).shape

    for p in tmp_path.iterdir():
        if p.is_file():
            p.unlink()

    pipeline(con_referencia=False)
    correr(monkeypatch)
    sin_ref = matplotlib.image.imread(salidas(tmp_path)[".png"]).shape

    assert con_ref[1] / sin_ref[1] == pytest.approx(1.5, abs=0.05)


# --------------------------------------------------------------------------- #
# Las máscaras, vistas desde el resultado final
# --------------------------------------------------------------------------- #
def test_el_agua_permanente_reduce_el_resultado(pipeline, monkeypatch,
                                                tmp_path):
    """Cruce de etapas: el JRC entra por una búsqueda distinta y tiene que
    terminar restando píxeles del GeoTIFF final."""
    import rioxarray

    def jrc_sobre_el_parche(tmp):
        occ = np.zeros((LADO, LADO), dtype="float32")
        occ[10:15, 10:20] = 100.0     # la mitad superior del agua es permanente
        return ItemConRaster(occurrence=geotiff(tmp, "jrc.tif", occ))

    pipeline()
    correr(monkeypatch)
    sin_jrc = int(rioxarray.open_rasterio(salidas(tmp_path)[".tif"]).values.sum())

    for p in tmp_path.iterdir():
        if p.is_file():
            p.unlink()

    pipeline(jrc=jrc_sobre_el_parche)
    correr(monkeypatch)
    con_jrc = int(rioxarray.open_rasterio(salidas(tmp_path)[".tif"]).values.sum())

    assert 0 < con_jrc < sin_jrc


# --------------------------------------------------------------------------- #
# main() del script hermano
# --------------------------------------------------------------------------- #
def test_main_del_listado_imprime_las_escenas(monkeypatch, capsys, fake_stac):
    """`list_s1_items` es de solo lectura: su salida *es* el listado."""
    fake_stac([FakeItem(ESCENA_DT, "S1D_escena")], list_s1_items)
    xmin, ymin, xmax, ymax = bbox_lonlat(LADO, LADO)
    monkeypatch.setattr("sys.argv", ["list_s1_items.py", "--bbox", str(xmin),
                                     str(ymin), str(xmax), str(ymax),
                                     "-n", "3", "--end-date", "2026-07-17"])

    list_s1_items.main()

    salida = capsys.readouterr().out
    assert "1 item(s)" in salida
    assert "S1D_escena" in salida
    assert "2026-07-16 10:02:47 UTC" in salida
