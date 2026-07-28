"""`parse_end_date`: semántica de la fecha de corte. Sin red.

Los tests de `--local-time` usan la fixture `en_santiago` (en `conftest.py`)
para fijar `TZ` en vez de leer la zona de la máquina: si no, pasarían en
Chile y fallarían en el runner de CI, que corre en UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import flood_monitor
import list_s1_items
from flood_monitor import parse_end_date


def test_sin_argumento_es_ahora_en_utc():
    """Sin --end-date-utc el corte es "ahora": el comportamiento NRT de siempre."""
    antes = datetime.now(timezone.utc)
    t = parse_end_date(None)
    despues = datetime.now(timezone.utc)
    assert t.utcoffset() == timedelta(0)
    assert antes <= t <= despues


def test_fecha_pelada_llega_al_final_del_dia():
    """`--end-date-utc 2026-07-16` debe cubrir TODO el 16.

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
    declararía como UTC un instante corrido por el offset (aquí, 4 h).
    """
    t = parse_end_date("2026-07-13T06:30:00-04:00")
    assert t == datetime(2026, 7, 13, 10, 30, tzinfo=timezone.utc)
    assert t.utcoffset() == timedelta(0)


# --------------------------------------------------------------------------- #
# --local-time
# --------------------------------------------------------------------------- #
def test_local_time_corre_el_corte_al_final_del_dia_local(en_santiago, capsys):
    """El caso de uso: validar contra una app que muestra hora de Chile.

    En julio Santiago es -04, así que el fin del 16 local son las 03:59:59
    UTC del 17 — otro día UTC, que es justo la confusión que el flag evita.
    Por eso además se imprime la equivalencia: el usuario pidió una fecha y
    el pipeline va a informar otra.
    """
    t = parse_end_date("2026-07-16", local=True)

    assert t == datetime(2026, 7, 17, 3, 59, 59, tzinfo=timezone.utc)
    salida = capsys.readouterr().out
    assert "2026-07-16 23:59:59" in salida     # lo que se pidió, local
    assert "2026-07-17 03:59:59 UTC" in salida  # contra qué se busca


def test_sin_el_flag_la_misma_fecha_corta_cuatro_horas_antes(en_santiago):
    """El contraste explícito: mismo texto, dos instantes distintos.

    Esas 4 horas contienen la pasada ascendente de Sentinel-1 sobre Chile
    (~23:28 UTC), así que la diferencia puede cambiar qué escena se usa.
    """
    utc = parse_end_date("2026-07-16")
    local = parse_end_date("2026-07-16", local=True)

    assert local - utc == timedelta(hours=4)


def test_usa_el_offset_vigente_en_esa_fecha_no_el_de_hoy(en_santiago):
    """Chile cambia de hora: -03 en verano, -04 en invierno.

    Un offset fijo tomado de `datetime.now()` daría bien una de las dos
    fechas y mal la otra; `.astimezone()` sobre un naive consulta las reglas
    de la zona para el instante pedido.
    """
    verano = parse_end_date("2026-01-15", local=True)   # -03
    invierno = parse_end_date("2026-07-15", local=True)  # -04

    assert verano == datetime(2026, 1, 16, 2, 59, 59, tzinfo=timezone.utc)
    assert invierno == datetime(2026, 7, 16, 3, 59, 59, tzinfo=timezone.utc)


def test_el_offset_explicito_le_gana_a_local_time(en_santiago):
    """Si el texto ya dice en qué zona está, no hay nada que suponer."""
    t = parse_end_date("2026-07-13T06:30:00+02:00", local=True)

    assert t == datetime(2026, 7, 13, 4, 30, tzinfo=timezone.utc)


def test_local_time_sin_fecha_avisa_que_no_hace_nada(capsys):
    """"Ahora" es un instante, no una fecha: no depende de la zona.

    Silenciarlo dejaría creer que el flag hizo algo.
    """
    t = parse_end_date(None, local=True)

    assert t.utcoffset() == timedelta(0)
    assert "--local-time no hace nada" in capsys.readouterr().out


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
