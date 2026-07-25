"""`parse_end_date`: semántica de la fecha de corte. Sin red."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import flood_monitor
import list_s1_items
from flood_monitor import parse_end_date


def test_sin_argumento_es_ahora_en_utc():
    """Sin --end-date el corte es "ahora": el comportamiento NRT de siempre."""
    antes = datetime.now(timezone.utc)
    t = parse_end_date(None)
    despues = datetime.now(timezone.utc)
    assert t.utcoffset() == timedelta(0)
    assert antes <= t <= despues


def test_fecha_pelada_llega_al_final_del_dia():
    """`--end-date 2026-07-16` debe cubrir TODO el 16.

    Si resolviera a las 00:00 se perderían las escenas de ese mismo día
    (sobre Tongoy, Sentinel-1 pasa ~10:02 UTC), que es justo la fecha que
    el usuario pidió validar.
    """
    t = parse_end_date("2026-07-16")
    assert (t.year, t.month, t.day) == (2026, 7, 16)
    assert (t.hour, t.minute, t.second) == (23, 59, 59)
    assert t.utcoffset() == timedelta(0)


def test_iso_sin_zona_se_asume_utc():
    t = parse_end_date("2026-07-13T06:30:00")
    assert t == datetime(2026, 7, 13, 6, 30, tzinfo=timezone.utc)


def test_iso_con_z_es_utc():
    t = parse_end_date("2026-07-13T06:30:00Z")
    assert t == datetime(2026, 7, 13, 6, 30, tzinfo=timezone.utc)


def test_iso_con_offset_se_convierte_a_utc():
    """Un offset explícito debe convertirse, no solo aceptarse.

    El rango STAC se formatea con sufijo "Z"; devolver la hora local
    declararía como UTC un instante corrido por el offset (acá, 4 h).
    """
    t = parse_end_date("2026-07-13T06:30:00-04:00")
    assert t == datetime(2026, 7, 13, 10, 30, tzinfo=timezone.utc)
    assert t.utcoffset() == timedelta(0)


def test_fecha_invalida_falla_fuerte():
    """Mejor un error ruidoso que un corte silenciosamente equivocado."""
    with pytest.raises(ValueError):
        parse_end_date("16/07/2026")


def test_helper_es_uno_solo_para_ambos_scripts():
    """`list_s1_items` importa el helper de `flood_monitor`, no lo duplica.

    Si alguien lo vuelve a copiar, las dos semánticas pueden divergir sin
    que nadie lo note: este test lo impide.
    """
    assert list_s1_items.parse_end_date is flood_monitor.parse_end_date
