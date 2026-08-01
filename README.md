# Monitoreo de anegamiento casi en tiempo real (Sentinel-1)

[![tests](https://github.com/mherreradsci/meteorologia-flood-monitor/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/mherreradsci/meteorologia-flood-monitor/actions/workflows/tests.yml)

Detecta anegamiento con la banda VH de Sentinel-1 RTC (Microsoft Planetary
Computer, sin cuenta ni API key), enmascara agua permanente con JRC Global
Surface Water y genera GeoTIFF, GeoJSON, quicklook PNG y mapa HTML interactivo.

## Instalación (Ubuntu 22.04, Python 3.12)

```bash
sudo apt update && sudo apt install -y gdal-bin libgdal-dev python3-dev python3-venv
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
# Con un punto de interés por nombre (por defecto busca en la Región de
# Coquimbo, Chile; cambia el contexto con --region):
python flood_monitor.py --place Tongoy
python flood_monitor.py --place Ovalle --buffer-km 8
python flood_monitor.py --place "Quilpué" --region "Región de Valparaíso, Chile"

# En zonas urbanas o agrícolas, activa la detección de cambio entre dos
# fechas (elimina falsos positivos de parcelas lisas, pavimento y sombras):
python flood_monitor.py --place "La Serena" --change

# Con bounding box (xmin ymin xmax ymax, lon/lat):
python flood_monitor.py --bbox -58.65 -34.75 -58.30 -34.45

# Con un GeoJSON de tu AOI (dibujalo en https://geojson.io). La carpeta
# aoi/ tiene ejemplos de referencia con nombre <País>-<Región>-<Comuna>-
# <Localidad>.geojson (correlo desde src/, por eso el ../):
python flood_monitor.py --aoi mi_zona.geojson
python flood_monitor.py --aoi ../aoi/Chile-Region_de_Coquimbo-La_huiguera-Chungungo.geojson

# Validar una fecha pasada: usa la última imagen anterior al corte, en vez
# de la más reciente (útil para comparar contra otra fuente en esa fecha).
# El corte se interpreta en UTC salvo que agregues --local-time:
python flood_monitor.py --place Tongoy --end-date-utc 2025-03-14
python flood_monitor.py --place Tongoy --end-date-utc 2025-03-14 --days 15
python flood_monitor.py --place Tongoy --end-date-utc 2025-03-14 --local-time

# Opciones útiles:
python flood_monitor.py --aoi mi_zona.geojson --days 15 --threshold -18
```

Salidas en `./output/`: `flood_mask_*.tif`, `flood_mask_*.geojson`,
`quicklook_*.png` y `flood_map_*.html` (abrir en el navegador).

Cada archivo lleva un sufijo que identifica la corrida —zona, fecha de la
imagen y timestamp local—, así que dos corridas nunca se pisan. Cómo se nombra
la zona depende de cómo la pediste:

| entrada | ejemplo de sufijo |
|---|---|
| `--place Tongoy` | `Región_de_Coquimbo,_Chile_Tongoy_20260724T232759Z_b5442c3e_20260726T011952` |
| `--aoi ../aoi/Chile-Region_de_Coquimbo-Punitaqui-Punitaqui.geojson` | `aoi_Chile-Region_de_Coquimbo-Punitaqui-Punitaqui_20260724T232759Z_...` |
| `--bbox -71.32 -30.85 -71.21 -30.80` | `bbox_-71.3200_-30.8500_-71.2100_-30.8000_20260724T232759Z_...` |

Con `--aoi` el nombre sale del GeoJSON (sin ruta ni extensión): es más legible
que sus coordenadas y distingue dos AOI que compartan envolvente.

## Zonas horarias: `--end-date-utc` y `--local-time`

**Sentinel-1 fecha todo en UTC**, y este script también: todo lo que imprime y
todo lo que le pide a la API está en UTC. Por eso el flag se llama
`--end-date-utc`: el nombre dice en qué zona se interpreta lo que escribes.

Con `--local-time`, la misma fecha se interpreta en la zona horaria **de la
máquina donde corres el script**. Ejemplo en Chile (`-04` en invierno):

| comando | corte efectivo |
|---|---|
| `--end-date-utc 2026-07-16` | 2026-07-16 **23:59:59 UTC** (= 19:59 en Chile) |
| `--end-date-utc 2026-07-16 --local-time` | 2026-07-16 23:59:59 en Chile (= **2026-07-17 03:59:59 UTC**) |
| `--end-date-utc 2026-07-16T20:00:00-04:00` | 2026-07-17 00:00:00 UTC |

Las reglas, en orden de prioridad:

1. **Si la fecha trae offset explícito** (`2026-07-16T20:00:00-04:00`), manda
   ese offset y `--local-time` se ignora. Ya dijiste en qué zona estabas.
2. **Si no, y pasas `--local-time`**, se interpreta como hora local, aplicando
   el horario de verano *vigente en esa fecha* — no el de hoy. En Chile, una
   fecha de enero se resuelve con `-03` y una de julio con `-04`, aunque las
   corras el mismo día.
3. **Si no**, se interpreta como UTC. Es el comportamiento por defecto y el que
   tenía el script desde siempre.

Un `YYYY-MM-DD` pelado siempre resuelve al **final del día** (23:59:59) en la
zona que corresponda, para que las escenas de esa misma fecha entren en la
ventana.

Con `--local-time` el script imprime la equivalencia, porque el corte suele
caer en otro día UTC que el que escribiste:

```
[+] Corte local 2026-07-16 23:59:59 (-0400) = 2026-07-17 03:59:59 UTC
```

**¿Cuándo importa de verdad?** Cuando validas contra una app que muestra hora
local. Sobre la Región de Coquimbo, Sentinel-1 pasa cerca de las 10:02 UTC
(06:02 local) y de las 23:28 UTC (19:28 local). Esa segunda pasada cae dentro
de las 4 horas que separan un corte de otro, así que `--local-time` puede
cambiar qué escena se usa. `--local-time` **no** afecta el default (sin fecha,
el corte es "ahora", que es el mismo instante en cualquier zona) — si lo pasas
solo, el script te avisa que no hizo nada.

> El flag anterior se llamaba `--end-date` y se sigue aceptando como alias, así
> que los `crontab` existentes no se rompen. Interpretaba la fecha en UTC, o
> sea que se comporta igual que `--end-date-utc`.

## Tests

```bash
pip install -r requirements-dev.txt   # solo pytest
pytest                  # desde la raíz del repo (~20 s, consulta la API)
pytest -m "not network"  # todo lo que no necesita internet (~2 s)
pytest -m raster         # solo los de GeoTIFF sintéticos
```

116 tests. Cubren la resolución del AOI (los tres modos de entrada y el buffer
del geocodificador), el parseo de fechas —incluidas las dos zonas de
`--local-time` y el horario de verano—, la ventana de búsqueda, la lectura y
conversión a dB, la detección (umbral de Otsu y su recorte, área mínima,
criterio de cambio), las dos máscaras (ocurrencia JRC + dilatación, pendiente
sobre el DEM), la escritura de salidas —incluida la reproyección del GeoJSON a
EPSG:4326 y el nombrado de los archivos en los tres modos— y la selección de
escena contra Planetary Computer.

**No** validan la calidad de la detección sobre imágenes reales: que el mapa
sea correcto para tu zona se sigue viendo con el quicklook y comparando con
GFM.

## Automatización (cada 6 horas)

```bash
crontab -e
# agregar:
0 */6 * * * cd /ruta/flood-monitor && ./venv/bin/python flood_monitor.py --aoi mi_zona.geojson >> monitor.log 2>&1
```

## Notas de calibración

- **Umbral**: por defecto usa Otsu (automático, acotado a [-25, -14] dB).
  Si tu zona tiene poca agua, Otsu puede fallar: fija `--threshold -18` y
  ajusta comparando el quicklook con el terreno que conoces.
- **Falsos positivos** típicos: sombras de relieve, asfalto/pistas, suelo muy
  liso y seco. El filtro `--min-area-px` ayuda, y la máscara de pendiente
  (Copernicus DEM GLO-30) descarta terreno con más de `--max-slope` grados
  (default 5°; `--max-slope 0` la desactiva).
- **Latencia real**: Sentinel-1 revisita cada ~2-6 días según la zona (con S-1A
  y S-1C operativos). El script informa cuántos días tiene la imagen usada.
- **Fecha explícita**: `--end-date-utc YYYY-MM-DD` corre el pipeline "como si
  fuera" esa fecha: busca hacia atrás desde el corte (23:59:59 UTC de ese día,
  o hora local con `--local-time`; ver "Zonas horarias" arriba) dentro de la
  ventana de `--days`. Si no hay escena en esa ventana el script falla en vez
  de traer una imagen lejana, para no validar contra una fecha equivocada:
  sube `--days` o muévela. Para ver qué escenas hay disponibles antes de correr,
  usa `list_s1_items.py --end-date-utc ...`, que acepta los mismos dos flags
  con idéntica semántica.
- **Validación**: comparar contra Copernicus Global Flood Monitoring (GFM):
  https://global-flood.emergency.copernicus.eu/

## flood_validation: validar susceptibilidad contra anegamiento real

Pipeline aparte en `src/flood_validation/` (no modifica lo de arriba) que
compara el producto de susceptibilidad de `meteorologia-flood-projections`
(repo hermano) contra una capa de anegamiento real estimada fusionando
Sentinel-1 y Sentinel-2, con filtros de plausibilidad de terreno (HAND) y
agua estacional/de riego.

```bash
cd src
python -m flood_validation --aoi ../aoi/Chile-Region_de_Coquimbo-Punitaqui-Punitaqui-V2.geojson \
    --start-date-utc 2026-07-15 --end-date-utc 2026-07-22
```

Salidas en `output/validation/`: GeoTIFF/GeoJSON por sensor y fusionado,
`validation_metrics-*.json` (matriz de confusión, Precision/Recall/F1/IoU/
Kappa/MCC, error de área, desglose por HAND), `validation_summary-*.csv`,
`validation_report-*.md` y `flood_map-*.html` (mapa interactivo con capas
por tier de confianza, susceptibilidad y acuerdo/desacuerdo).

### Métricas: matriz de confusión

Las métricas de `validation_metrics-*.json` comparan píxel a píxel la capa de
susceptibilidad (predicción) contra el anegamiento real estimado (referencia).
Cada píxel cae en una de cuatro celdas de la **matriz de confusión**:

| | Real: inundado | Real: no inundado |
|---|---|---|
| **Predicho: inundado** | TP (verdadero positivo) | FP (falso positivo) |
| **Predicho: no inundado** | FN (falso negativo) | TN (verdadero negativo) |

- **TP** — píxeles inundados que la predicción marcó correctamente.
- **FP** — falsa alarma: predicho inundado, pero seco en la referencia.
- **FN** — omisión: inundado en la referencia, pero la predicción no lo vio.
- **TN** — seco en ambas capas.

De ahí derivan las métricas del JSON:

- **Precision** = TP / (TP + FP) — de lo predicho como inundado, ¿cuánto era
  real?
- **Recall** = TP / (TP + FN) — de lo realmente inundado, ¿cuánto se detectó?
- **F1** = media armónica de Precision y Recall; equilibra falsas alarmas y
  omisiones en un solo número (1 = perfecto, 0 = sin acierto).
- **IoU** (Intersection over Union, índice de Jaccard) = TP / (TP + FP + FN) —
  solapamiento entre ambas capas, ignorando los TN: en un AOI mayormente seco
  los TN dominan e inflarían cualquier métrica que los cuente.
- **Kappa de Cohen** y **MCC** — acuerdo corregido por azar; útiles justamente
  porque la clase "inundado" es minoritaria. Valen `None` cuando la fórmula es
  un 0/0 real (p. ej. ambas capas completamente positivas), no un valor
  inventado.

Detalle de arquitectura, config (`config/regions.yaml`/`validation.yaml`),
convenciones de test y limitaciones conocidas: ver la sección
`flood_validation` de `CLAUDE.md`.

## Glosario de siglas

### Sensores y teledetección

| Sigla | Significado |
|---|---|
| SAR | Synthetic Aperture Radar — radar de apertura sintética (Sentinel-1) |
| VH | Polarización cruzada (emite Vertical, recibe Horizontal) — banda SAR usada para detectar agua |
| RTC | Radiometric Terrain Correction — la variante de Sentinel-1 usada (`sentinel-1-rtc`) |
| dB | Decibel — escala logarítmica del retorno (backscatter) SAR |
| SCL | Scene Classification Layer — máscara de nube/sombra/nieve de Sentinel-2 |
| AWEI | Automated Water Extraction Index — índice de agua sobre Sentinel-2 (variantes `nsh`/`sh`) |
| NDWI / MNDWI | (Modified) Normalized Difference Water Index — índices de agua alternativos a AWEI |

### Datasets de referencia

| Sigla | Significado |
|---|---|
| DEM | Digital Elevation Model — modelo digital de elevación (Copernicus GLO-30) |
| JRC | Joint Research Centre (Comisión Europea) — autor del dataset GSW |
| GSW | (JRC) Global Surface Water — ocurrencia y estacionalidad de agua superficial |
| HAND | Height Above Nearest Drainage — altura sobre el drenaje más cercano; filtro de plausibilidad de terreno |
| GFM | (Copernicus) Global Flood Monitoring — producto de referencia para validación visual |
| EMS | (Copernicus) Emergency Management Service — activaciones de emergencia usables como ground truth |
| GEE | Google Earth Engine — requerido por Dynamic World (no implementado) |

### Geoespacial

| Sigla | Significado |
|---|---|
| AOI | Area of Interest — polígono o bbox que define la zona a procesar |
| bbox | Bounding box — rectángulo `xmin ymin xmax ymax` en lon/lat |
| POI | Point of Interest — punto geocodificado por `--place` |
| EPSG | Código de sistema de referencia de coordenadas (EPSG:4326 = lat/lon WGS84) |
| UTM | Universal Transverse Mercator — proyección en que se calcula la máscara |
| OSM | OpenStreetMap — fuente del geocodificador Nominatim (`--place`) |
| STAC | SpatioTemporal Asset Catalog — API de catálogo de Planetary Computer |
| GDAL | Geospatial Data Abstraction Library — base de rasterio/rioxarray |

### Métricas de validación

Ver la sección "Métricas: matriz de confusión" para las definiciones completas.

| Sigla | Significado |
|---|---|
| TP / TN | True Positive / True Negative — aciertos (inundado / seco) |
| FP / FN | False Positive / False Negative — falsa alarma / omisión |
| F1 | Media armónica de Precision y Recall |
| IoU | Intersection over Union — índice de Jaccard |
| MCC | Matthews Correlation Coefficient — correlación robusta a clases desbalanceadas |

### Tiempo e infraestructura

| Sigla | Significado |
|---|---|
| UTC | Coordinated Universal Time — zona horaria de todo el pipeline |
| DST | Daylight Saving Time — horario de verano (afecta `--local-time`) |
| CI | Continuous Integration — los jobs de GitHub Actions del repo |
