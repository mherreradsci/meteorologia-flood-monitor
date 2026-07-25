# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-script pipeline (`src/flood_monitor.py`) that detects near-real-time
flooding from Sentinel-1 SAR imagery. It queries Microsoft Planetary Computer
(no account/API key needed) for the VH backscatter band, thresholds it (Otsu
or fixed dB), masks out permanent water (JRC Global Surface Water) and steep
terrain (Copernicus DEM GLO-30, to drop relief-shadow false positives), and
writes a GeoTIFF, GeoJSON, PNG quicklook, and an interactive Leaflet HTML map.

## Setup

```bash
sudo apt update && sudo apt install -y gdal-bin libgdal-dev python3-dev python3-venv
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```
Python 3.12 (see `.python-version`). GDAL system libs must be installed before
`pip install` because `rasterio`/`rioxarray` build against them.

## Running

The script lives in `src/`, but `OUTPUT_DIR = Path("output")` is resolved
relative to the current working directory, not the script location — so
where you invoke `python` from determines whether results land in `./output`
or `src/output`. Pick one convention and stay consistent within a session.

```bash
cd src
python flood_monitor.py --place Tongoy                       # geocoded POI (default region: Coquimbo, Chile)
python flood_monitor.py --place Ovalle --buffer-km 8
python flood_monitor.py --place "Quilpué" --region "Región de Valparaíso, Chile"
python flood_monitor.py --place "La Serena" --change          # two-date change detection (urban/farmland)
python flood_monitor.py --bbox -58.65 -34.75 -58.30 -34.45     # xmin ymin xmax ymax, lon/lat
python flood_monitor.py --aoi mi_zona.geojson
python flood_monitor.py --aoi mi_zona.geojson --days 15 --threshold -18
python flood_monitor.py --place Tongoy --end-date 2025-03-14   # fecha pasada
```

`aoi/` (raíz del repo) guarda GeoJSON de referencia reutilizables como ejemplo
y para pruebas — nombrados `<País>-<Región>-<Comuna>-<Localidad>.geojson`
(ej. `aoi/Chile-Region_de_Coquimbo-La_huiguera-Chungungo.geojson`). Al
correr desde `src/`, referenciarlos con `--aoi ../aoi/<archivo>.geojson`.

## Tests

There is no linter or build step. There *is* a pytest suite in `tests/`,
covering AOI-independent logic — it does **not** validate detection quality
(for that, see "verificación visual" below).

```bash
pip install -r requirements-dev.txt   # solo pytest; el pipeline no lo necesita
pytest                                # todo (~18 s, consulta la API)
pytest -m "not network"               # solo offline (<1 s)
pytest -m network                     # solo los que consultan Planetary Computer
```

`pytest.ini` pone `src/` en `sys.path` (`pythonpath = src`), así que los tests
importan `flood_monitor` / `list_s1_items` por nombre igual que entre sí, y
`pytest` se corre desde la raíz del repo (no desde `src/`).

- `test_end_date.py`, `test_run_tag.py` — funciones puras (parseo de fechas,
  slug/tag de salida, conversión a dB).
- `test_detection.py` — el núcleo de la decisión: `water_threshold` (umbral
  fijo vs Otsu y su recorte a [-25, -14]) y `detect_flood` (umbral, nodata,
  el borde exacto de `--min-area-px`, las dos máscaras y el criterio de
  `--change`). Usa el doble `FakeRaster` de `helpers.py`, que solo expone
  `.values`: es todo lo que esas dos funciones leen, así que no hace falta
  xarray ni GDAL. Los mutantes de estas dos funciones (correr el `- 1` de
  `max_size`, aflojar `<` a `<=`, sacar el `clip` o la guarda `isfinite`)
  hacen fallar la suite; conviene que siga siendo así.
- `test_search_window.py` — mockea `stac_catalog` (fixture `fake_stac` en
  `conftest.py`) para fijar el rango de fechas exacto que se le pide a la API
  y cómo se elige entre lo que devuelve, sin red.
