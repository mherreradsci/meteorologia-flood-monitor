# Monitoreo de anegamiento casi en tiempo real (Sentinel-1)

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
# Coquimbo, Chile; cambiá el contexto con --region):
python flood_monitor.py --place Tongoy
python flood_monitor.py --place Ovalle --buffer-km 8
python flood_monitor.py --place "Quilpué" --region "Región de Valparaíso, Chile"

# En zonas urbanas o agrícolas, activá la detección de cambio entre dos
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
# de la más reciente (útil para comparar contra otra fuente en esa fecha):
python flood_monitor.py --place Tongoy --end-date 2025-03-14
python flood_monitor.py --place Tongoy --end-date 2025-03-14 --days 15

# Opciones útiles:
python flood_monitor.py --aoi mi_zona.geojson --days 15 --threshold -18
```

Salidas en `./output/`: `flood_mask_*.tif`, `flood_mask_*.geojson`,
`quicklook_*.png` y `flood_map_*.html` (abrir en el navegador).

## Tests

```bash
pip install -r requirements-dev.txt   # solo pytest
pytest                  # desde la raíz del repo (~20 s, consulta la API)
pytest -m "not network"  # todo lo que no necesita internet (~2 s)
pytest -m raster         # solo los de GeoTIFF sintéticos
```

103 tests. Cubren la resolución del AOI (los tres modos de entrada y el buffer
del geocodificador), el parseo de fechas, la ventana de búsqueda, la lectura y
conversión a dB, la detección (umbral de Otsu y su recorte, área mínima,
criterio de cambio), las dos máscaras (ocurrencia JRC + dilatación, pendiente
sobre el DEM), la escritura de salidas —incluida la reproyección del GeoJSON a
EPSG:4326— y la selección de escena contra Planetary Computer.

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
  Si tu zona tiene poca agua, Otsu puede fallar: fijá `--threshold -18` y
  ajustá comparando el quicklook con el terreno que conocés.
- **Falsos positivos** típicos: sombras de relieve, asfalto/pistas, suelo muy
  liso y seco. El filtro `--min-area-px` ayuda, y la máscara de pendiente
  (Copernicus DEM GLO-30) descarta terreno con más de `--max-slope` grados
  (default 5°; `--max-slope 0` la desactiva).
- **Latencia real**: Sentinel-1 revisita cada ~2-6 días según la zona (con S-1A
  y S-1C operativos). El script informa cuántos días tiene la imagen usada.
- **Fecha explícita**: `--end-date YYYY-MM-DD` corre el pipeline "como si fuera"
  esa fecha: busca hacia atrás desde el corte (23:59:59 UTC de ese día) dentro
  de la ventana de `--days`. Si no hay escena en esa ventana el script falla en
  vez de traer una imagen lejana, para no validar contra una fecha equivocada:
  subí `--days` o movéla. Para ver qué escenas hay disponibles antes de correr,
  usá `list_s1_items.py --end-date ...`.
- **Validación**: comparar contra Copernicus Global Flood Monitoring (GFM):
  https://global-flood.emergency.copernicus.eu/
