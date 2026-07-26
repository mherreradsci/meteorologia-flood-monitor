"""Ventana de búsqueda de escenas, con la API STAC mockeada. Sin red.

Estos tests fijan *qué se le pide* a Planetary Computer (el rango de fechas
exacto) y *cómo se elige* entre lo que devuelve. Los de red (test_search_live)
comprueban después que la API responde lo esperado a esas mismas preguntas.
"""

from __future__ import annotations

import pytest

from flood_monitor import search_latest_s1, search_reference_s1
from helpers import FakeItem, utc

GEOM = {"type": "Point", "coordinates": [-71.49, -30.25]}


def test_la_ventana_termina_en_el_corte_y_lleva_hora(fake_stac):
    """El rango es [corte - days, corte], con hora y no solo fecha.

    La hora importa: con `%Y-%m-%d` pelado, el 23:59:59 del final del día
    se perdería y con él las escenas de la fecha pedida.
    """
    corte = utc(2026, 7, 16, 23, 59, 59)
    registro = fake_stac([FakeItem(utc(2026, 7, 16, 10, 2))])

    search_latest_s1(GEOM, 10, corte)

    assert (registro["kwargs"]["datetime"]
            == "2026-07-06T23:59:59Z/2026-07-16T23:59:59Z")
    assert registro["kwargs"]["collections"] == ["sentinel-1-rtc"]
    assert registro["kwargs"]["intersects"] is GEOM


def test_days_mide_hacia_atras_desde_el_corte(fake_stac):
    registro = fake_stac([FakeItem(utc(2025, 3, 6, 23, 29))])

    search_latest_s1(GEOM, 12, utc(2025, 3, 14, 23, 59, 59))

    inicio, fin = registro["kwargs"]["datetime"].split("/")
    assert inicio.startswith("2025-03-02")
    assert fin.startswith("2025-03-14")


def test_elige_la_escena_mas_reciente_del_lote(fake_stac):
    """La API puede devolver sin ordenar: el orden lo garantiza el cliente."""
    vieja = FakeItem(utc(2026, 7, 10, 10, 2), "S1C_vieja")
    nueva = FakeItem(utc(2026, 7, 16, 10, 2), "S1D_nueva")
    fake_stac([vieja, nueva, FakeItem(utc(2026, 7, 12, 23, 28), "S1C_media")])

    assert search_latest_s1(GEOM, 10, utc(2026, 7, 17)).id == "S1D_nueva"


def test_un_item_sin_fecha_no_rompe_el_orden(fake_stac):
    """STAC permite `datetime: null` (items que usan start/end_datetime).

    Ordenar por ese campo sin protección compara None con datetime y tira
    TypeError. Sentinel-1 RTC siempre trae fecha, pero un item sin ella no
    debe voltear la corrida: va al fondo y gana el que sí la tiene.
    """
    sin_fecha = FakeItem(utc(2026, 7, 20), "S1_sin_fecha")
    sin_fecha.datetime = None
    fake_stac([sin_fecha, FakeItem(utc(2026, 7, 16, 10, 2), "S1_con_fecha")])

    assert search_latest_s1(GEOM, 10, utc(2026, 7, 17)).id == "S1_con_fecha"


def test_ventana_vacia_falla_con_mensaje_util(fake_stac):
    """Sin escena en la ventana el script corta, no retrocede en silencio.

    Es la garantía de una corrida de validación: nunca se compara contra
    una escena de semanas antes de la fecha pedida.
    """
    fake_stac([])

    with pytest.raises(SystemExit) as exc:
        search_latest_s1(GEOM, 1, utc(2026, 7, 17, 23, 59, 59))

    msg = str(exc.value)
    assert "1 días previos" in msg
    assert "2026-07-17" in msg
    assert "--days" in msg and "--end-date-utc" in msg


def test_la_referencia_se_ancla_en_la_escena_no_en_el_reloj(fake_stac):
    """Con --change, la referencia retrocede junto al corte.

    `search_reference_s1` deriva su ventana del datetime del item elegido,
    así que al procesar una fecha histórica la referencia también es
    histórica — sin que --end-date-utc tenga que pasarle nada.
    """
    actual = FakeItem(utc(2026, 7, 16, 10, 2), orbit=156, state="descending")
    ref = FakeItem(utc(2026, 7, 10, 10, 2), "S1C_ref")
    registro = fake_stac([ref])

    elegida = search_reference_s1(GEOM, actual, ref_days=45)

    assert elegida.id == "S1C_ref"
    assert elegida.datetime < actual.datetime
    inicio, fin = registro["kwargs"]["datetime"].split("/")
    assert inicio == "2026-06-01"   # 45 días antes de la escena
    assert fin == "2026-07-10"      # 6 días antes: revisita mínima de S1
    # Misma geometría de adquisición, si no la comparación de dB no vale.
    assert registro["kwargs"]["query"] == {
        "sat:relative_orbit": {"eq": 156},
        "sat:orbit_state": {"eq": "descending"},
    }


def test_sin_referencia_devuelve_none_y_no_aborta(fake_stac):
    """--change degrada a solo-umbral; no es motivo para cortar la corrida."""
    fake_stac([])
    actual = FakeItem(utc(2026, 7, 16, 10, 2))

    assert search_reference_s1(GEOM, actual, ref_days=45) is None
