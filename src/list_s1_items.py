#!/usr/bin/env python3
"""
list_s1_items.py — Lista los N items Sentinel-1 RTC más recientes que
intersectan un AOI, buscando hacia atrás desde una fecha de fin.

Utilidad de solo lectura para auditar disponibilidad de escenas antes de
correr flood_monitor.py (por ejemplo, para elegir una fecha de referencia
manualmente o depurar coberturas).

Uso:
    python list_s1_items.py --place Tongoy
    python list_s1_items.py --place Ovalle --end-date 2025-01-15 -n 5
    python list_s1_items.py --bbox -71.3 -29.95 -71.1 -29.8 --days-back 60
    python list_s1_items.py --aoi mi_zona.geojson -n 3
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flood_monitor import (DEFAULT_REGION, load_aoi, parse_end_date,
                           stac_catalog)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Lista los N items Sentinel-1 RTC más recientes que "
                     "intersectan un AOI, buscando hacia atrás desde una "
                     "fecha de fin.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--aoi", type=Path, help="GeoJSON con el área de interés")
    g.add_argument("--bbox", nargs=4, type=float,
                    metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
                    help="Bounding box en lon/lat (EPSG:4326)")
    g.add_argument("--place", type=str,
                    help="Punto de interés por nombre (ej: 'Tongoy', "
                         "'Ovalle'), geocodificado con Nominatim/OSM dentro "
                         "de --region")
    p.add_argument("--region", type=str, default=DEFAULT_REGION,
                    help=f"Contexto geográfico para --place "
                         f"(default: '{DEFAULT_REGION}')")
    p.add_argument("--buffer-km", type=float, default=5.0,
                    help="Margen en km alrededor del lugar geocodificado "
                         "(default: 5)")
    p.add_argument("-n", "--num-items", type=int, default=10,
                    help="Cantidad de items a listar (default: 10)")
    p.add_argument("--end-date", type=str, default=None,
                    help="Fecha de fin (YYYY-MM-DD o ISO 8601) desde la "
                         "cual buscar hacia atrás, UTC. Default: ahora")
    p.add_argument("--days-back", type=int, default=None,
                    help="Opcional: acota la búsqueda a los N días previos "
                         "a --end-date. Default: sin límite (todo el "
                         "archivo)")
    return p.parse_args()


def search_recent_s1_items(geom: dict, n: int, end: datetime,
                            days_back: int | None):
    """Devuelve hasta `n` items Sentinel-1 RTC que intersectan `geom`,
    de más reciente a más antiguo, buscando hacia atrás desde `end`.

    Usa sortby+max_items del lado del servidor (la API de Planetary
    Computer soporta la STAC API Sort extension) en vez de ensanchar
    ventanas de fecha: con un intervalo abierto ("../end") se garantizan
    hasta `n` resultados en una sola búsqueda paginada, sin adivinar
    cuántos días hacia atrás hace falta mirar."""
    if days_back is not None:
        start = end - timedelta(days=days_back)
        dt_range = f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}"
    else:
        dt_range = f"../{end:%Y-%m-%dT%H:%M:%SZ}"

    search = stac_catalog().search(
        collections=["sentinel-1-rtc"],
        intersects=geom,
        datetime=dt_range,
        sortby=[{"field": "properties.datetime", "direction": "desc"}],
        max_items=n,
    )
    # Re-ordenamos también del lado del cliente como red de seguridad
    # barata (n es chico): si el servidor no respetara sortby, igual
    # obtenemos el orden correcto.
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    items = sorted(search.items(), key=lambda it: it.datetime or epoch,
                   reverse=True)
    if not items:
        end_desc = f"hasta {end:%Y-%m-%d}"
        if days_back is not None:
            end_desc += f" (ventana de {days_back} días)"
        sys.exit(f"[!] No hay imágenes Sentinel-1 {end_desc} para ese AOI.")
    return items


def print_items(items, end: datetime) -> None:
    print(f"[+] {len(items)} item(s) encontrado(s) hasta "
          f"{end:%Y-%m-%d %H:%M} UTC:")
    for i, it in enumerate(items, start=1):
        orbit = it.properties.get("sat:relative_orbit", "?")
        state = it.properties.get("sat:orbit_state", "?")
        platform = it.properties.get("platform", "?")
        print(f"  {i:>2}. {it.id}")
        print(f"      Fecha: {it.datetime:%Y-%m-%d %H:%M:%S} UTC  "
              f"(órbita relativa {orbit}, {state}, {platform})")


def main() -> None:
    args = parse_args()
    geom, bbox = load_aoi(args)
    print(f"[+] AOI bbox: {tuple(round(v, 4) for v in bbox)}")
    end = parse_end_date(args.end_date)
    items = search_recent_s1_items(geom, args.num_items, end, args.days_back)
    print_items(items, end)


if __name__ == "__main__":
    main()
