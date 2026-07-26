"""`list_s1_items.search_recent_s1_items`: la búsqueda del script hermano.

A diferencia de `search_latest_s1` —que ensancha una ventana fija de días—,
esta usa la Sort extension de la STAC API (`sortby` + `max_items`) con un
intervalo abierto, para no tener que adivinar cuántos días mirar hacia atrás.
Estos tests fijan esa diferencia. Sin red.
"""

from __future__ import annotations

import pytest

import list_s1_items
from helpers import FakeItem, utc
from list_s1_items import print_items, search_recent_s1_items

GEOM = {"type": "Point", "coordinates": [-71.49, -30.25]}


def instalar(fake_stac, items):
    """El hermano importó `stac_catalog` a su propio espacio de nombres, así
    que hay que parchearlo ahí y no en flood_monitor."""
    return fake_stac(items, list_s1_items)


def test_sin_days_back_el_intervalo_queda_abierto(fake_stac):
    """`../{end}` = "todo lo anterior a esta fecha".

    Es lo que permite pedir los N más recientes sin saber si hay que mirar
    10 días atrás o 200.
    """
    registro = instalar(fake_stac, [FakeItem(utc(2026, 7, 16, 10, 2))])

    search_recent_s1_items(GEOM, n=5, end=utc(2026, 7, 17, 23, 59, 59),
                           days_back=None)

    assert registro["kwargs"]["datetime"] == "../2026-07-17T23:59:59Z"


def test_con_days_back_el_intervalo_se_acota(fake_stac):
    registro = instalar(fake_stac, [FakeItem(utc(2026, 7, 16, 10, 2))])

    search_recent_s1_items(GEOM, n=5, end=utc(2026, 7, 17, 23, 59, 59),
                           days_back=30)

    assert (registro["kwargs"]["datetime"]
            == "2026-06-17T23:59:59Z/2026-07-17T23:59:59Z")


def test_pide_orden_descendente_y_tope_del_lado_del_servidor(fake_stac):
    """`max_items` sin `sortby` traería N cualesquiera, no los N más nuevos."""
    registro = instalar(fake_stac, [FakeItem(utc(2026, 7, 16))])

    search_recent_s1_items(GEOM, n=7, end=utc(2026, 7, 17), days_back=None)

    assert registro["kwargs"]["max_items"] == 7
    assert registro["kwargs"]["sortby"] == [
        {"field": "properties.datetime", "direction": "desc"}]


def test_reordena_igual_del_lado_del_cliente(fake_stac):
    """Red de seguridad barata: si un servidor ignorara `sortby`, el orden
    del listado seguiría siendo correcto."""
    instalar(fake_stac, [FakeItem(utc(2026, 7, 10), "vieja"),
                         FakeItem(utc(2026, 7, 16), "nueva"),
                         FakeItem(utc(2026, 7, 12), "media")])

    items = search_recent_s1_items(GEOM, n=3, end=utc(2026, 7, 17),
                                   days_back=None)

    assert [i.id for i in items] == ["nueva", "media", "vieja"]


def test_un_item_sin_fecha_no_rompe_el_orden(fake_stac):
    """Mismo caso que en flood_monitor: STAC admite `datetime: null`.

    Ambos scripts comparten la constante EPOCH justamente para tratarlo
    igual; acá se verifica del lado del hermano.
    """
    sin_fecha = FakeItem(utc(2026, 7, 20), "sin_fecha")
    sin_fecha.datetime = None
    instalar(fake_stac, [sin_fecha, FakeItem(utc(2026, 7, 16), "con_fecha")])

    items = search_recent_s1_items(GEOM, n=2, end=utc(2026, 7, 17),
                                   days_back=None)

    assert items[0].id == "con_fecha"


def test_sin_resultados_corta_con_mensaje(fake_stac):
    instalar(fake_stac, [])

    with pytest.raises(SystemExit) as exc:
        search_recent_s1_items(GEOM, n=5, end=utc(2026, 7, 17), days_back=30)

    mensaje = str(exc.value)
    assert "2026-07-17" in mensaje
    assert "30 días" in mensaje


# --------------------------------------------------------------------------- #
# print_items — el listado es *la* salida de este script
# --------------------------------------------------------------------------- #
def test_lista_numerada_desde_uno_con_id_y_fecha(capsys):
    """El número de orden es lo que se usa para elegir un item a mano y
    pasárselo a flood_monitor como --end-date-utc."""
    items = [FakeItem(utc(2026, 7, 16, 10, 2, 47), "S1D_primera"),
             FakeItem(utc(2026, 7, 12, 23, 28, 23), "S1C_segunda")]

    print_items(items, utc(2026, 7, 17, 23, 59, 59))

    salida = capsys.readouterr().out
    assert "2 item(s)" in salida
    assert "2026-07-17 23:59 UTC" in salida     # la fecha de corte
    assert " 1. S1D_primera" in salida
    assert " 2. S1C_segunda" in salida
    assert "2026-07-16 10:02:47 UTC" in salida


def test_muestra_orbita_estado_y_plataforma(capsys):
    """Son los datos con los que se decide si dos escenas son comparables:
    la referencia de --change exige misma órbita relativa y mismo sentido."""
    item = FakeItem(utc(2026, 7, 16), "S1D", orbit=156, state="descending")
    item.properties["platform"] = "sentinel-1d"

    print_items([item], utc(2026, 7, 17))

    salida = capsys.readouterr().out
    assert "órbita relativa 156" in salida
    assert "descending" in salida
    assert "sentinel-1d" in salida


def test_las_propiedades_ausentes_salen_como_interrogacion(capsys):
    """Un item incompleto se lista igual: es una utilidad de inspección, no
    tiene por qué exigir metadatos completos."""
    item = FakeItem(utc(2026, 7, 16), "S1_pelado")
    item.properties = {}

    print_items([item], utc(2026, 7, 17))

    assert "órbita relativa ?, ?, ?" in capsys.readouterr().out


def test_un_item_sin_fecha_se_lista_en_vez_de_reventar(capsys):
    """STAC admite `datetime: null` y este script existe justamente para
    mirar qué hay: formatear None tiraba TypeError y se llevaba puesto el
    listado entero, incluidos los items que sí tenían fecha."""
    sin_fecha = FakeItem(utc(2026, 7, 20), "S1_sin_fecha")
    sin_fecha.datetime = None

    print_items([sin_fecha, FakeItem(utc(2026, 7, 16), "S1_con_fecha")],
                utc(2026, 7, 17))

    salida = capsys.readouterr().out
    assert "sin fecha declarada" in salida
    assert "S1_con_fecha" in salida
    assert "2026-07-16" in salida


def test_una_lista_vacia_no_rompe(capsys):
    print_items([], utc(2026, 7, 17))

    assert "0 item(s)" in capsys.readouterr().out
