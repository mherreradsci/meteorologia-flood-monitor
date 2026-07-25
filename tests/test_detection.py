"""El núcleo de la decisión: qué píxel cuenta como anegado. Sin red.

`water_threshold` y `detect_flood` son las dos funciones que deciden el
resultado del mapa. Un error acá no rompe la corrida: produce un mapa
verosímil pero equivocado, que es el modo de falla más difícil de ver a ojo.

Solo necesitan numpy y scikit-image (nada de GDAL): operan sobre `.values`,
así que alcanza con el doble `FakeRaster`.
"""

from __future__ import annotations

import numpy as np
import pytest

from flood_monitor import detect_flood, water_threshold
from helpers import FakeRaster

CLARO = -5.0     # retrodispersión típica de suelo seco
OSCURO = -22.0   # agua: reflector especular, devuelve poco al sensor


def escena_bimodal(centro_oscuro: float, centro_claro: float) -> FakeRaster:
    """Histograma de dos modas, que es donde Otsu tiene sentido.

    Un pequeño abanico alrededor de cada moda evita el aviso de skimage
    sobre imágenes con muy pocos valores distintos.
    """
    oscuro = np.linspace(centro_oscuro - 1, centro_oscuro + 1, 300)
    claro = np.linspace(centro_claro - 1, centro_claro + 1, 700)
    return FakeRaster(np.concatenate([oscuro, claro]))


# --------------------------------------------------------------------------- #
# water_threshold
# --------------------------------------------------------------------------- #
def test_umbral_fijo_se_respeta_sin_acotar():
    """--threshold manda: el recorte [-25, -14] es solo para Otsu.

    Si también acotara el valor fijo, no habría forma de calibrar a mano
    una escena rara, que es justamente para lo que existe la opción.
    """
    assert water_threshold(escena_bimodal(-22, -5), fixed=-40.0) == -40.0
    assert water_threshold(escena_bimodal(-22, -5), fixed=-2.0) == -2.0


def test_umbral_fijo_de_cero_no_se_confunde_con_ausente():
    """`--threshold 0` es un valor, no un "no me pasaron nada".

    La comprobación es `is not None`; con un `if not fixed` esto caería a
    Otsu en silencio.
    """
    assert water_threshold(escena_bimodal(-22, -5), fixed=0.0) == 0.0


def test_otsu_cae_entre_las_dos_modas():
    t = water_threshold(escena_bimodal(-22, -8), fixed=None)

    assert -22.0 < t < -8.0


def test_otsu_demasiado_bajo_se_acota_a_menos_25():
    """Escena sin agua real: todo oscuro (p. ej. suelo muy liso y seco).

    Otsu partiría el histograma igual, devolviendo ~-39 dB y marcando como
    agua medio AOI. El recorte lo frena.
    """
    t = water_threshold(escena_bimodal(-40, -30), fixed=None)

    assert t == -25.0


def test_otsu_demasiado_alto_se_acota_a_menos_14():
    """Escena entera brillante: sin el recorte, el umbral subiría tanto que
    contaría como agua terreno seco normal."""
    t = water_threshold(escena_bimodal(-10, 2), fixed=None)

    assert t == -14.0


def test_otsu_ignora_los_nodata():
    """Los píxeles inválidos entran como NaN (ver DB_NODATA en to_db).

    Sin el filtro `isfinite`, Otsu devuelve NaN y el umbral queda
    inservible: ningún píxel compararía como menor que él.
    """
    limpia = escena_bimodal(-22, -8)
    con_huecos = FakeRaster(np.concatenate([limpia.values,
                                            np.full(200, np.nan)]))

    assert water_threshold(con_huecos, None) == water_threshold(limpia, None)


# --------------------------------------------------------------------------- #
# detect_flood
# --------------------------------------------------------------------------- #
def escena_con_parche(alto=12, ancho=12, fondo=CLARO):
    return np.full((alto, ancho), fondo, dtype="float32")


def test_solo_los_pixeles_por_debajo_del_umbral_son_agua():
    vh = escena_con_parche()
    vh[2:8, 2:8] = OSCURO   # 36 px, bien por encima del área mínima

    flood = detect_flood(FakeRaster(vh), threshold=-18.0, perm_mask=None,
                         steep_mask=None, min_area_px=5)

    assert flood[2:8, 2:8].all()
    assert flood.sum() == 36


def test_los_nodata_nunca_cuentan_como_agua():
    """NaN no es "oscuro": es "no sé". Un hueco grande no debe convertirse
    en un polígono de anegamiento.

    El -inf es el caso que de verdad exige la guarda `isfinite`: cumple
    `< threshold` y sin ella entraría como agua. Con NaN solo, la
    comparación ya da False y la guarda parecería de adorno.
    """
    vh = escena_con_parche()
    vh[1:5, 1:5] = np.nan
    vh[7:11, 1:5] = -np.inf

    flood = detect_flood(FakeRaster(vh), threshold=-18.0, perm_mask=None,
                         steep_mask=None, min_area_px=5)

    assert not flood.any()


