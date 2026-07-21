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
```

There is no test suite, linter, or build step in this repo — verification is
by inspecting the generated outputs (quicklook PNG against known terrain,
GeoJSON in QGIS/geojson.io) or comparing against Copernicus Global Flood
Monitoring (https://global-flood.emergency.copernicus.eu/).

## Architecture

Everything is in `src/flood_monitor.py`, structured as a linear pipeline
driven by `main()`:

1. **AOI resolution** (`load_aoi` / `geocode_place`) — three mutually
   exclusive input modes (`--aoi`, `--bbox`, `--place`). `--place` geocodes
   via Nominatim/OSM using the *center point* of the result plus
   `--buffer-km`, not Nominatim's bounding box (admin boundaries can be
   ~100 km wide).
2. **Image search** (`search_latest_s1`, `search_reference_s1`) — queries the
   `sentinel-1-rtc` STAC collection. Reference-image search (for `--change`)
   filters on `sat:relative_orbit` + `sat:orbit_state` so the two acquisitions
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

## Notes on calibration (from README)

- Otsu threshold can fail on low-water scenes; fix with `--threshold` and
  tune by comparing the quicklook against known terrain.
- Typical false positives: relief shadows, asphalt/runways, smooth dry soil.
  Use `--min-area-px` and `--max-slope` to suppress these.
- Sentinel-1 revisit is ~2-6 days depending on location; the script prints
  the age of the image it used.
