"""susceptibility.py: resolución de qué ciclo de pronóstico usar. Sin red,
sin GDAL — `find_cycles`/`resolve_susceptibility` son puro pathlib/regex/
datetime, así que corren en el job offline (el módulo no importa
rioxarray a nivel de tope, solo dentro de `load_susceptibility`).
"""

from __future__ import annotations

from datetime import datetime, timezone

from flood_validation import susceptibility


def utc(y, m, d, hh=0):
    return datetime(y, m, d, hh, tzinfo=timezone.utc)


def _tocar(dir_, nombre):
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / nombre).write_bytes(b"")


# --------------------------------------------------------------------------- #
# find_cycles
# --------------------------------------------------------------------------- #
def test_reconoce_el_patron_real_del_repo_hermano(tmp_path):
    gfs = tmp_path / "gfs"
    _tocar(gfs, "mapa_anegamientos_gfs_extension_20260715_00utc_20260715-010203.tif")

    ciclos = susceptibility.find_cycles(tmp_path, "gfs", utc(2026, 7, 15),
                                        utc(2026, 7, 16))

    assert len(ciclos) == 1
    assert ciclos[0].sufijo == "gfs"
    assert ciclos[0].cycle_utc == utc(2026, 7, 15, 0)


def test_ignora_archivos_que_no_matchean(tmp_path):
    gfs = tmp_path / "gfs"
    # El HTML pareado (sin "_extension") no es el raster.
    _tocar(gfs, "mapa_anegamientos_gfs_20260715_00utc_20260715-010203.html")
    _tocar(gfs, "otra_cosa.tif")

    ciclos = susceptibility.find_cycles(tmp_path, "gfs", utc(2026, 7, 1),
                                        utc(2026, 7, 30))

    assert ciclos == []


def test_directorio_del_sufijo_inexistente_devuelve_vacio(tmp_path):
    assert susceptibility.find_cycles(tmp_path, "gfs", utc(2026, 7, 1),
                                      utc(2026, 7, 2)) == []


def test_filtra_por_solape_de_la_ventana_de_proyeccion_72h(tmp_path):
    gfs = tmp_path / "gfs"
    # Ciclo del 01-jul 00z: proyecta hasta el 04-jul 00z, se solapa.
    _tocar(gfs, "mapa_anegamientos_gfs_extension_20260701_00utc_20260701-010000.tif")
    # Ciclo del 10-jul 00z: proyecta hasta el 13-jul, no se solapa para nada.
    _tocar(gfs, "mapa_anegamientos_gfs_extension_20260710_00utc_20260710-010000.tif")

    ciclos = susceptibility.find_cycles(tmp_path, "gfs", utc(2026, 7, 2),
                                        utc(2026, 7, 3))

    assert len(ciclos) == 1
    assert ciclos[0].cycle_utc == utc(2026, 7, 1, 0)


def test_ordena_del_mas_reciente_al_mas_antiguo(tmp_path):
    gfs = tmp_path / "gfs"
    _tocar(gfs, "mapa_anegamientos_gfs_extension_20260701_00utc_20260701-010000.tif")
    _tocar(gfs, "mapa_anegamientos_gfs_extension_20260702_06utc_20260702-070000.tif")

    ciclos = susceptibility.find_cycles(tmp_path, "gfs", utc(2026, 6, 25),
                                        utc(2026, 7, 5))

    assert [c.cycle_utc for c in ciclos] == [utc(2026, 7, 2, 6), utc(2026, 7, 1, 0)]


def test_sufijo_distingue_gfs_de_ifs(tmp_path):
    gfs = tmp_path / "gfs"
    ifs = tmp_path / "ifs"
    _tocar(gfs, "mapa_anegamientos_gfs_extension_20260701_00utc_20260701-010000.tif")
    _tocar(ifs, "mapa_anegamientos_ifs_extension_20260701_00utc_20260701-010000.tif")

    ciclos = susceptibility.find_cycles(tmp_path, "ifs", utc(2026, 6, 28),
                                        utc(2026, 7, 3))

    assert len(ciclos) == 1
    assert ciclos[0].sufijo == "ifs"


# --------------------------------------------------------------------------- #
# resolve_susceptibility
# --------------------------------------------------------------------------- #
def test_ruta_explicita_gana_siempre(tmp_path):
    explicita = tmp_path / "mi_capa.tif"

    ciclo = susceptibility.resolve_susceptibility(
        explicit_path=explicita, source_root=str(tmp_path),
        sufijo_preferido="gfs", start=utc(2026, 7, 1), end=utc(2026, 7, 2))

    assert ciclo.path == explicita
    assert ciclo.cycle_utc is None


def test_usa_el_ciclo_mas_reciente_que_califica(tmp_path):
    gfs = tmp_path / "gfs"
    _tocar(gfs, "mapa_anegamientos_gfs_extension_20260701_00utc_20260701-010000.tif")
    _tocar(gfs, "mapa_anegamientos_gfs_extension_20260701_06utc_20260701-070000.tif")

    ciclo = susceptibility.resolve_susceptibility(
        explicit_path=None, source_root=str(tmp_path), sufijo_preferido="gfs",
        start=utc(2026, 6, 28), end=utc(2026, 7, 3))

    assert ciclo.cycle_utc == utc(2026, 7, 1, 6)


def test_sin_source_root_ni_ruta_explicita_devuelve_none():
    ciclo = susceptibility.resolve_susceptibility(
        explicit_path=None, source_root=None, sufijo_preferido="gfs",
        start=utc(2026, 7, 1), end=utc(2026, 7, 2))

    assert ciclo is None


def test_sin_ningun_ciclo_que_califique_devuelve_none(tmp_path):
    ciclo = susceptibility.resolve_susceptibility(
        explicit_path=None, source_root=str(tmp_path), sufijo_preferido="gfs",
        start=utc(2026, 7, 1), end=utc(2026, 7, 2))

    assert ciclo is None


def test_source_root_relativo_se_resuelve_contra_base_dir(tmp_path):
    base = tmp_path / "src"
    base.mkdir()
    gfs = tmp_path / "otro_repo" / "outputs" / "coquimbo" / "gfs"
    _tocar(gfs, "mapa_anegamientos_gfs_extension_20260701_00utc_20260701-010000.tif")

    ciclo = susceptibility.resolve_susceptibility(
        explicit_path=None, source_root="../otro_repo/outputs/coquimbo",
        sufijo_preferido="gfs", start=utc(2026, 6, 28), end=utc(2026, 7, 3),
        base_dir=base)

    assert ciclo is not None
    esperado = gfs / "mapa_anegamientos_gfs_extension_20260701_00utc_20260701-010000.tif"
    assert ciclo.path.resolve() == esperado.resolve()