def test_min_area_px_conserva_el_parche_justo_y_borra_el_de_uno_menos():
    """El borde exacto de --min-area-px.

    `remove_small_objects(max_size=min_area_px - 1)` elimina parches de
    tamaño <= max_size, o sea conserva los de >= min_area_px. Ese `- 1`
    reproduce la semántica del viejo `min_size`; si una versión de skimage
    la corriera un lugar, este test lo caza.
    """
    vh = escena_con_parche()
    vh[1, 1:6] = OSCURO    # 5 px contiguos  -> se conserva
    vh[9, 1:5] = OSCURO    # 4 px contiguos  -> se descarta

    flood = detect_flood(FakeRaster(vh), threshold=-18.0, perm_mask=None,
                         steep_mask=None, min_area_px=5)

    assert flood[1, 1:6].all()
    assert not flood[9, 1:5].any()
    assert flood.sum() == 5


def test_el_agua_permanente_queda_excluida():
    """El mar y los embalses son agua, pero no son novedad."""
    vh = escena_con_parche()
    vh[2:8, 2:8] = OSCURO
    perm = np.zeros_like(vh, dtype=bool)
    perm[2:8, 2:5] = True   # media mitad del parche es agua permanente

    flood = detect_flood(FakeRaster(vh), threshold=-18.0, perm_mask=perm,
                         steep_mask=None, min_area_px=5)

    assert not flood[2:8, 2:5].any()
    assert flood[2:8, 5:8].all()


def test_la_pendiente_excluye_las_sombras_de_relieve():
    """Detrás de un cerro el radar no ilumina: sale oscuro por geometría,
    no por agua. El DEM es lo que distingue un caso del otro."""
    vh = escena_con_parche()
    vh[2:8, 2:8] = OSCURO
    empinado = np.zeros_like(vh, dtype=bool)
    empinado[2:8, 2:8] = True

    flood = detect_flood(FakeRaster(vh), threshold=-18.0, perm_mask=None,
                         steep_mask=empinado, min_area_px=5)

    assert not flood.any()


# --------------------------------------------------------------------------- #
# detect_flood con --change
# --------------------------------------------------------------------------- #
def test_el_cambio_descarta_lo_oscuro_estable():
    """El asfalto y las parcelas lisas son oscuros en todas las fechas.

    Con referencia, hay que haberse oscurecido: lo que ya estaba oscuro
    antes no es anegamiento nuevo.
    """
    vh = escena_con_parche()
    ref = escena_con_parche()
    vh[1, 1:7] = OSCURO
    ref[1, 1:7] = OSCURO    # ya estaba oscuro -> pavimento, no agua
    vh[9, 1:7] = OSCURO
    ref[9, 1:7] = CLARO     # se oscureció -> anegamiento

    flood = detect_flood(FakeRaster(vh), threshold=-18.0, perm_mask=None,
                         steep_mask=None, min_area_px=5,
                         ref_db=FakeRaster(ref), change_delta=3.0)

    assert not flood[1, 1:7].any()
    assert flood[9, 1:7].all()


def test_la_caida_debe_superar_change_delta_no_igualarlo():
    """El criterio es `diff < -change_delta`, estricto.

    Una caída de exactamente 3 dB con --change-delta 3 no alcanza: fija el
    borde para que nadie lo cambie a <= sin querer.
    """
    vh = escena_con_parche()
    ref = escena_con_parche()
    vh[1, 1:7] = -22.0
    ref[1, 1:7] = -19.0     # caída de exactamente 3.0 dB
    vh[9, 1:7] = -22.0
    ref[9, 1:7] = -18.9     # caída de 3.1 dB

    flood = detect_flood(FakeRaster(vh), threshold=-18.0, perm_mask=None,
                         steep_mask=None, min_area_px=5,
                         ref_db=FakeRaster(ref), change_delta=3.0)

    assert not flood[1, 1:7].any()
    assert flood[9, 1:7].all()


def test_sin_referencia_el_criterio_de_cambio_no_se_aplica():
    """Mismo dato, con y sin referencia: sin ella manda solo el umbral."""
    vh = escena_con_parche()
    vh[2:8, 2:8] = OSCURO
    ref = escena_con_parche()
    ref[2:8, 2:8] = OSCURO   # estable: con --change no sería anegamiento

    con_ref = detect_flood(FakeRaster(vh), -18.0, None, None, 5,
                           ref_db=FakeRaster(ref), change_delta=3.0)
    sin_ref = detect_flood(FakeRaster(vh), -18.0, None, None, 5)

    assert not con_ref.any()
    assert sin_ref.sum() == 36


@pytest.mark.parametrize("min_area_px", [1, 5, 20])
def test_la_salida_es_booleana_del_mismo_tamano(min_area_px):
    """save_outputs hace `flood.astype("uint8")` y lo usa como máscara de
    rasterio: si dejara de ser booleano del tamaño de la grilla, el GeoTIFF
    y la vectorización saldrían corridos."""
    vh = escena_con_parche()
    vh[2:8, 2:8] = OSCURO

    flood = detect_flood(FakeRaster(vh), -18.0, None, None, min_area_px)

    assert flood.dtype == bool
    assert flood.shape == vh.shape
