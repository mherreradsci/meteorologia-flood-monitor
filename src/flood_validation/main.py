"""main.py — orquestación de flood_validation.

Fase 1 (fundamentos): resuelve AOI, ventana y config, arma el tag de la
corrida y escribe el manifiesto de reproducibilidad — solo `--dry-run`, sin
procesar rásters. Las fases siguientes agregan las capas de sensores
(Sentinel-1, Sentinel-2, Dynamic World opcional), la fusión y la
comparación real contra la capa de susceptibilidad.
"""

from __future__ import annotations

import hashlib
import json
import platform
import secrets
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from flood_monitor import load_aoi, slugify

from . import cli, config, windows


def _config_hash(paths: list[Path]) -> str:
    """Hash corto de los YAML de config, para el manifiesto: dos corridas
    con distinto hash usaron distintos umbrales/pesos, aunque el resto de
    los argumentos sea igual."""
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def build_run_tag(args, bbox, start: datetime, end: datetime) -> str:
    """Mismo espíritu que build_run_tag de flood_monitor.py (secuencia
    aleatoria + timestamp local para no pisar corridas previas), pero
    fechado por la ventana de validación en vez de la fecha de una sola
    imagen — acá no hay una escena única, hay una ventana multi-sensor."""
    if args.place:
        region = slugify(args.region)
        place = slugify(args.place)
    elif args.aoi:
        region = "aoi"
        place = slugify(args.aoi.stem)
    else:
        region = "bbox"
        place = "_".join(f"{v:.4f}" for v in bbox)
    window = f"{start:%Y%m%d}-{end:%Y%m%d}"
    sequence = secrets.token_hex(4)
    local_ts = f"{datetime.now():%Y%m%dT%H%M%S}"
    return f"{region}_{place}_{window}_{sequence}_{local_ts}"


def main(argv: list[str] | None = None) -> None:
    args = cli.parse_args(argv)

    # Config primero: es una lectura local barata, y falla rápido si la
    # región no está configurada — antes de tocar la red con --place
    # (geocodificación) o hacer ningún otro trabajo.
    regions_path = args.config_dir / "regions.yaml"
    validation_path = args.config_dir / "validation.yaml"
    regions_cfg = config.load_regions_config(regions_path)
    config.load_validation_config(validation_path)  # valida que parsee bien
    region_cfg = config.resolve_region_config(args.region, regions_cfg)
    print(f"[+] Config de región resuelta: zoom={region_cfg.zoom}, "
          f"HAND≤{region_cfg.hand_threshold_m} m, AWEI "
          f"{region_cfg.awei_variant}, umbral de confianza "
          f"{region_cfg.confidence_threshold}")

    geom, bbox = load_aoi(args)
    print(f"[+] AOI bbox: {tuple(round(v, 4) for v in bbox)}")

    start, end = windows.resolve_window(args)
    print(f"[+] Ventana de validación: {start:%Y-%m-%d %H:%M:%S} a "
          f"{end:%Y-%m-%d %H:%M:%S} UTC ({(end - start).days} días)")

    susceptibility_path = args.susceptibility
    if susceptibility_path is not None:
        print(f"[+] Susceptibilidad: ruta explícita {susceptibility_path}")
    elif region_cfg.susceptibility.source_root:
        print(f"[+] Susceptibilidad: se resolverá desde "
              f"{region_cfg.susceptibility.source_root} (sufijo preferido: "
              f"{region_cfg.susceptibility.sufijo_preferido}) — la "
              f"resolución de ciclo llega en la Fase 5.")
    else:
        print("[!] Sin --susceptibility ni source_root configurado para "
              "esta región: no habrá con qué comparar en fases futuras.")

    print("[+] Sensores configurados — Sentinel-1: "
          f"{'on' if region_cfg.datasets.sentinel1 else 'off'}, "
          f"Sentinel-2: {'on' if region_cfg.datasets.sentinel2 else 'off'}, "
          f"Dynamic World: "
          f"{'on' if region_cfg.datasets.dynamic_world else 'off'} "
          "(disponibilidad real por red/credenciales se verifica en las "
          "fases que agregan cada sensor).")

    if not args.dry_run:
        raise SystemExit(
            "[!] Todavía no implementado: por ahora solo --dry-run "
            "funciona (Fase 1 — fundamentos). Las fases siguientes agregan "
            "las capas de sensores, la fusión y la comparación real.")

    tag = build_run_tag(args, bbox, start, end)
    print(f"[+] ID de corrida: {tag}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_tag": tag,
        "dry_run": True,
        "aoi": {
            "mode": ("place" if args.place else
                    "aoi" if args.aoi else "bbox"),
            "bbox": [round(v, 6) for v in bbox],
            "place": args.place,
            "region": args.region,
            "aoi_file": str(args.aoi) if args.aoi else None,
        },
        "window": {
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),
        },
        "susceptibility": {
            "explicit_path": (str(susceptibility_path)
                              if susceptibility_path else None),
            "source_root": region_cfg.susceptibility.source_root,
            "sufijo_preferido": region_cfg.susceptibility.sufijo_preferido,
        },
        "sensors_enabled": asdict(region_cfg.datasets),
        "config_hash": _config_hash([regions_path, validation_path]),
        "python_version": platform.python_version(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = args.output_dir / f"run_manifest-{tag}.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"[+] Manifiesto: {manifest_path}")
    print("[✓] Dry-run listo (Fase 1 — sin procesamiento de rásters).")


if __name__ == "__main__":
    main()
