"""Búsqueda contra la API real de Planetary Computer. Requiere internet.

    pytest -m network          # solo estos
    pytest -m "not network"    # el resto, sin red

Son deterministas pese a consultar un servicio remoto: el archivo de
Sentinel-1 es inmutable, así que "la última escena anterior al 2026-07-17
sobre Tongoy" es la misma hoy que dentro de un año. Esa es justamente la
propiedad que habilita --end-date-utc: sin él, un test solo podría preguntar
por "la más reciente", que cambia cada ~3 días.

No descargan rasters (eso son cientos de MB): se quedan en la búsqueda.
"""

from __future__ import annotations

import pytest

from conftest import TONGOY_GEOM
from flood_monitor import (parse_end_date, search_latest_s1,
                           search_reference_s1)

pytestmark = pytest.mark.network

# Escenas reales sobre el AOI de Tongoy, verificadas contra
# `list_s1_items.py --place Tongoy --end-date-utc 2026-07-17`.
ESCENA_16 = "S1D_IW_GRDH_1SDV_20260716T100235_20260716T100300_003697_0069D4_rtc"
ESCENA_12 = "S1C_IW_GRDH_1SDV_20260712T232811_20260712T232835_008516_010DC6_rtc"
ESCENA_10 = "S1C_IW_GRDH_1SDV_20260710T100242_20260710T100307_008479_010C90_rtc"


def _buscar(end_date, days=10):
    return search_latest_s1(TONGOY_GEOM, days, parse_end_date(end_date))


def test_corte_historico_devuelve_la_escena_anterior():
    item = _buscar("2026-07-17")

    assert item.id == ESCENA_16
    assert item.datetime.strftime("%Y-%m-%d") == "2026-07-16"


def test_el_corte_del_mismo_dia_incluye_esa_jornada():
    """Caso borde del 23:59:59, contra la API de verdad.

    La escena del 16 pasa a las 10:02 UTC: con un corte a las 00:00 se
    caería del rango y la validación de esa fecha quedaría sin imagen.
    """
    item = _buscar("2026-07-16", days=3)

    assert item.id == ESCENA_16


def test_corte_con_hora_explicita_recorta_el_dia():
    """A las 00:00 del 13, la escena del 12 a las 23:28 todavía entra."""
    item = _buscar("2026-07-13T00:00:00", days=5)

    assert item.id == ESCENA_12


def test_ventana_sin_cobertura_corta_la_corrida():
    """Entre el 16 a las 10:02 y el 17 a las 23:59 no pasó ningún satélite."""
    with pytest.raises(SystemExit):
        _buscar("2026-07-17", days=1)


def test_la_referencia_de_cambio_tambien_es_historica():
    """--change sobre una fecha pasada compara dos escenas pasadas.

    La referencia debe ser anterior a la principal y de la misma órbita
    relativa; si no, la caída de dB mide geometría, no agua.
    """
    actual = _buscar("2026-07-17")
    ref = search_reference_s1(TONGOY_GEOM, actual, ref_days=45)

    assert ref is not None
    assert ref.id == ESCENA_10
    assert ref.datetime < actual.datetime
    assert (ref.properties["sat:relative_orbit"]
            == actual.properties["sat:relative_orbit"])


def test_sin_end_date_sigue_siendo_la_mas_reciente():
    """No regresión: el modo NRT de siempre.

    No se puede afirmar un ID (cambia con cada pasada), pero sí el
    invariante: una escena reciente, dentro de la ventana pedida.
    """
    ahora = parse_end_date(None)
    item = search_latest_s1(TONGOY_GEOM, 20, ahora)

    edad = (ahora - item.datetime).days
    assert 0 <= edad <= 20
