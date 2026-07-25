"""Resolución del AOI: los tres modos de entrada. Sin red.

Es la primera etapa del pipeline y la que ningún test posterior vigila: si
`load_aoi` devuelve el recuadro equivocado, todo lo demás sigue en verde y el
mapa sale perfectamente calculado sobre el lugar equivocado.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import shape

import flood_monitor
from flood_monitor import geocode_place, load_aoi

# Recuadro de referencia sobre Tongoy, en lon/lat.
BBOX = (-71.5449, -30.3021, -71.4409, -30.2123)
POLIGONO = {
    "type": "Polygon",
    "coordinates": [[[-71.54, -30.30], [-71.44, -30.30],
                     [-71.44, -30.21], [-71.54, -30.21], [-71.54, -30.30]]],
}


def args(**kw):
    base = {"aoi": None, "bbox": None, "place": None,
            "region": flood_monitor.DEFAULT_REGION, "buffer_km": 5.0}
    return argparse.Namespace(**{**base, **kw})


def escribir(tmp_path, nombre, contenido):
    ruta = tmp_path / nombre
    ruta.write_text(json.dumps(contenido))
    return ruta


# --------------------------------------------------------------------------- #
# --bbox
# --------------------------------------------------------------------------- #
def test_bbox_se_devuelve_tal_cual():
    """El orden es xmin ymin xmax ymax; permutarlo daría un AOI vacío."""
    geom, bbox = load_aoi(args(bbox=list(BBOX)))

    assert bbox == BBOX
    assert shape(geom).bounds == BBOX


# --------------------------------------------------------------------------- #
# --aoi (GeoJSON)
# --------------------------------------------------------------------------- #
def test_las_tres_formas_de_geojson_dan_lo_mismo(tmp_path):
    """geojson.io exporta FeatureCollection, otras herramientas no.

    Las tres envolturas deben resolver a la misma geometría; si no, el mismo
    polígono daría AOIs distintos según de dónde salió el archivo.
    """
    coleccion = escribir(tmp_path, "fc.geojson", {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {},
                      "geometry": POLIGONO}]})
    feature = escribir(tmp_path, "f.geojson", {
        "type": "Feature", "properties": {}, "geometry": POLIGONO})
    pelada = escribir(tmp_path, "g.geojson", POLIGONO)

    resultados = [load_aoi(args(aoi=r))[1] for r in (coleccion, feature, pelada)]

    assert resultados[0] == resultados[1] == resultados[2]
    assert resultados[0] == shape(POLIGONO).bounds


def test_una_coleccion_de_varios_features_usa_solo_el_primero(tmp_path):
    """Limitación conocida, acá documentada: `features[0]` y el resto se
    descarta en silencio.

    Si dibujás dos polígonos en geojson.io, el segundo no se procesa y nada
    lo avisa. Los ejemplos de `aoi/` tienen un solo feature, así que hoy no
    molesta; este test está para que el día que cambie sea una decisión y no
    una sorpresa.
    """
    lejos = {"type": "Polygon",
             "coordinates": [[[-70.0, -33.0], [-69.9, -33.0],
                              [-69.9, -32.9], [-70.0, -32.9], [-70.0, -33.0]]]}
    ruta = escribir(tmp_path, "dos.geojson", {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": POLIGONO},
                     {"type": "Feature", "properties": {}, "geometry": lejos}]})

    _, bbox = load_aoi(args(aoi=ruta))

    assert bbox == shape(POLIGONO).bounds


@pytest.mark.parametrize(
    "ruta", sorted((Path(__file__).parent.parent / "aoi").glob("*.geojson")),
    ids=lambda p: p.stem[:40])
def test_los_aoi_de_ejemplo_del_repo_cargan(ruta):
    """Los GeoJSON de `aoi/` son documentación ejecutable: si alguno se
    corrompe o cambia de formato, esto lo caza.

    El bbox tiene que caer dentro de Chile continental; un archivo con las
    coordenadas invertidas (lat, lon) se iría al Índico y fallaría acá.
    """
    geom, bbox = load_aoi(args(aoi=ruta))

    xmin, ymin, xmax, ymax = bbox
    assert -76 < xmin < xmax < -66, "longitud fuera de Chile"
    assert -56 < ymin < ymax < -17, "latitud fuera de Chile"
    assert shape(geom).area > 0


# --------------------------------------------------------------------------- #
# --place (geocodificación)
# --------------------------------------------------------------------------- #
class RespuestaFalsa:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture
def nominatim(monkeypatch):
    """Sustituye la llamada HTTP a Nominatim por una respuesta fija."""
    import requests

    def install(lat, lon, nombre="Lugar de prueba"):
        registro = {}

        def fake_get(url, **kwargs):
            registro["url"] = url
            registro["params"] = kwargs.get("params")
            return RespuestaFalsa([{"lat": str(lat), "lon": str(lon),
                                    "display_name": nombre}])

        monkeypatch.setattr(requests, "get", fake_get)
        return registro

    return install


def test_el_buffer_se_mide_desde_el_centro_no_desde_el_limite(nominatim):
    """Se usa el punto central del resultado, no su boundingbox.

    Para una comuna, Nominatim devuelve el límite administrativo entero
    (~100 km de lado); tomarlo daría un AOI descomunal. Con --buffer-km 5 el
    lado debe ser 10 km, no el tamaño de la comuna.
    """
    nominatim(lat=-30.2572, lon=-71.4929)

    _, (xmin, ymin, xmax, ymax) = geocode_place("Tongoy", "Chile", 5.0)

    alto_km = (ymax - ymin) * 111.32
    assert alto_km == pytest.approx(10.0, abs=0.1)


def test_el_buffer_en_longitud_se_corrige_por_latitud(nominatim):
    """Un grado de longitud mide menos cuanto más lejos del ecuador.

    Sin dividir por cos(lat), el AOI saldría angosto: a -30° sería un 14%
    más chico en el eje este-oeste que lo pedido.
    """
    nominatim(lat=-30.2572, lon=-71.4929)
    _, (xmin, _, xmax, _) = geocode_place("Tongoy", "Chile", 5.0)

    ancho_km = (xmax - xmin) * 111.32 * np.cos(np.radians(-30.2572))
    assert ancho_km == pytest.approx(10.0, abs=0.1)


def test_cerca_del_polo_el_ancho_no_se_dispara(nominatim):
    """La guarda `max(cos(lat), 0.01)` evita dividir por ~0.

    Sin ella, un AOI polar tendería a un ancho infinito en longitud.
    """
    nominatim(lat=89.999, lon=0.0)

    _, (xmin, _, xmax, _) = geocode_place("Polo", "", 5.0)

    assert np.isfinite(xmax - xmin)
    assert (xmax - xmin) <= 2 * 5.0 / (111.32 * 0.01) + 1e-6


def test_sin_resultados_de_nominatim_se_corta_con_mensaje(monkeypatch):
    """Mejor cortar que geocodificar cualquier cosa: seguir con un AOI
    inventado produciría un mapa de un lugar que nadie pidió."""
    import requests
    monkeypatch.setattr(requests, "get", lambda url, **kw: RespuestaFalsa([]))

    with pytest.raises(SystemExit) as exc:
        geocode_place("Ciudad Inexistente", "Chile", 5.0)

    assert "Ciudad Inexistente" in str(exc.value)


def test_la_consulta_incluye_el_contexto_de_region(nominatim):
    """--region es lo que desambigua: hay muchos "San José"."""
    registro = nominatim(lat=-30.0, lon=-71.0)

    geocode_place("Tongoy", "Región de Coquimbo, Chile", 5.0)

    assert registro["params"]["q"] == "Tongoy, Región de Coquimbo, Chile"
