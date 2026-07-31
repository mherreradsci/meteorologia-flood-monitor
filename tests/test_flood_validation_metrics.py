"""metrics.py: matriz de confusión, métricas derivadas, error de área,
agreement con tolerancia espacial y desglose por bin de HAND. Sin red, sin
GDAL — todo el módulo es numpy puro (`buffered_agreement` usa
scipy.ndimage, ya una dependencia transitiva de scikit-image/rasterio).

Los valores esperados de las métricas derivadas se recalculan acá con las
fórmulas de referencia sobre la misma matriz de confusión (Kappa/MCC en
particular, donde un error de tipeo a mano es fácil) — mismo espíritu que
el test analítico de pendiente en test_masks.py (atan(1/3) exacto), pero
con la fórmula como código en vez de un número pegado.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from flood_validation import metrics

SUSCEPTIBLE = np.array([
    [True, True, False, False],
    [True, True, False, False],
    [False, False, False, False],
    [False, False, False, False],
])
REAL = np.array([
    [True, False, False, False],
    [True, True, False, False],
    [False, False, False, False],
    [False, False, False, False],
])


# --------------------------------------------------------------------------- #
# confusion_matrix / derived_metrics
# --------------------------------------------------------------------------- #
def test_confusion_matrix_cuenta_a_mano():
    cm = metrics.confusion_matrix(SUSCEPTIBLE, REAL)

    assert (cm.tp, cm.fp, cm.fn, cm.tn) == (3, 1, 0, 12)
    assert cm.n == 16


def test_derived_metrics_contra_formulas_de_referencia():
    cm = metrics.ConfusionMatrix(tp=3, fp=1, fn=0, tn=12)

    d = metrics.derived_metrics(cm)

    assert d.precision == pytest.approx(3 / 4)
    assert d.recall == pytest.approx(3 / 3)
    assert d.f1 == pytest.approx(2 * 0.75 * 1.0 / (0.75 + 1.0))
    assert d.iou == pytest.approx(3 / 4)

    n = 16
    po = (3 + 12) / n
    pe = ((3 + 1) * (3 + 0) + (0 + 12) * (1 + 12)) / (n * n)
    assert d.kappa == pytest.approx((po - pe) / (1 - pe))

    mcc_ref = (3 * 12 - 1 * 0) / math.sqrt(4 * 3 * 13 * 12)
    assert d.mcc == pytest.approx(mcc_ref)


def test_precision_recall_none_sin_positivos_predichos_ni_reales():
    cm = metrics.ConfusionMatrix(tp=0, fp=0, fn=0, tn=16)

    d = metrics.derived_metrics(cm)

    assert d.precision is None
    assert d.recall is None
    assert d.f1 is None
    assert d.iou is None


def test_kappa_y_mcc_none_cuando_las_dos_capas_son_todo_positivo():
    """Caso límite matemático real de Kappa/MCC: sin ningún negativo en
    ninguna de las dos capas, ambas fórmulas caen en 0/0 (no hay
    variabilidad marginal que explicar) — None, no un 1.0 inventado."""
    cm = metrics.ConfusionMatrix(tp=16, fp=0, fn=0, tn=0)

    d = metrics.derived_metrics(cm)

    assert d.precision == 1.0
    assert d.recall == 1.0
    assert d.f1 == 1.0
    assert d.iou == 1.0
    assert d.kappa is None
    assert d.mcc is None


# --------------------------------------------------------------------------- #
# area_metrics
# --------------------------------------------------------------------------- #
def test_area_metrics_contra_calculo_a_mano():
    pixel_area_km2 = 0.0009  # 30x30 m

    area = metrics.area_metrics(SUSCEPTIBLE, REAL, pixel_area_km2)

    assert area.susceptible_km2 == pytest.approx(4 * pixel_area_km2)
    assert area.real_km2 == pytest.approx(3 * pixel_area_km2)
    assert area.diff_km2 == pytest.approx(1 * pixel_area_km2)
    assert area.pct_error_signed == pytest.approx(
        100 * pixel_area_km2 / (3 * pixel_area_km2))
    assert area.pct_error_abs == pytest.approx(area.pct_error_signed)


def test_area_metrics_sin_area_real_no_calcula_porcentaje():
    susceptible = np.array([[True, False], [False, False]])
    real = np.zeros((2, 2), dtype=bool)

    area = metrics.area_metrics(susceptible, real, 1.0)

    assert area.real_km2 == 0.0
    assert area.pct_error_signed is None
    assert area.pct_error_abs is None


# --------------------------------------------------------------------------- #
# buffered_agreement
# --------------------------------------------------------------------------- #
def test_buffered_agreement_contra_distancias_calculadas_a_mano():
    susceptible = np.zeros((10, 10), dtype=bool)
    susceptible[5, 5] = True
    real = np.zeros((10, 10), dtype=bool)
    real[5, 5] = True   # distancia 0
    real[5, 7] = True   # 2 px = 60 m
    real[5, 9] = True   # 4 px = 120 m

    pct = metrics.buffered_agreement(susceptible, real, resolution_m=30.0,
                                     buffer_tolerance_m=90.0)

    assert pct == pytest.approx(100 * 2 / 3)  # 2 de los 3 reales caen a <=90 m


def test_buffered_agreement_sin_area_real_devuelve_none():
    susceptible = np.zeros((5, 5), dtype=bool)
    real = np.zeros((5, 5), dtype=bool)

    assert metrics.buffered_agreement(susceptible, real, 30.0, 100.0) is None


def test_buffered_agreement_sin_nada_susceptible_da_cero():
    susceptible = np.zeros((5, 5), dtype=bool)
    real = np.zeros((5, 5), dtype=bool)
    real[2, 2] = True

    assert metrics.buffered_agreement(susceptible, real, 30.0, 100.0) == 0.0


# --------------------------------------------------------------------------- #
# stratify_by_hand_bin
# --------------------------------------------------------------------------- #
def test_stratify_by_hand_bin_separa_la_confusion_por_bin():
    susceptible = np.zeros((4, 4), dtype=bool)
    real = np.zeros((4, 4), dtype=bool)
    hand = np.zeros((4, 4), dtype="float32")

    hand[0, :] = 0.5    # bin [0, 1): TP en (0,0)
    susceptible[0, 0] = True
    real[0, 0] = True

    hand[1, :] = 4.0    # bin [3, 5): FP en (1,0)
    susceptible[1, 0] = True

    hand[2, :] = np.nan  # sin dato: no debe entrar a ningún bin

    hand[3, :] = 20.0   # bin [15, inf)

    bins = metrics.stratify_by_hand_bin(susceptible, real, hand)

    assert len(bins) == 3  # solo los bins con al menos un píxel
    por_rango = {(b["hand_min_m"], b["hand_max_m"]): b for b in bins}
    assert por_rango[(0.0, 1.0)]["confusion"]["tp"] == 1
    assert por_rango[(0.0, 1.0)]["n_px"] == 4
    assert por_rango[(3.0, 5.0)]["confusion"]["fp"] == 1
    assert por_rango[(15.0, None)]["n_px"] == 4
    assert sum(b["n_px"] for b in bins) == 12  # 3 filas de 4, la fila NaN afuera


# --------------------------------------------------------------------------- #
# evaluate / evaluation_to_dict
# --------------------------------------------------------------------------- #
def test_evaluate_arma_el_reporte_completo_y_serializable():
    hand = np.full((4, 4), 2.0, dtype="float32")

    resultado = metrics.evaluate(SUSCEPTIBLE, REAL, pixel_area_km2=0.0009,
                                 resolution_m=30.0, hand=hand)
    d = metrics.evaluation_to_dict(resultado)

    json.dumps(d)  # no debe fallar por tipos no serializables (np.float64, etc.)
    assert d["confusion_matrix"] == {"tp": 3, "fp": 1, "fn": 0, "tn": 12}
    assert d["derived_metrics"]["precision"] == pytest.approx(0.75)
    assert d["area_metrics"]["susceptible_km2"] == pytest.approx(4 * 0.0009)
    assert d["buffered_agreement_pct"] is not None
    assert d["hand_bins"]  # todo el AOI cae en el mismo bin (HAND=2.0)
    assert d["n_valid_px"] == 16


def test_evaluate_sin_hand_no_calcula_bins():
    resultado = metrics.evaluate(SUSCEPTIBLE, REAL, pixel_area_km2=0.0009,
                                 resolution_m=30.0)

    assert resultado.hand_bins == []


def test_evaluate_respeta_la_mascara_valid():
    valid = np.ones((4, 4), dtype=bool)
    valid[0, 0] = False  # excluye justo el único TP

    resultado = metrics.evaluate(SUSCEPTIBLE, REAL, pixel_area_km2=0.0009,
                                 resolution_m=30.0, valid=valid)

    assert resultado.confusion.tp == 2
    assert resultado.n_valid_px == 15
