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
python flood_monitor.py --place Tongoy --end-date-utc 2025-03-14              # corte en UTC
python flood_monitor.py --place Tongoy --end-date-utc 2025-03-14 --local-time # corte en hora local
```

`aoi/` (raíz del repo) guarda GeoJSON de referencia reutilizables como ejemplo
y para pruebas — nombrados `<País>-<Región>-<Comuna>-<Localidad>.geojson`
(ej. `aoi/Chile-Region_de_Coquimbo-La_huiguera-Chungungo.geojson`). Al
correr desde `src/`, referenciarlos con `--aoi ../aoi/<archivo>.geojson`.

## Tests

There is no linter or build step. There *is* a pytest suite en `tests/` (116
tests) que cubre todas las funciones de ambos scripts. **No** valida la
calidad de la detección sobre imágenes reales (para eso, "verificación
visual" más abajo).

```bash
pip install -r requirements-dev.txt   # solo pytest; el pipeline no lo necesita
pytest                                # todo (~18 s, consulta la API)
pytest -m "not network"               # sin internet (~2 s)
pytest -m "not network and not raster"  # además sin GDAL (<1 s)
pytest -m raster                      # solo los de GeoTIFF sintéticos
pytest -m network                     # solo los que consultan Planetary Computer
```

`pytest.ini` pone `src/` en `sys.path` (`pythonpath = src`), así que los tests
importan `flood_monitor` / `list_s1_items` por nombre igual que entre sí, y
`pytest` se corre desde la raíz del repo (no desde `src/`).

- `test_end_date.py`, `test_run_tag.py` — funciones puras (parseo de fechas,
  slug/tag de salida, conversión a dB). Los de `--local-time` usan la fixture
  `en_santiago` (en `conftest.py`), que fija `TZ=America/Santiago` +
  `time.tzset()`: sin eso pasarían en Chile y fallarían en CI, que corre en
  UTC. La zona se eligió porque tiene horario de verano, así que el mismo
  test cubre que se aplique el offset de la fecha pedida (`-03` en enero,
  `-04` en julio) y no el de hoy. Verificado corriendo la suite entera bajo
  `TZ=UTC`, `TZ=America/Santiago` y `TZ=Asia/Tokyo`.
- `test_aoi.py` — `load_aoi` y `geocode_place`. Es la primera etapa y la que
  ningún otro test vigila: con el AOI equivocado, todo lo demás sigue en verde
  y el mapa sale bien calculado del lugar equivocado. Cubre las tres
  envolturas de GeoJSON, que un `FeatureCollection` de varios features usa
  solo el primero (limitación conocida, ahí documentada) y la matemática del
  buffer km→grados con la corrección por `cos(lat)`. Incluye un test
  parametrizado sobre los `aoi/*.geojson` del repo, así que esos ejemplos son
  documentación que CI protege.
- `test_cli.py` — contrato de `parse_args` en los dos scripts: exclusividad
  mutua de `--aoi/--bbox/--place` y los defaults que documentan README y este
  archivo (si cambian aquí, el test avisa).
- `test_list_items.py` — `search_recent_s1_items`: el intervalo abierto
  `../{end}`, `sortby` + `max_items` del lado del servidor y el reordenado
  cliente. Ojo con el parcheo: el hermano hace
  `from flood_monitor import stac_catalog`, o sea que guarda su propia
  referencia; por eso `fake_stac` acepta a qué módulo aplicarse.
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
- `test_masks.py` — marcado `raster`. `permanent_water_mask` y `slope_mask`
  son casi todo E/S, así que en vez de mockear rioxarray estos tests escriben
  GeoTIFF sintéticos a `tmp_path` y dejan correr el código real (`clip_box`,
  `reproject_match`, gradiente, dilatación); solo se sustituye la búsqueda
  STAC, así que no hay red. Los valores son analíticos: una rampa de 10 m por
  píxel de 30 m da exactamente atan(1/3) = 18.4349°, y un píxel aislado
  dilatado con `disk(3)` da 29 px. Necesitan rioxarray, que **no** requiere
  GDAL de sistema: las ruedas manylinux de rasterio lo traen embebido.
- `test_read_vh.py` — marcado `raster`. El cableado de `read_vh_db` sobre un
  GeoTIFF real: potencia lineal → dB, los ceros terminando en NaN vía
  `DB_NODATA`, el colapso de la banda y el recorte al bbox.
- `test_outputs.py` — marcado `raster`. Lo que se lleva el usuario, y sobre
  todo la **única transformación de coordenadas del pipeline**: la máscara se
  calcula en UTM y el GeoJSON se escribe en EPSG:4326. El test compara contra
  una conversión hecha por una ruta independiente (`rasterio.warp` en vez de
  geopandas/pyproj). Sin eso, un error de reproyección dejaría toda la suite
  en verde con los polígonos a cientos de km. `OUTPUT_DIR` se apunta a
  `tmp_path` con monkeypatch, ya que es un global relativo al cwd.
- `test_main.py` — marcado `raster`. `main()` de punta a punta: se sustituye
  solo el catálogo STAC (la frontera de red) por uno que sirve GeoTIFF
  sintéticos y el pipeline real corre entero. Lo que verifica es lo único que
  ningún test aislado puede ver: que el valor de cada opción de la CLI llegue
  a la etapa que corresponde —cruzar `--min-area-px` con `--max-slope` no
  rompería ningún otro test— y las tres ramas de `--change`. Cubre también
  `main()` del hermano.
- El andamiaje de los tests `raster` (grillas UTM 19S a 30 m, escritura de
  GeoTIFF, bbox en lon/lat) vive en `tests/raster_helpers.py`, aparte de
  `helpers.py` porque este último lo usan también los tests que corren sin
  GDAL. El origen elegido cae sobre Tongoy, así que las coordenadas que
  aparecen en los asserts son reconocibles.
- `test_search_live.py` — marcado `network`. Es determinista pese a pegarle a
  un servicio remoto porque el archivo Sentinel-1 es **inmutable**: las
  aserciones se anclan en cortes históricos (`--end-date-utc 2026-07-17` sobre
  Tongoy siempre devuelve la misma escena). Nunca afirmar sobre "la más
  reciente" en un test: eso cambia cada ~3 días. No descarga rasters.

Los tests de red usan un bbox literal de Tongoy (`TONGOY_GEOM` en
`conftest.py`) en vez de `--place`, para no depender también de Nominatim.

### CI

`.github/workflows/tests.yml` corre **dos jobs en paralelo** en cada push a
`main` y en cada PR, ninguno con red:

| job | instala | corre |
|---|---|---|
| `offline` | pytest, numpy, shapely, scikit-image, requests, pyyaml | `-m "not network and not raster"` |
| `raster` | lo anterior (sin pyyaml propio, se instala aparte) + rioxarray, geopandas, matplotlib, pysheds, pyyaml | `-m raster` |

Están separados a propósito. El job `offline` **no instala rioxarray**, así
que si alguien sube un import pesado al tope de un módulo, falla en la
recolección — es lo que mantiene los imports perezosos, y con ellos el
arranque rápido del `--help`. Metiendo rioxarray en ese mismo job esa alarma
se apagaría (verificado: con `import rioxarray` a nivel de módulo, `offline`
da 5 errores y `raster` pasa igual). `pyyaml` hace falta en los **dos**
jobs, por razones distintas: en `offline` porque
`tests/test_flood_validation_config.py` llama en serio al loader de
`flood_validation/config.py`; en `raster` porque `flood_validation.main()`
carga `regions.yaml`/`validation.yaml` siempre, incluso en las corridas
reales (no solo `--dry-run`) que ejercitan los tests raster de `main()` —
sin esto, cualquiera de esos tests revienta con `ModuleNotFoundError` antes
de tocar ningún sensor. En los dos casos el `import yaml` real sigue siendo
perezoso (dentro de la función, no al tope del módulo); la instalación en
CI es lo que cambió, no el estilo de import. Este gap en `raster` pasó
desapercibido durante varias fases seguidas porque el venv de desarrollo
local ya tenía `pyyaml` instalado (viene en `requirements.txt`) — solo se
detectó armando a mano un venv que replica el install list exacto de cada
job de CI y corriendo la selección de tests real ahí, no asumiendo que "pasa
en local" alcanza. `pysheds` es para `terrain.py` (HAND).

Ninguno de los dos necesita `apt install gdal-bin libgdal-dev`: las ruedas
manylinux de rasterio traen GDAL embebido. El apt del README hace falta solo
si tu plataforma no tiene rueda y pip compila desde fuente.

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
   where `end` comes from `parse_end_date(--end-date-utc, --local-time)` and
   defaults to *now* — so `--end-date-utc` reruns the whole pipeline "as of" a
   past date (for validating against another source on a specific day). A bare
   `YYYY-MM-DD` resolves to 23:59:59 so that day's own acquisitions are
   included. If no scene falls in the window the script exits rather than
   silently reaching further back; this is deliberate, so a validation run
   never compares against a scene weeks away from the requested date.
   Reference-image search (for `--change`) anchors on the *chosen* item's
   datetime, so it follows `--end-date-utc` back automatically, and filters on
   `sat:relative_orbit` + `sat:orbit_state` so the two acquisitions
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

**Zonas horarias** (`parse_end_date`): el pipeline trabaja **siempre en UTC**
—el rango STAC se formatea con sufijo `Z` y todo lo que se imprime lleva la
etiqueta UTC—, así que la función devuelve un datetime *aware* en UTC sin
excepción. Lo único configurable es cómo se **interpreta** el texto que
escribió el usuario, y el orden de prioridad es:

| entrada | zona con que se interpreta |
|---|---|
| offset explícito (`...T20:00:00-04:00`) | el offset dado; `--local-time` se ignora |
| naive + `--local-time` | zona del sistema, con el DST **de esa fecha** |
| naive sin flag | UTC (default histórico) |

El nombre del flag (`--end-date-utc`, antes `--end-date`) marca el default;
`--end-date` sigue siendo un alias de argparse para no romper crontabs.

La rama local usa `dt.astimezone(timezone.utc)` sobre un datetime **naive**,
no `dt.replace(tzinfo=<offset de hoy>)`. La diferencia importa en zonas con
horario de verano: `.astimezone()` sobre un naive presume hora del sistema y
consulta las reglas para *ese* instante, así que en Chile una fecha de enero
sale `-03` y una de julio `-04` aunque las corras el mismo día. Con un offset
fijo tomado de `datetime.now()`, una de las dos quedaría corrida una hora.

Sin fecha, `--local-time` no hace nada (el default es "ahora", el mismo
instante en toda zona) y el script lo avisa en vez de callarse. Con fecha
local sí imprime la equivalencia, porque el corte cae seguido en otro día UTC
que el pedido.

**Traceable output naming** (`build_run_tag`): every run's output files are
tagged `<region>_<place>_<image-date>_<random-hex>_<local-timestamp>`, so
repeated runs — even reprocessing the same Sentinel-1 scene — never overwrite
prior outputs. The `<region>_<place>` half depends on the input mode:

| modo | prefijo del tag |
|---|---|
| `--place` | `<región>_<lugar>` (ambos por `slugify`) |
| `--aoi` | `aoi_<nombre del geojson sin extensión>` |
| `--bbox` | `bbox_<xmin>_<ymin>_<xmax>_<ymax>` (4 decimales) |

Con `--aoi` se usa el nombre del archivo y no su envolvente porque dos
polígonos distintos pueden compartir bbox, y porque los AOI de `aoi/` ya
codifican país/región/comuna/localidad en el nombre — el resultado es
`flood_mask_aoi_Chile-Region_de_Coquimbo-Punitaqui-Punitaqui_<...>.tif` en vez
de una tira de coordenadas.

## Utilidades auxiliares

`src/list_s1_items.py` es un script hermano, de solo lectura, que lista los
N items Sentinel-1 RTC más recientes que intersectan un AOI, buscando hacia
atrás desde una fecha de fin (`--end-date-utc`, default "ahora"). Reutiliza
`load_aoi`/`geocode_place`/`stac_catalog`/`DEFAULT_REGION` de
`flood_monitor.py` vía import directo (mismo directorio, sin paquete), y
comparte la misma convención de AOI (`--aoi`/`--bbox`/`--place`). También
importa de ahí `parse_end_date` y `EPOCH`, que viven en `flood_monitor.py`
porque ambos scripts aceptan `--end-date-utc` y `--local-time` con idéntica
semántica y ordenan items STAC igual (el import va siempre en esa dirección:
`list_s1_items` → `flood_monitor`, nunca al revés). Esa paridad es el punto:
el flujo normal es elegir una escena con el listado y pasarle esa misma fecha
al pipeline, así que si los dos flags divergieran, el corte también. Un test
parametrizado en `test_cli.py` los compara en los dos scripts.

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
python list_s1_items.py --place Ovalle --end-date-utc 2025-01-15 -n 5
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

## flood_validation

Un segundo pipeline independiente en `src/flood_validation/` (paquete, a
diferencia del script único `flood_monitor.py`) que valida el producto de
susceptibilidad de anegamiento de `meteorologia-flood-projections` (repo
hermano, no vive acá) contra una capa de "anegamiento real" estimada con
sensores remotos públicos (Sentinel-1 SAR, Sentinel-2 óptico, fusionados
con plausibilidad de terreno y agua estacional). No modifica
`flood_monitor.py`; importa de ahí `load_aoi`/`geocode_place`/
`parse_end_date`/`EPOCH`/`slugify`/`stac_catalog`/`read_vh_db`/
`water_threshold`/`detect_flood`/`permanent_water_mask`/`slope_mask` — la
dirección del import es siempre `flood_validation` → `flood_monitor`,
nunca al revés, mismo patrón que ya sigue `list_s1_items.py`.

Historial completo de decisiones, hallazgos y verificaciones en vivo por
fase: `flood-projections-feature-real-flood.V2.0.md` (fuera de este repo,
en `/home/mherrera/Proyectos/meteorologia/`). Lo que sigue acá es la
guía de trabajo, no la bitácora completa.

### Setup

Mismos requisitos que arriba, más lo que ya trae `requirements.txt`:
`pyyaml` (config) y `pysheds` (HAND). `numpy` queda fijado a `<2.4` ahí
mismo: `pysheds` 0.5 llama a `np.in1d`, removido en numpy 2.4 (confirmado
empíricamente — 2.2.6 anda, 2.4.6 no; el repo hermano no lo pisó porque
corre con 2.2.6).

### Running

```bash
cd src
python -m flood_validation --aoi ../aoi/Chile-Region_de_Coquimbo-Punitaqui-Punitaqui-V2.geojson \
    --start-date-utc 2026-07-15 --end-date-utc 2026-07-22
python -m flood_validation --bbox -71.5449 -30.3021 -71.4409 -30.2123 --days 10 --end-date-utc 2026-07-22
python -m flood_validation --place Punitaqui --dry-run   # resuelve AOI/ventana/config, no procesa nada
```

`--start-date-utc`/`--end-date-utc`/`--local-time`/`--days` comparten
semántica con `flood_monitor.py` (mismo `parse_end_date`); a diferencia de
ahí, acá la ventana necesita **los dos extremos** — `--start-date-utc`
explícito, o `--days` hacia atrás desde `--end-date-utc` — porque esto
valida una ventana completa, no busca la imagen más reciente. Una fecha
pelada (`YYYY-MM-DD`) en `--start-date-utc` resuelve a las 00:00:00 (no a
las 23:59:59 que usa `--end-date-utc`): asimetría a propósito, para que el
día completo quede adentro de la ventana en los dos extremos.

`--output-dir`/`--config-dir` se resuelven contra la ubicación del paquete
(`cli.REPO_ROOT`, no el `cwd`) — a diferencia del `OUTPUT_DIR` relativo de
`flood_monitor.py`, correr desde `src/` o desde la raíz del repo da el
mismo resultado.

Salidas en `output/validation/` (default): `real_flood_s1-*`,
`real_flood_s2-*`, `real_flood_fused-*` (`.tif` + `.geojson`),
`validation_metrics-*.json`, `validation_summary-*.csv`,
`validation_report-*.md`, `flood_map-*.html`, `run_manifest-*.json` —
todos con el mismo tag de corrida (`<aoi>_<ventana>_<hex>_<timestamp
local>`, ver `main.build_run_tag`), así que ninguna corrida pisa a otra.

### Config: `config/regions.yaml` + `config/validation.yaml`

YAML en vez de constantes Python (`config.py`). `regions.yaml` clavea por
el string exacto de `--region`; una entrada `default` cubre cualquier
región no configurada, con aviso. Campos por región:
`susceptibility.source_root` (ruta al `outputs/<region>/` del repo
hermano, relativa a la raíz de **este** repo) + `sufijo_preferido`
(`gfs`/`ifs`), `hand_threshold_m` (15.0, del repo hermano),
`drainage_threshold_km2` (**0.05**, no el 15 km² del hermano — ver HAND
más abajo), `awei_variant`, `confidence_threshold`. `validation.yaml`:
`stac_collections`, `fusion_weights` por sensor, `confidence_tiers`
(cortes alta/media/baja) y `buffer_tolerance_m`.

### Architecture

Pipeline lineal en `main.py`, mismo espíritu que `flood_monitor.main()`:

1. **Config + AOI + ventana** (`cli.py`/`config.py`/`windows.py`) — config
   primero (lectura local barata, falla rápido si la región no está
   configurada, antes de tocar red con `--place`). `windows.resolve_window`
   arma `(start, end)`: `end` reusa `parse_end_date`; `start` viene de
   `--start-date-utc` o de `end - --days`.
2. **Sentinel-1** (`sar_layer.py`) — busca **todas** las escenas S1 de la
   ventana (no la más reciente, como `flood_monitor`), detecta cada una
   por separado contra una grilla de referencia compartida (la primera
   escena legible; agua permanente y pendiente se calculan una sola vez,
   no por escena) y unión (OR) de todas. Una escena que falla al leerse se
   saltea con aviso, no aborta la ventana.
3. **Sentinel-2** (`optical_layer.py`) — AWEI (`nsh`/`sh`/`both`,
   `--awei-variant`) como índice primario, no NDWI/MNDWI (AWEI ya cubre el
   caso de sombra de relieve que importa en Coquimbo), con máscara SCL de
   nube/sombra/nieve (clases `{0,1,3,8,9,10,11}` no votan). Una escena sin
   píxeles despejados se saltea con su cobertura real logueada, no en
   silencio.
4. **Terreno — HAND** (`terrain.py`) — `compute_hand`/
   `hand_implausible_mask`, mismo método pysheds que
   `meteorologia-flood-projections/src/inundaciones/terrain.py`
   (`fill_pits→fill_depressions→resolve_flats→flowdir→accumulation→
   compute_hand`) — leído ese código antes de escribir este, no adivinado.
   **No** reproyecta directo a la grilla del AOI como `slope_mask`:
   pysheds asigna dirección de flujo inválida a las celdas en el borde de
   la grilla que se le pasa, así que computa sobre una grilla con margen
   (`HAND_PAD_PX`, 30 px ≈ 900 m) y recorta al final — verificado contra
   un valle sintético (error < 0.2 mm en el interior). `drainage_
   threshold_km2` default **0.05 km²**, no el 15 km² calibrado del repo
   hermano: con solo ~900 m de margen, un cauce real casi nunca junta
   15 km² de área aguas arriba *dentro de ese margen* (verificado en vivo
   sobre Tongoy: 15 km² → solo 18.6% de celdas con HAND válido; barrido
   empírico sobre los mismos datos reales landeó en 0.05 km² → 81%
   válido). No es solo un ajuste numérico: reconoce quebradas chicas en
   vez de solo ríos con nombre, que es lo apropiado para este filtro en
   terreno árido.
5. **Agua estacional** (`seasonality.py`) — banda `seasonality` de JRC GSW
   (meses/año clasificados como agua, 0-12; valores reales confirmados en
   Tongoy: enteros 0-9 y 12), no solo `occurrence` (que ya usa
   `permanent_water_mask`, ocurrencia > 50% del registro entero): un canal
   de riego con 3-4 meses/año de agua puede tener `occurrence` baja pero
   `seasonality` alta — el caso intermedio que `permanent_water_mask` deja
   pasar.
6. **Fusión** (`fusion.py`) — combina los sensores disponibles sobre la
   grilla del que tenga más peso (`fusion_weights`), **renormalizando el
   peso solo entre los sensores con dato para esta ventana** — un sensor
   ausente no baja la confianza (punto de diseño explícitamente probado en
   `test_flood_validation_fusion.py`). Aplica HAND y agua estacional como
   exclusión dura, una sola vez sobre la grilla fusionada, no por sensor
   (evita calcular HAND/JRC dos veces). Cuantiza en tiers
   (`confidence_tiers`) → `real_flood_fused-*`.
7. **Susceptibilidad** (`susceptibility.py`) — el producto del repo
   hermano no es un archivo único: un raster binario por ciclo de
   pronóstico (`outputs/<region>/<sufijo>/mapa_anegamientos_<sufijo>_
   extension_<AAAAMMDD>_<HH>utc_<timestamp-local>.tif`, patrón confirmado
   contra archivos reales, no adivinado). Cada ciclo proyecta desde lluvia
   acumulada de 72 h *a partir* de su hora de inicio — `find_cycles`
   devuelve todos los que se solapan con la ventana pedida, más reciente
   primero; `resolve_susceptibility` usa el más reciente por default (o
   `--susceptibility <ruta>` como override incondicional). Rutas relativas
   en `source_root` se resuelven contra `cli.REPO_ROOT`, no el `cwd` — un
   bug real de esto (resolvía contra `Path.cwd()`, dando cero ciclos pese
   a que existían decenas) se encontró recién en la verificación en vivo,
   porque todos los tests usaban rutas absolutas.
8. **Métricas** (`metrics.py`) — matriz de confusión + Precision/Recall/
   F1/IoU/Cohen's Kappa/MCC (`None`, no un valor inventado, donde la
   fórmula no está definida — p. ej. Kappa/MCC con las dos capas
   completamente positivas, 0/0 matemático real), error de área señalado y
   absoluto, `buffered_agreement` (tolerancia espacial vía
   `scipy.ndimage.distance_transform_edt` — ya dependencia transitiva de
   `scikit-image`, no hace falta agregarla a mano), y desglose por bin de
   HAND (reusa el HAND crudo que expone `FusionResult.hand`, no lo
   recalcula). Sin barrido ROC/AUC: el producto es binario por ciclo, no
   hay nada continuo que threshold-sweepear dentro de un mismo ciclo — el
   barrido con sentido es a través de varios ciclos por lead time
   (`find_cycles` ya da la lista), dejado para cuando el reporte lo
   necesite.
9. **Reporte** (`report.py`) — mapa HTML (`leafmap`, mismo patrón CartoDB
   Voyager + satelital que `flood_monitor.save_outputs`, verificado el API
   real de `add_legend`/`add_geojson`/`add_gdf` antes de escribir código),
   CSV de una fila (`csv.DictWriter`, sin el desglose por HAND — no
   entra en una fila plana), y Markdown narrativo con metodología,
   métricas completas y una sección explícita de limitaciones conocidas.

### CLI: diferencias con `flood_monitor.py`

- `--start-date-utc` + `--end-date-utc`/`--days`: ventana con dos
  extremos, no un solo corte.
- `--susceptibility <ruta>`: override del ciclo auto-resuelto.
- `--awei-variant {nsh,sh,both}`: default `None` = usa el de
  `regions.yaml` para la región resuelta.
- No hay `--change`: la ventana ya hace unión multi-fecha por diseño, y un
  flag con ese nombre acá significaría otra cosa (comparar dos ventanas de
  validación entre sí, no dos escenas de una) — no se reusó el nombre a
  propósito, para no chocar semánticamente con el de `flood_monitor.py`.
- `--threshold`/`--min-area-px`/`--max-slope`: mismo nombre y semántica
  que `flood_monitor.py`, aplicados por escena dentro de `sar_layer.py`.

### Tests

Sufijo `test_flood_validation_*.py`, mismo split offline/`raster` de
arriba. Puntos no obvios:

- `test_flood_validation_terrain.py` — el test analítico es un valle en V
  sintético con `HAND_PAD_PX` de margen de cada lado, en las **dos**
  dimensiones (no solo filas): sin el margen en columnas también, el
  recorte final queda con índices fuera de rango.
- `test_flood_validation_main_raster.py` — `sar_layer.py`,
  `optical_layer.py`, `terrain.py` y `seasonality.py` importan cada uno su
  propia referencia a `stac_catalog`; los cinco (+`flood_monitor`) se
  mockean siempre juntos en este archivo. Pasó **dos veces** que un módulo
  nuevo se quedó sin mockear y la suite completa terminó pegándole a la
  Planetary Computer real (una vez, ~6 min en vez de segundos) — el
  docstring del archivo lo deja anotado para que no pase una tercera.
- `test_flood_validation_fusion.py` — `terrain`/`seasonality` se mockean
  directo (ya tienen sus propios tests contra STAC); `fusion.fuse` llama a
  `terrain.compute_hand` (no al conveniente `hand_implausible_mask`) para
  quedarse con el HAND crudo, así que los tests mockean ese, no el
  wrapper.
- `test_flood_validation_report.py` — los tests de `build_html_map` usan
  `pytest.importorskip("leafmap")`: el job `raster` de CI no lo instala a
  propósito (arrastra medio ecosistema de folium, y el mapa ya degrada
  suave sin él), así que esos dos tests se saltean ahí. CSV/Markdown no
  dependen de leafmap y corren siempre.
- La reconciliación de CI se verificó a mano, no se asumió: se armaron
  venvs que replican el install list exacto de cada job (no el venv de
  desarrollo, que tiene `requirements.txt` completo) y se corrió la
  selección de tests real en cada uno. Los conteos coinciden exactamente
  con lo que da el venv de desarrollo filtrando por marcador (133
  `offline`, 98 `raster`). Así se encontró el gap real de `pyyaml` en el
  job `raster` (ver la sección CI arriba) — invisible en local porque ese
  venv ya tenía todo `requirements.txt` instalado.

### Limitaciones conocidas

- **Fusión por sensor, no por píxel despejado**: un píxel nublado en
  Sentinel-2 vota "seco" en vez de "sin opinión" en `fusion.py`, porque la
  renormalización de peso es a nivel de sensor (¿tuvo esta ventana algún
  dato?), no a nivel de píxel (¿esta escena concreta estaba despejada
  acá?). En una semana de tormenta con nubosidad generalizada esto topea
  la confianza en "media" justo donde más importaría "alta" — confirmado
  en corridas reales sobre Tongoy y Punitaqui. Arreglarlo necesita que
  `sar_layer`/`optical_layer` devuelvan una máscara de validez por píxel,
  no solo `flood`, para que `fusion.py` excluya del denominador los
  píxeles sin opinión real de un sensor — un refinamiento real, no un bug,
  pendiente de confirmar si hace falta en la práctica.
- **Sin Dynamic World**: el toggle/config/aviso-de-pendiente ya existen
  (`region_cfg.datasets.dynamic_world`, `fusion_weights.dynamic_world`),
  pero el módulo (`dynamic_world.py`, import-guarded) no está escrito —
  necesita credenciales GEE no anónimas (factible bajo el tier gratuito
  según la investigación de la Fase 0 del plan, pero no configuradas en
  este entorno).
- **Sin ground truth de Copernicus EMS confirmado**: la búsqueda
  automática no encontró una activación para este evento, pero el portal
  es una SPA que resiste rastreo automatizado — inconcluso, no un "no"
  confirmado. Se procede asumiendo que no hay: "anegamiento real" es en sí
  una estimación multi-sensor, no una verdad de terreno independiente.
- **Sin agregación multi-corrida**: `write_csv_summary` escribe una fila
  por corrida, pensada para juntarse con las de otras corridas más
  adelante — ese batch en sí no existe todavía (fuera de scope de v1).

Las cuatro siguientes salieron de la calibración en vivo sobre Vallenar
(Región de Atacama, evento del 2026-07-19; corridas `2a1f800a`,
`c4aee33c`, `2a69a658`, `da0a76b5` en `output/validation/`):

- **La ventana debe anclarse al evento y ensancharse hacia adelante,
  nunca hacia atrás**: la unión OR de escenas es asimétrica frente al
  error — un falso positivo en *cualquier* escena entra al mapa completo.
  Una escena pre-evento (2026-07-16, pre-lluvia) aportó 15.9% del AOI de
  falsos positivos contra el 3.0% de la escena de la noche del evento;
  moverse de la ventana 15→20 a la 19→22 bajó la capa "real" de 14.0 a
  5.9 km² y subió Kappa/MCC de ~0.002 a ~0.05.
- **La resolución de ciclo "el más reciente que solapa" es la heurística
  equivocada para validar eventos**: con una ventana que se extiende
  después del evento (lo que la regla anterior recomienda), siempre gana
  un ciclo post-evento que proyecta desde después de la lluvia — sobre
  Vallenar resolvió el ciclo del 22 18utc con **0 px susceptibles** y las
  métricas colapsaron (tp=fp=0). El ciclo correcto es el último que
  *empieza antes* del evento; hoy se fuerza con `--susceptibility <ruta>`.
  Una futura opción `--event` derivaría ventana Y ciclo de una sola
  fecha, eliminando las dos trampas a la vez.
- **El tier "alta" pierde significado con un solo sensor** (extiende la
  limitación de fusión por sensor de arriba): con S2 nublado 94% que
  *participa*, todo S1 queda en "media"; con S2 nublado 99.7% que se
  *saltea*, la renormalización deja a S1 con peso 1.0 y todo sale "alta"
  (58,597 px alta / 0 media, corrida `2a69a658`). La misma situación
  física produce etiquetas opuestas según un umbral interno de
  participación. Regla candidata: "alta" requiere ≥2 sensores con dato
  real (distinguible en `FusionResult` sin tocar la renormalización).
- **Artefactos permanentes por geometría de órbita**: los cerros de
  regolito liso al NE de Vallenar son oscuros (< -22 dB) en la órbita
  relativa 156 descendente *siempre* — pre y post lluvia — y ningún
  umbral global los separa de agua; la unión multi-órbita acumula los
  artefactos de cada geometría. Mitigado con `drainage_threshold_km2:
  0.5` por región (crestas quedan con HAND alto sobre cauces reales;
  validez apenas bajó de 99.9% a 98.5%). El arreglo de fondo es de
  diseño, no de calibración: exigir persistencia (≥2 escenas) para el
  tier alto, o una referencia pre-evento por órbita (el `--change` de
  `flood_monitor`, que este pipeline no tiene) — la misma escena
  pre-evento que contamina la unión serviría de referencia para restar.
