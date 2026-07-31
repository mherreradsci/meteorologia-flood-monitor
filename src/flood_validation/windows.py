"""windows.py — resuelve la ventana de validación (inicio, fin) en UTC.

`end` reutiliza `parse_end_date` de flood_monitor.py (misma semántica que
list_s1_items.py ya comparte). `start` necesita su propio parseo: una fecha
"pelada" (YYYY-MM-DD) tiene que resolver a las 00:00:00 de ese día —el
principio de la ventana— y no a las 23:59:59 que usa parse_end_date para un
corte.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from flood_monitor import parse_end_date


def _parse_start_date(s: str, local: bool) -> datetime:
    if len(s) == 10:  # "YYYY-MM-DD"
        dt = datetime.strptime(s, "%Y-%m-%d")
    else:
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None or local:
        # Mismo motivo que en parse_end_date: .astimezone() sobre un naive
        # aplica el offset vigente en esa fecha, no el de hoy.
        return dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=timezone.utc)


def resolve_window(args: argparse.Namespace) -> tuple[datetime, datetime]:
    """Devuelve (start, end) aware UTC a partir de los flags de ventana.

    `end` sale de --end-date-utc (o "ahora"); `start` de --start-date-utc si
    se dio, si no de `end - --days`. Corta la corrida si la ventana queda
    vacía o invertida en vez de dejar que un STAC range abierto al revés
    falle más adelante con un traceback menos claro.
    """
    end = parse_end_date(args.end_date_utc, args.local_time)
    if args.start_date_utc is not None:
        start = _parse_start_date(args.start_date_utc, args.local_time)
    else:
        start = end - timedelta(days=args.days)
    if start >= end:
        raise SystemExit(
            f"[!] La ventana de validación quedó vacía o invertida: "
            f"{start:%Y-%m-%d %H:%M:%S} UTC a {end:%Y-%m-%d %H:%M:%S} UTC. "
            f"Revisa --start-date-utc/--end-date-utc/--days.")
    return start, end
