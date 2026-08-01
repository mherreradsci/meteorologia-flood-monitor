"""report.py: mapa HTML, resumen CSV y reporte Markdown. Marcado `raster`
(el `template` de `ReportContext` es una grilla de rioxarray), sin red.

`build_html_map` necesita leafmap, que el job `raster` de CI deliberadamente
NO instala (mismo motivo que ya documenta CLAUDE.md para flood_monitor.py:
arrastra medio ecosistema de folium) — sus tests se saltean ahí con
`importorskip`, igual que el propio mapa ya degrada solo sin leafmap en
producción. CSV y Markdown no dependen de leafmap y corren siempre.
"""

from __future__ import annotations

import csv as csv_module
import json

import numpy as np
import pytest

pytest.importorskip("rioxarray")
pytest.importorskip("geopandas")

from flood_validation import report  # noqa: E402
from flood_validation.fusion import FusionResult  # noqa: E402
from helpers import utc  # noqa: E402
from raster_helpers import grilla  # noqa: E402

pytestmark = pytest.mark.raster

LADO = 20


def _contexto(tmp_path, *, con_susceptibilidad=True, con_metricas=True):
    template = grilla(np.zeros((LADO, LADO)))
    tier = np.zeros((LADO, LADO), dtype="uint8")
    tier[2:6, 2:6] = 3   # alta
    tier[10:12, 10:12] = 1   # baja

    from flood_validation import outputs
    paths = outputs.write_tiered_geotiff_geojson(
        template, tier, tmp_path, "tag_de_prueba", prefix="real_flood_fused",
        tier_labels=report.TIER_LABELS)

    fused = FusionResult(
        confidence=(tier > 0).astype("float32"), tier=tier, template=template,
        sensors_used=["sentinel1", "sentinel2"], terrain_excluded_px=3,
        seasonal_excluded_px=1, hand=np.full((LADO, LADO), 2.0, dtype="float32"))

    susceptible_mask = None
    ciclo = None
    metricas = None
    if con_susceptibilidad:
        susceptible_mask = np.zeros((LADO, LADO), dtype=bool)
        susceptible_mask[2:6, 2:6] = True  # coincide con el tier alto
        ciclo = {"cycle_path": "/tmp/ciclo.tif", "cycle_sufijo": "gfs",
                 "cycle_utc": "2026-07-15T00:00:00+00:00"}
        if con_metricas:
            from flood_validation import metrics as metrics_mod

            resultado = metrics_mod.evaluate(
                susceptible_mask, tier > 0, pixel_area_km2=0.0009,
                resolution_m=30.0, hand=fused.hand)
            metricas = metrics_mod.evaluation_to_dict(resultado)

    return report.ReportContext(
        tag="tag_de_prueba", geom={"type": "Polygon", "coordinates": [[
            [-71.55, -30.30], [-71.44, -30.30], [-71.44, -30.21],
            [-71.55, -30.21], [-71.55, -30.30]]]},
        bbox=(-71.55, -30.30, -71.44, -30.21),
        region="Región de Coquimbo, Chile", place="Tongoy",
        start=utc(2026, 7, 15), end=utc(2026, 7, 22),
        template=template,
        sar_acquisitions=[{"item_id": "S1_a"}], sar_skipped=[],
        optical_acquisitions=[{"item_id": "S2_a"}], optical_skipped=["S2_nube"],
        fused=fused, fused_geojson_path=paths["geojson"],
        susceptibility_cycle=ciclo, susceptible_mask=susceptible_mask,
        metrics=metricas), template


# --------------------------------------------------------------------------- #
# build_html_map
# --------------------------------------------------------------------------- #
def test_build_html_map_escribe_un_archivo_con_las_capas(tmp_path):
    pytest.importorskip("leafmap")
    ctx, _ = _contexto(tmp_path)

    html_path = report.build_html_map(ctx, tmp_path)

    assert html_path is not None
    assert html_path.exists()
    contenido = html_path.read_text(encoding="utf-8")
    assert "Tongoy" in contenido  # panel de metadata
    assert len(contenido) > 1000  # no es un archivo vacío/roto
    # Ventana con hora y offset explícitos (no solo la fecha): una ventana
    # de menos de un día se veía igual que una de varios en el popup.
    assert "2026-07-15T00:00:00+00:00" in contenido
    assert "2026-07-22T00:00:00+00:00" in contenido


def test_build_html_map_sin_susceptibilidad_no_rompe(tmp_path):
    pytest.importorskip("leafmap")
    ctx, _ = _contexto(tmp_path, con_susceptibilidad=False)

    html_path = report.build_html_map(ctx, tmp_path)

    assert html_path is not None
    assert html_path.exists()


# --------------------------------------------------------------------------- #
# write_csv_summary
# --------------------------------------------------------------------------- #
def test_write_csv_summary_tiene_una_fila_con_las_metricas(tmp_path):
    ctx, _ = _contexto(tmp_path)

    csv_path = report.write_csv_summary(ctx, tmp_path)

    assert csv_path.exists()
    with csv_path.open(encoding="utf-8") as f:
        filas = list(csv_module.DictReader(f))
    assert len(filas) == 1
    fila = filas[0]
    assert fila["run_tag"] == "tag_de_prueba"
    assert fila["sensors_used"] == "sentinel1+sentinel2"
    assert fila["susceptibility_cycle_sufijo"] == "gfs"
    assert float(fila["tp"]) == 16  # 4x4 de acuerdo en el bloque alto


def test_write_csv_summary_sin_metricas_deja_columnas_vacias(tmp_path):
    ctx, _ = _contexto(tmp_path, con_susceptibilidad=False)

    csv_path = report.write_csv_summary(ctx, tmp_path)

    with csv_path.open(encoding="utf-8") as f:
        fila = next(csv_module.DictReader(f))
    assert fila["tp"] == ""
    assert fila["susceptibility_cycle_sufijo"] == ""


# --------------------------------------------------------------------------- #
# write_markdown_report
# --------------------------------------------------------------------------- #
def test_write_markdown_report_incluye_metricas_y_caveats(tmp_path):
    ctx, _ = _contexto(tmp_path)

    md_path = report.write_markdown_report(ctx, tmp_path, extra_paths={
        "GeoTIFF fusionado": tmp_path / "real_flood_fused_tag_de_prueba.tif",
    })

    assert md_path.exists()
    texto = md_path.read_text(encoding="utf-8")
    assert "propensión, no una predicción binaria" in texto
    assert "Cohen's Kappa" in texto
    assert "Desglose por HAND" in texto
    assert "Limitaciones conocidas" in texto
    assert "real_flood_fused_tag_de_prueba.tif" in texto
    assert "2026-07-15T00:00:00+00:00" in texto
    assert "2026-07-22T00:00:00+00:00" in texto


def test_write_markdown_report_sin_comparacion_lo_dice_explicito(tmp_path):
    ctx, _ = _contexto(tmp_path, con_susceptibilidad=False)

    md_path = report.write_markdown_report(ctx, tmp_path, extra_paths={})

    texto = md_path.read_text(encoding="utf-8")
    assert "Sin comparación" in texto
