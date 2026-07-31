"""Resolución de la ventana de validación (inicio, fin) en UTC. Sin red.

Los tests con --local-time usan la fixture `en_santiago` (conftest.py, ya
compartida con test_end_date.py) para fijar TZ en vez de leer la de la
máquina.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from flood_validation import cli, windows


def _args(extra: list[str]) -> object:
    return cli.parse_args(
        ["--bbox", "-71.5", "-30.3", "-71.4", "-30.2", *extra])


def test_sin_start_date_usa_days_hacia_atras():
    """Igual patrón que --days en flood_monitor.py: ventana = end - days."""
    args = _args(["--end-date-utc", "2026-07-22", "--days", "7"])

    start, end = windows.resolve_window(args)

    assert end == datetime(2026, 7, 22, 23, 59, 59, tzinfo=timezone.utc)
    assert start == end - timedelta(days=7)


def test_start_date_pelada_resuelve_a_medianoche():
    """Asimetría a propósito: `end` pelada = 23:59:59 (incluye todo el
    día), `start` pelada = 00:00:00 (el día entero queda dentro de la
    ventana, no solo su segunda mitad)."""
    args = _args(["--start-date-utc", "2026-07-15",
                 "--end-date-utc", "2026-07-22"])

    start, end = windows.resolve_window(args)

    assert start == datetime(2026, 7, 15, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 22, 23, 59, 59, tzinfo=timezone.utc)


def test_start_date_iso_con_hora():
    args = _args(["--start-date-utc", "2026-07-15T06:00:00",
                 "--end-date-utc", "2026-07-22"])

    start, _ = windows.resolve_window(args)

    assert start == datetime(2026, 7, 15, 6, 0, 0, tzinfo=timezone.utc)


def test_start_date_con_offset_explicito():
    args = _args(["--start-date-utc", "2026-07-15T06:00:00-04:00",
                 "--end-date-utc", "2026-07-22"])

    start, _ = windows.resolve_window(args)

    assert start == datetime(2026, 7, 15, 10, 0, 0, tzinfo=timezone.utc)


def test_ventana_invertida_falla():
    args = _args(["--start-date-utc", "2026-07-25",
                 "--end-date-utc", "2026-07-22"])

    with pytest.raises(SystemExit):
        windows.resolve_window(args)


def test_ventana_vacia_falla():
    """Mismo instante para inicio y fin: sin margen para buscar nada."""
    args = _args(["--start-date-utc", "2026-07-22T23:59:59",
                 "--end-date-utc", "2026-07-22"])

    with pytest.raises(SystemExit):
        windows.resolve_window(args)


def test_start_date_en_zona_local_usa_el_offset_de_esa_fecha(en_santiago):
    """Enero: verano en Chile, -03. 2026-01-15 00:00 local = 03:00 UTC."""
    args = _args(["--start-date-utc", "2026-01-15",
                 "--end-date-utc", "2026-01-20", "--local-time"])

    start, _ = windows.resolve_window(args)

    assert start == datetime(2026, 1, 15, 3, 0, 0, tzinfo=timezone.utc)


def test_start_date_en_invierno_usa_el_offset_de_esa_fecha(en_santiago):
    """Julio: invierno en Chile, -04 — el mismo flag da un offset distinto
    según la fecha pedida, no según la fecha de hoy."""
    args = _args(["--start-date-utc", "2026-07-15",
                 "--end-date-utc", "2026-07-20", "--local-time"])

    start, _ = windows.resolve_window(args)

    assert start == datetime(2026, 7, 15, 4, 0, 0, tzinfo=timezone.utc)
