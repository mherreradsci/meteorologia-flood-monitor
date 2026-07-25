#!/usr/bin/env python3
"""
flood_monitor.py — Mapa de anegamiento casi en tiempo real con Sentinel-1 (SAR).

Fuente: Microsoft Planetary Computer (colección "sentinel-1-rtc", ya calibrada
y corregida por terreno — no hace falta SNAP ni preprocesamiento pesado).
Agua permanente: JRC Global Surface Water (colección "jrc-gsw").

Uso:
    python flood_monitor.py --aoi aoi.geojson
    python flood_monitor.py --bbox -58.65 -34.75 -58.30 -34.45   # xmin ymin xmax ymax
    python flood_monitor.py --place Tongoy                # POI en Región de Coquimbo
    python flood_monitor.py --place Ovalle --buffer-km 8
    python flood_monitor.py --place "La Serena" --change  # cambio entre 2 fechas
    python flood_monitor.py --place Tongoy --end-date 2025-03-14  # fecha pasada
    python flood_monitor.py --bbox ... --days 12 --threshold -17.5

Salidas (en ./output/), con sufijo de trazabilidad
<region>_<place>_<fecha-imagen>_<secuencia>_<fecha-local> (no se pisan
entre corridas):
    flood_mask_<tag>.tif      GeoTIFF binario (1 = anegado)
    flood_mask_<tag>.geojson  Polígonos vectorizados del anegamiento
    flood_map_<tag>.html      Mapa interactivo (abrir en navegador)
    quicklook_<tag>.png       Vista rápida VH + máscara
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

OUTPUT_DIR = Path("output")
DB_NODATA = -9999.0
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_REGION = "Región de Coquimbo, Chile"


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Anegamiento NRT con Sentinel-1 RTC")
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
    p.add_argument("--days", type=int, default=10,
                   help="Buscar imágenes de los últimos N días (default: 10)")
    p.add_argument("--end-date", type=str, default=None,
                   help="Fecha de corte (YYYY-MM-DD o ISO 8601, UTC): usa la "
                        "última imagen anterior a esa fecha en vez de la más "
                        "reciente. Útil para validar contra una fecha "
                        "concreta. Default: ahora")
    p.add_argument("--threshold", type=float, default=None,
                   help="Umbral fijo en dB para VH (ej: -18). "
                        "Si se omite, se calcula con Otsu.")
    p.add_argument("--min-area-px", type=int, default=20,
                   help="Área mínima (píxeles) para conservar un parche de agua")
    p.add_argument("--change", action="store_true",
                   help="Detección de cambio entre dos fechas: además del "
                        "umbral, exige una caída de --change-delta dB "
                        "respecto a una imagen previa de la misma órbita. "
                        "Elimina falsos positivos permanentes (parcelas "
                        "lisas, pavimento, sombras urbanas).")
    p.add_argument("--ref-days", type=int, default=45,
                   help="Buscar la imagen de referencia hasta N días antes "
                        "de la imagen actual (default: 45)")
    p.add_argument("--change-delta", type=float, default=3.0,
                   help="Caída mínima de retrodispersión en dB respecto a la "
                        "referencia para marcar anegamiento (default: 3)")
    p.add_argument("--max-slope", type=float, default=5.0,
                   help="Pendiente máxima en grados (Copernicus DEM): píxeles "
                        "más empinados se descartan como falsos positivos "
                        "(sombras de relieve). 0 desactiva. Default: 5")
    return p.parse_args()


def geocode_place(place: str, region: str, buffer_km: float):
    """Geocodifica un punto de interés con Nominatim (OSM) y devuelve
    (geometry_dict, bbox_tuple) en EPSG:4326, con `buffer_km` de margen."""
    import requests
    from shapely.geometry import box, mapping

    r = requests.get(
        NOMINATIM_URL,
        params={"q": f"{place}, {region}", "format": "jsonv2", "limit": 1},
        headers={"User-Agent": "flood-monitor/1.0 (anegamiento Sentinel-1)"},
        timeout=30,
    )
    r.raise_for_status()
    results = r.json()
    if not results:
        sys.exit(f"[!] Nominatim no encontró '{place}' en '{region}'. "
                 f"Probá otro nombre o ajustá --region.")
    res = results[0]
    print(f"[+] POI geocodificado: {res['display_name']}")
    # Usamos el centro del resultado, no su boundingbox: para comunas
    # Nominatim devuelve el límite administrativo entero (~100 km de lado).
    lat_c, lon_c = float(res["lat"]), float(res["lon"])

    # Buffer en km -> grados (lon corregida por latitud).
    dlat = buffer_km / 111.32
    dlon = float(buffer_km / (111.32 * max(np.cos(np.radians(lat_c)), 0.01)))
    bbox = (lon_c - dlon, lat_c - dlat, lon_c + dlon, lat_c + dlat)
    print(f"[+] AOI: {2 * buffer_km:.0f}x{2 * buffer_km:.0f} km alrededor de "
          f"({lat_c:.4f}, {lon_c:.4f})")
    geom = box(*bbox)
    return mapping(geom), bbox


def load_aoi(args: argparse.Namespace):
    """Devuelve (geometry_dict, bbox_tuple) en EPSG:4326."""
    from shapely.geometry import box, shape, mapping

    if args.place:
        return geocode_place(args.place, args.region, args.buffer_km)

    if args.bbox:
        geom = box(*args.bbox)
        return mapping(geom), tuple(args.bbox)

    gj = json.loads(args.aoi.read_text())
    if gj.get("type") == "FeatureCollection":
        geom = shape(gj["features"][0]["geometry"])
    elif gj.get("type") == "Feature":
        geom = shape(gj["geometry"])
    else:
        geom = shape(gj)
    return mapping(geom), geom.bounds


def parse_end_date(s: str | None) -> datetime:
    """Parsea --end-date a datetime aware UTC. Sin --end-date, usa el
    momento actual. Con solo fecha (YYYY-MM-DD), usa el final de ese día
    (23:59:59 UTC) para incluir todas las imágenes de esa fecha.

    Compartida con list_s1_items.py (que la importa desde acá)."""
    if s is None:
        return datetime.now(timezone.utc)
    if len(s) == 10:  # "YYYY-MM-DD"
        return datetime.strptime(s, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    # Con offset explícito ("...T10:00:00-04:00") hay que convertir, no solo
    # aceptar: el rango STAC se formatea con sufijo "Z", así que devolver la
    # hora local declararía como UTC un instante que no lo es.
    return dt.astimezone(timezone.utc)


def slugify(s: str) -> str:
    """Nombre apto para archivo: solo espacios en blanco -> '_'.
    Conserva tildes y 'ñ'/'Ñ'; solo reemplaza '/' (separador de rutas)."""
    return re.sub(r"\s+", "_", s.strip()).replace("/", "-")


def build_run_tag(args: argparse.Namespace, bbox, item) -> str:
    """Sufijo de trazabilidad para los archivos de salida:
    <region>_<place>_<fecha-imagen>_<secuencia-segura>_<fecha-local>.

    Cada corrida genera un tag distinto (secuencia aleatoria + timestamp
    local) para no pisar salidas previas, incluso reprocesando la misma
    imagen Sentinel-1."""
    if args.place:
        region = slugify(args.region)
        place = slugify(args.place)
    else:
        # Sin --place no hay nombre geocodificado: identificamos el AOI
        # por sus coordenadas (bbox o --aoi resuelven a un bbox igual).
        region = "bbox"
        place = "_".join(f"{v:.4f}" for v in bbox)
    img_ts = f"{item.datetime:%Y%m%dT%H%M%SZ}"
    sequence = secrets.token_hex(4)
    local_ts = f"{datetime.now():%Y%m%dT%H%M%S}"
    return f"{region}_{place}_{img_ts}_{sequence}_{local_ts}"


def to_db(arr: np.ndarray) -> np.ndarray:
    """Potencia lineal -> dB, protegiendo ceros/negativos."""
    out = np.full(arr.shape, DB_NODATA, dtype="float32")
    valid = arr > 0
    out[valid] = 10.0 * np.log10(arr[valid])
    return out


# --------------------------------------------------------------------------- #
# Búsqueda y descarga
# --------------------------------------------------------------------------- #
def stac_catalog():
    import planetary_computer as pc
    from pystac_client import Client

    return Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=pc.sign_inplace,
    )


def search_latest_s1(geom: dict, days: int, end: datetime):
    """Busca el item Sentinel-1 RTC más reciente anterior a `end` que
    intersecte el AOI, dentro de una ventana de `days` días hacia atrás.
    Sin --end-date, `end` es "ahora" y equivale a la imagen más reciente."""
    start = end - timedelta(days=days)

    search = stac_catalog().search(
        collections=["sentinel-1-rtc"],
        intersects=geom,
        # Con hora, no solo fecha: --end-date YYYY-MM-DD resuelve a las
        # 23:59:59 y así no se pierden las escenas de ese mismo día.
        datetime=f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}",
    )
    items = sorted(search.item_collection(),
                   key=lambda it: it.datetime, reverse=True)
    if not items:
        sys.exit(f"[!] No hay imágenes Sentinel-1 en los {days} días previos "
                 f"a {end:%Y-%m-%d} para ese AOI. Probá aumentar --days o "
                 f"mover --end-date.")
    item = items[0]
    now = datetime.now(timezone.utc)
    age = f"hace {(now - item.datetime).days} días"
    # Con --end-date la antigüedad real no dice nada sobre la fecha pedida:
    # informamos además cuánto quedó la escena antes del corte.
    if (now - end).total_seconds() > 60:
        age += f", {(end - item.datetime).days} días antes del corte"
    print(f"[+] Imagen encontrada: {item.id}")
    print(f"    Fecha: {item.datetime:%Y-%m-%d %H:%M} UTC ({age})")
    return item


def search_reference_s1(geom: dict, current, ref_days: int):
    """Busca una imagen de referencia previa a `current`, de la misma órbita
    relativa (misma geometría de adquisición). Devuelve el item o None."""
    orbit = current.properties.get("sat:relative_orbit")
    state = current.properties.get("sat:orbit_state")
    # Al menos 6 días de separación (revisita mínima S1); hasta ref_days.
    end = current.datetime - timedelta(days=6)
    start = current.datetime - timedelta(days=ref_days)
    search = stac_catalog().search(
        collections=["sentinel-1-rtc"],
        intersects=geom,
        datetime=f"{start:%Y-%m-%d}/{end:%Y-%m-%d}",
        query={"sat:relative_orbit": {"eq": orbit},
               "sat:orbit_state": {"eq": state}},
    )
    items = sorted(search.item_collection(),
                   key=lambda it: it.datetime, reverse=True)
    if not items:
        return None
    ref = items[0]
    print(f"[+] Referencia: {ref.id}")
    print(f"    Fecha: {ref.datetime:%Y-%m-%d %H:%M} UTC "
          f"({(current.datetime - ref.datetime).days} días antes, "
          f"órbita relativa {orbit})")
    return ref


def read_vh_db(item, bbox):
    """Lee la banda VH recortada al bbox y la devuelve en dB (rioxarray)."""
    import rioxarray  # noqa: F401  (registra el accessor .rio)
    import xarray as xr  # noqa: F401

    href = item.assets["vh"].href
    da = (
        __import__("rioxarray")
        .open_rasterio(href, masked=True)
        .rio.clip_box(*bbox, crs="EPSG:4326")
        .squeeze("band", drop=True)
    )
    vh_db = da.copy(data=to_db(da.values))
    vh_db = vh_db.where(vh_db != DB_NODATA)
    print(f"[+] VH leída: {vh_db.shape[1]}x{vh_db.shape[0]} px, "
          f"CRS {da.rio.crs}")
    return vh_db


def water_threshold(vh_db, fixed: float | None) -> float:
    """Umbral fijo o automático (Otsu) sobre los valores válidos."""
    if fixed is not None:
        print(f"[+] Umbral fijo: {fixed:.1f} dB")
        return fixed
    from skimage.filters import threshold_otsu

    vals = vh_db.values[np.isfinite(vh_db.values)]
    t = float(threshold_otsu(vals))
    # Otsu puede fallar en escenas casi sin agua; acotamos a un rango sensato.
    t = float(np.clip(t, -25.0, -14.0))
    print(f"[+] Umbral Otsu (acotado): {t:.1f} dB")
    return t


# --------------------------------------------------------------------------- #
# Agua permanente (JRC)
# --------------------------------------------------------------------------- #
def permanent_water_mask(geom: dict, bbox, template):
    """Máscara booleana de agua permanente (JRC GSW, occurrence > 50%),
    reproyectada a la grilla de `template`. Si falla, devuelve None."""
    try:
        import rioxarray
        from rioxarray.merge import merge_arrays

        items = list(stac_catalog().search(collections=["jrc-gsw"],
                                           intersects=geom).item_collection())
        if not items:
            return None
        # Margen extra en el recorte: sin él, reproject_match deja NaN en los
        # bordes de la grilla UTM y el océano queda sin enmascarar (cuñas
        # falsas de "anegamiento" pegadas al borde del AOI).
        pad = 0.02
        pbbox = (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)
        tiles = []
        for it in items:
            da = (rioxarray.open_rasterio(it.assets["occurrence"].href,
                                          masked=True)
                  .rio.clip_box(*pbbox, crs="EPSG:4326")
                  .squeeze("band", drop=True))
            tiles.append(da)
        occ = tiles[0] if len(tiles) == 1 else merge_arrays(tiles)
        occ = occ.rio.reproject_match(template)
        mask = occ.values > 50  # agua presente >50% del tiempo
        # Dilatación leve (~30 m): absorbe el desalineado JRC/S1 en la línea
        # de costa y la franja de rompiente, sin comerse humedales interiores.
        from skimage.morphology import dilation, disk
        mask = dilation(mask, disk(3))
        print(f"[+] Agua permanente (JRC): {mask.sum():,} px enmascarados")
        return mask
    except Exception as e:  # noqa: BLE001
        print(f"[!] No pude cargar JRC GSW ({e}). Sigo sin enmascarar "
              f"agua permanente.")
        return None


# --------------------------------------------------------------------------- #
# Pendiente (Copernicus DEM)
# --------------------------------------------------------------------------- #
def slope_mask(geom: dict, bbox, template, max_slope_deg: float):
    """Máscara booleana de pendiente > max_slope_deg (Copernicus DEM GLO-30),
    calculada sobre la grilla de `template`. Si falla, devuelve None."""
    if max_slope_deg <= 0:
        return None
    try:
        import rioxarray
        from rasterio.enums import Resampling
        from rioxarray.merge import merge_arrays

        items = list(stac_catalog().search(collections=["cop-dem-glo-30"],
                                           intersects=geom).item_collection())
        if not items:
            return None
        # Mismo margen que en JRC: evita NaN de borde tras reproject_match.
        pad = 0.02
        pbbox = (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)
        tiles = []
        for it in items:
            da = (rioxarray.open_rasterio(it.assets["data"].href, masked=True)
                  .rio.clip_box(*pbbox, crs="EPSG:4326")
                  .squeeze("band", drop=True))
            tiles.append(da)
        dem = tiles[0] if len(tiles) == 1 else merge_arrays(tiles)
        dem = dem.rio.reproject_match(template,
                                      resampling=Resampling.bilinear)
        # Pendiente en grados sobre la grilla UTM (resolución en metros).
        res_x, res_y = template.rio.resolution()
        dzdy, dzdx = np.gradient(dem.values, abs(res_y), abs(res_x))
        slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
        mask = np.isfinite(slope) & (slope > max_slope_deg)
        print(f"[+] Pendiente > {max_slope_deg:.0f}° (Cop-DEM GLO-30): "
              f"{mask.sum():,} px enmascarados")
        return mask
    except Exception as e:  # noqa: BLE001
        print(f"[!] No pude cargar el DEM ({e}). Sigo sin máscara de "
              f"pendiente.")
        return None


# --------------------------------------------------------------------------- #
# Detección y salidas
# --------------------------------------------------------------------------- #
def detect_flood(vh_db, threshold: float, perm_mask, steep_mask,
                 min_area_px: int, ref_db=None, change_delta: float = 3.0):
    from skimage.morphology import remove_small_objects

    water = np.isfinite(vh_db.values) & (vh_db.values < threshold)
    if ref_db is not None:
        # Cambio: el píxel debe haberse oscurecido >= change_delta dB
        # respecto a la referencia. Superficies oscuras en ambas fechas
        # (parcelas lisas, pavimento, sombras) quedan descartadas.
        diff = vh_db.values - ref_db.values
        changed = np.isfinite(diff) & (diff < -change_delta)
        print(f"[+] Criterio de cambio: {change_delta:.1f} dB de caída — "
              f"descarta {(water & ~changed).sum():,} px oscuros estables")
        water &= changed
    if perm_mask is not None:
        water &= ~perm_mask
    if steep_mask is not None:
        water &= ~steep_mask
    # skimage >= 0.26: max_size elimina parches de tamaño <= max_size,
    # equivalente al viejo min_size=min_area_px (que eliminaba < min_area_px).
    water = remove_small_objects(water, max_size=min_area_px - 1)
    pct = 100.0 * water.sum() / max(np.isfinite(vh_db.values).sum(), 1)
    print(f"[+] Anegamiento detectado: {water.sum():,} px "
          f"({pct:.2f}% del AOI)")
    return water


def save_outputs(vh_db, flood: np.ndarray, item, bbox, tag: str,
                 ref_db=None, ref_item=None):
    import geopandas as gpd
    import matplotlib.pyplot as plt
    import rasterio.features
    from shapely.geometry import shape as shp_shape

    OUTPUT_DIR.mkdir(exist_ok=True)

    # GeoTIFF
    tif = OUTPUT_DIR / f"flood_mask_{tag}.tif"
    mask_da = vh_db.copy(data=flood.astype("uint8"))
    mask_da.rio.write_nodata(255, inplace=True)
    mask_da.rio.to_raster(tif, dtype="uint8", compress="deflate")
    print(f"[+] GeoTIFF: {tif}")

    # Vectorización -> GeoJSON en EPSG:4326
    transform = vh_db.rio.transform()
    shapes = rasterio.features.shapes(flood.astype("uint8"),
                                      mask=flood, transform=transform)
    geoms = [shp_shape(g) for g, v in shapes if v == 1]
    gj = OUTPUT_DIR / f"flood_mask_{tag}.geojson"
    if geoms:
        gdf = gpd.GeoDataFrame(geometry=geoms, crs=vh_db.rio.crs)
        gdf = gdf.to_crs("EPSG:4326")
        gdf.to_file(gj, driver="GeoJSON")
        print(f"[+] GeoJSON: {gj} ({len(gdf)} polígonos)")
    else:
        gdf = None
        print("[i] Sin polígonos de anegamiento para vectorizar.")

    # Quicklook PNG (3 paneles si hay referencia de cambio, si no 2)
    png = OUTPUT_DIR / f"quicklook_{tag}.png"
    n = 3 if ref_db is not None else 2
    fig, ax = plt.subplots(1, n, figsize=(6 * n, 6))
    if ref_db is not None:
        ax[0].imshow(ref_db.values, cmap="gray", vmin=-25, vmax=0)
        ax[0].set_title(f"Referencia VH — {ref_item.datetime:%Y-%m-%d}")
    ax[-2].imshow(vh_db.values, cmap="gray", vmin=-25, vmax=0)
    ax[-2].set_title(f"Sentinel-1 VH (dB) — {item.datetime:%Y-%m-%d}")
    ax[-1].imshow(vh_db.values, cmap="gray", vmin=-25, vmax=0)
    overlay = np.ma.masked_where(~flood, flood)
    ax[-1].imshow(overlay, cmap="autumn", alpha=0.8)
    ax[-1].set_title("Anegamiento detectado")
    for a in ax:
        a.axis("off")
    fig.tight_layout()
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"[+] Quicklook: {png}")

    # Mapa interactivo
    if gdf is not None and len(gdf):
        try:
            import leafmap.foliumap as leafmap

            center = [(bbox[1] + bbox[3]) / 2, (bbox[0] + bbox[2]) / 2]
            # Sin capa base OSM: sus servidores exigen Referer y devuelven 403
            # al abrir el HTML desde file://. Usamos solo el satelital.
            m = leafmap.Map(center=center, zoom=11, tiles=None)
            # Calles OSM servidas por Carto: no exigen Referer, funcionan
            # desde file://. La última capa agregada queda visible al abrir.
            m.add_basemap("CartoDB.Voyager")
            m.add_basemap("SATELLITE")
            m.add_gdf(gdf, layer_name="Anegamiento",
                      style={"color": "#ff3300", "fillColor": "#ff3300",
                             "fillOpacity": 0.5, "weight": 1})
            html = OUTPUT_DIR / f"flood_map_{tag}.html"
            m.to_html(str(html))
            print(f"[+] Mapa interactivo: {html}")
        except Exception as e:  # noqa: BLE001
            print(f"[!] No pude generar el mapa HTML ({e}). "
                  f"Usá el GeoJSON en QGIS/geojson.io.")


def main() -> None:
    args = parse_args()
    geom, bbox = load_aoi(args)
    print(f"[+] AOI bbox: {tuple(round(v, 4) for v in bbox)}")

    end = parse_end_date(args.end_date)
    item = search_latest_s1(geom, args.days, end)
    vh_db = read_vh_db(item, bbox)

    ref_db = ref_item = None
    if args.change:
        ref_item = search_reference_s1(geom, item, args.ref_days)
        if ref_item is None:
            print(f"[!] Sin referencia de la misma órbita en los {args.ref_days} "
                  f"días previos. Sigo solo con umbral (probá subir --ref-days).")
        else:
            from rasterio.enums import Resampling

            ref_db = (read_vh_db(ref_item, bbox)
                      .rio.reproject_match(vh_db,
                                           resampling=Resampling.bilinear))

    thr = water_threshold(vh_db, args.threshold)
    perm = permanent_water_mask(geom, bbox, vh_db)
    steep = slope_mask(geom, bbox, vh_db, args.max_slope)
    flood = detect_flood(vh_db, thr, perm, steep, args.min_area_px,
                         ref_db, args.change_delta)
    tag = build_run_tag(args, bbox, item)
    print(f"[+] ID de corrida: {tag}")
    save_outputs(vh_db, flood, item, bbox, tag, ref_db, ref_item)
    print("[✓] Listo.")


if __name__ == "__main__":
    main()