- `test_search_live.py` — marcado `network`. Es determinista pese a pegarle a
  un servicio remoto porque el archivo Sentinel-1 es **inmutable**: las
  aserciones se anclan en cortes históricos (`--end-date 2026-07-17` sobre
  Tongoy siempre devuelve la misma escena). Nunca afirmar sobre "la más
  reciente" en un test: eso cambia cada ~3 días. No descarga rasters.

Los tests de red usan un bbox literal de Tongoy (`TONGOY_GEOM` en
`conftest.py`) en vez de `--place`, para no depender también de Nominatim.

### CI

`.github/workflows/tests.yml` corre `pytest -m "not network"` en cada push a
`main` y en cada PR. **No instala `requirements.txt`**: solo pytest, numpy y
shapely, sin GDAL. Alcanza porque `flood_monitor.py` importa las librerías
pesadas *dentro* de las funciones y a nivel de módulo solo usa numpy (shapely
lo pide `conftest.py`). Ese mínimo es intencional: si alguien sube un import
pesado al tope de un módulo, el job falla — es lo que mantiene los imports
perezosos, y con ellos el arranque rápido del `--help`.

Ojo con Python: `datetime.fromisoformat` solo acepta el sufijo `Z` desde 3.11,
así que `parse_end_date("...T06:30:00Z")` revienta en 3.10. El repo apunta a
3.12 (`.python-version`) y el workflow lee ese mismo archivo.

**Verificación visual** (lo que los tests no cubren): inspeccionar el quicklook
PNG contra terreno conocido, el GeoJSON en QGIS/geojson.io, o comparar contra
Copernicus Global Flood Monitoring
(https://global-flood.emergency.copernicus.eu/).

## Architecture

Everything is in `src/flood_monitor.py`, structured as a linear pipeline
driven by `main()`:

1. **AOI resolution** (`load_aoi` / `geocode_place`) — three mutually
   exclusive input modes (`--aoi`, `--bbox`, `--place`). `--place` geocodes
   via Nominatim/OSM using the *center point* of the result plus
   `--buffer-km`, not Nominatim's bounding box (admin boundaries can be
   ~100 km wide).
2. **Image search** (`search_latest_s1`, `search_reference_s1`) — queries the
   `sentinel-1-rtc` STAC collection. The search window is `[end - --days, end]`,
   where `end` comes from `parse_end_date(--end-date)` and defaults to *now* —
   so `--end-date` reruns the whole pipeline "as of" a past date (for validating
   against another source on a specific day). A bare `YYYY-MM-DD` resolves to
   23:59:59 UTC so that day's own acquisitions are included. If no scene falls
   in the window the script exits rather than silently reaching further back;
   this is deliberate, so a validation run never compares against a scene weeks
   away from the requested date. Reference-image search (for `--change`)
   anchors on the *chosen* item's datetime, so it follows `--end-date` back
   automatically, and filters on `sat:relative_orbit` + `sat:orbit_state` so the two acquisitions
   share geometry, and requires ≥6 days separation (S1 minimum revisit).
3. **Read + convert** (`read_vh_db`) — clips the VH asset to bbox, converts
   linear power to dB (`to_db`), treating `DB_NODATA = -9999.0` as the
   sentinel for invalid pixels.
4. **Thresholding** (`water_threshold`) — Otsu by default, clamped to
   [-25, -14] dB since Otsu can misfire on scenes with little water; override
   with `--threshold`.
5. **Masking**:
   - `permanent_water_mask` — JRC GSW `occurrence > 50%`, reprojected to the
     VH grid with `reproject_match`, then dilated (`disk(3)`) to absorb
     JRC/S1 coastline misalignment. Both this and `slope_mask` clip a padded
     bbox (`pad = 0.02°`) before reprojecting — without the pad,
     `reproject_match` leaves NaN edges that show up as false flooding along
     the AOI border.
   - `slope_mask` — Copernicus DEM GLO-30, gradient → slope in degrees,
     discards pixels above `--max-slope` (default 5°, `0` disables).
   - Both masks fail soft: on any exception they print a warning and return
     `None` rather than aborting the run.
6. **Detection** (`detect_flood`) — combines threshold + optional change
   criterion (`vh_db - ref_db < -change_delta`, only with `--change`) +
   permanent-water and slope exclusions, then drops small patches via
   `remove_small_objects(max_size=min_area_px - 1)` (note the off-by-one:
   `skimage`'s `max_size` removes patches `<= max_size`, so this reproduces
   the old `min_size` semantics).
7. **Outputs** (`save_outputs`) — GeoTIFF, vectorized GeoJSON (reprojected to
   EPSG:4326), a 2- or 3-panel matplotlib quicklook (3 panels when a change
   reference exists), and a `leafmap` HTML map. The HTML map deliberately
   skips the OSM raster basemap (it 403s on `file://` due to `Referer`
   enforcement) and uses CartoDB Voyager + a satellite layer instead.

**Traceable output naming** (`build_run_tag`): every run's output files are
tagged `<region>_<place>_<image-date>_<random-hex>_<local-timestamp>` (or
`bbox_<coords>_...` when not using `--place`), so repeated runs — even
reprocessing the same Sentinel-1 scene — never overwrite prior outputs.

## Utilidades auxiliares

`src/list_s1_items.py` es un script hermano, de solo lectura, que lista los
N items Sentinel-1 RTC más recientes que intersectan un AOI, buscando hacia
atrás desde una fecha de fin (`--end-date`, default "ahora"). Reutiliza
`load_aoi`/`geocode_place`/`stac_catalog`/`DEFAULT_REGION` de
`flood_monitor.py` vía import directo (mismo directorio, sin paquete), y
comparte la misma convención de AOI (`--aoi`/`--bbox`/`--place`). También
importa de ahí `parse_end_date` y `EPOCH`, que viven en `flood_monitor.py`
porque ambos scripts aceptan `--end-date` con idéntica semántica y ordenan
items STAC igual (el import va siempre en esa dirección: `list_s1_items` →
`flood_monitor`, nunca al revés).

`EPOCH` existe porque STAC permite `datetime: null` (items que declaran
start/end_datetime en su lugar): ordenar por ese campo sin protección compara
None con datetime y tira `TypeError`. Con `key=lambda it: it.datetime or EPOCH`
esos items caen al fondo. Por eso `search_latest_s1` puede afirmar que, si el
elegido no tiene fecha, es que ninguno la tenía.

A diferencia de `search_latest_s1` (que ensancha una ventana fija de días y
ordena del lado del cliente), usa la STAC API **Sort extension**
(`sortby`) + `max_items` de Planetary Computer con un intervalo de fecha
abierto (`../{end_date}`), confirmado en vivo que pagina correctamente más
allá del tamaño de página por defecto de `pystac-client` (10). Esto evita
tener que adivinar cuántos días hacia atrás mirar.

```bash
cd src
python list_s1_items.py --place Tongoy
python list_s1_items.py --place Ovalle --end-date 2025-01-15 -n 5
python list_s1_items.py --bbox -71.3 -29.95 -71.1 -29.8 --days-back 60
python list_s1_items.py --aoi ../aoi/Chile-Region_de_Coquimbo-La_huiguera-Chungungo.geojson
```

## Notes on calibration (from README)

- Otsu threshold can fail on low-water scenes; fix with `--threshold` and
  tune by comparing the quicklook against known terrain.
- Typical false positives: relief shadows, asphalt/runways, smooth dry soil.
  Use `--min-area-px` and `--max-slope` to suppress these.
- Sentinel-1 revisit is ~2-6 days depending on location; the script prints
  the age of the image it used.
