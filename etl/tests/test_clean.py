"""Tests unitaires pour etl.clean._impute().

Couvre :
  - Série sans NULLs (pas d'imputation)
  - Interpolation linéaire sur un petit trou (≤ MAX_IMPUTABLE_GAP)
  - Forward fill sur les NULLs en tête de série (pas de valeur précédente)
  - Trou trop grand (> MAX_IMPUTABLE_GAP) → reste NULL (non imputé)
  - Série entièrement nulle → reste NULL

Ces tests n'ont besoin d'aucune base de données.
"""

from __future__ import annotations

import math

import pandas as pd

from etl.clean import MAX_IMPUTABLE_GAP, _impute

# ────────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────────


def make_series(*values: float | None) -> pd.Series:
    """Crée une pd.Series flottante à partir de valeurs (None → NaN)."""
    return pd.Series([float("nan") if v is None else float(v) for v in values])


# ────────────────────────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────────────────────────


class TestImpute:
    """Tests de _impute() — imputation des valeurs manquantes."""

    def test_no_nulls_unchanged(self):
        """Une série sans NULLs ne doit pas être modifiée."""
        s = make_series(10.0, 20.0, 30.0, 40.0)
        imputed, is_imputed, method = _impute(s)

        pd.testing.assert_series_equal(imputed, s, check_names=False)
        assert is_imputed.sum() == 0, "Aucune valeur ne doit être marquée imputée"
        assert (method == "none").all()

    def test_linear_interpolation_small_gap(self):
        """Un trou d'un seul NULL entouré de valeurs connues → interpolation linéaire."""
        # 10 → None → 30 : la valeur interpolée attendue est 20.0
        s = make_series(10.0, None, 30.0)
        imputed, is_imputed, method = _impute(s)

        assert not math.isnan(imputed.iloc[1]), "Le NULL doit être imputé"
        assert math.isclose(imputed.iloc[1], 20.0, rel_tol=1e-6)
        assert is_imputed.iloc[1]
        assert method.iloc[1] == "linear_interpolation"
        # Les valeurs déjà connues ne changent pas
        assert math.isclose(imputed.iloc[0], 10.0)
        assert math.isclose(imputed.iloc[2], 30.0)

    def test_linear_interpolation_gap_at_limit(self):
        """Un trou de exactement MAX_IMPUTABLE_GAP NULLs → tous interpolés."""
        # 0 → [None × MAX_IMPUTABLE_GAP] → (MAX_IMPUTABLE_GAP+1)*10
        last = (MAX_IMPUTABLE_GAP + 1) * 10.0
        values: list[float | None] = [0.0] + [None] * MAX_IMPUTABLE_GAP + [last]
        s = make_series(*values)
        imputed, is_imputed, method = _impute(s)

        # Tous les NULLs intermédiaires doivent être imputés
        null_positions = list(range(1, MAX_IMPUTABLE_GAP + 1))
        for idx in null_positions:
            assert is_imputed.iloc[idx], f"Position {idx} doit être imputée"
            assert method.iloc[idx] == "linear_interpolation"
        # Valeurs aux bornes inchangées
        assert math.isclose(imputed.iloc[0], 0.0)
        assert math.isclose(imputed.iloc[-1], last)

    def test_gap_too_large_uses_forward_fill(self):
        """Un trou > MAX_IMPUTABLE_GAP entre deux bornes connues :
        les premières positions sont interpolées linéairement, les suivantes
        sont forward-fillées (valeur du dernier point interpolé).
        Aucune position ne reste NULL."""
        gap = MAX_IMPUTABLE_GAP + 1  # dépasse la limite
        values: list[float | None] = [0.0] + [None] * gap + [100.0]
        s = make_series(*values)
        imputed, is_imputed, method = _impute(s)

        # Toutes les positions de trou doivent être imputées (aucune ne reste NULL)
        for i in range(1, gap + 1):
            assert not math.isnan(imputed.iloc[i]), (
                f"Position {i} ne doit pas rester NULL"
            )
            assert is_imputed.iloc[i], f"Position {i} doit être marquée imputée"

        # Les premières MAX_IMPUTABLE_GAP positions → interpolation linéaire
        for i in range(1, MAX_IMPUTABLE_GAP + 1):
            assert method.iloc[i] == "linear_interpolation", (
                f"Position {i} attendue 'linear_interpolation', obtenu '{method.iloc[i]}'"
            )

        # Les positions au-delà de la limite → forward_fill
        for i in range(MAX_IMPUTABLE_GAP + 1, gap + 1):
            assert method.iloc[i] == "forward_fill", (
                f"Position {i} attendue 'forward_fill' (au-delà de la limite), obtenu '{method.iloc[i]}'"
            )

    def test_leading_nulls_stay_null(self):
        """Les NULLs en tête de série (avant toute valeur connue) restent NULL :
        ni l'interpolation ni le forward-fill ne peuvent les atteindre."""
        # None None 42.0 None  : positions 0 et 1 restent NULL (aucune valeur avant elles)
        s = make_series(None, None, 42.0, None)
        imputed, is_imputed, method = _impute(s)

        # Les NULLs de tête restent NULL
        assert math.isnan(imputed.iloc[0]), "NULL de tête doit rester NaN"
        assert math.isnan(imputed.iloc[1]), "NULL de tête doit rester NaN"
        assert not is_imputed.iloc[0]
        assert not is_imputed.iloc[1]
        assert method.iloc[0] == "none"
        assert method.iloc[1] == "none"

        # La valeur connue reste inchangée
        assert math.isclose(imputed.iloc[2], 42.0)

        # Le NULL trailing (position 3) doit être imputé (interpol. ou ffill)
        assert not math.isnan(imputed.iloc[3]), "NULL trailing doit être imputé"
        assert is_imputed.iloc[3]

    def test_forward_fill_beyond_interpolation_limit(self):
        """Un long trou trailing (> MAX_IMPUTABLE_GAP) : les positions
        au-delà de la limite d'interpolation sont forward-fillées."""
        # 5.0 suivi de MAX_IMPUTABLE_GAP + 3 NULLs (pas de valeur à droite)
        extra = 3
        values: list[float | None] = [5.0] + [None] * (MAX_IMPUTABLE_GAP + extra)
        s = make_series(*values)
        imputed, _is_imputed, method = _impute(s)

        # Les positions interpolées (1 à MAX_IMPUTABLE_GAP) → linear_interpolation
        for i in range(1, MAX_IMPUTABLE_GAP + 1):
            assert method.iloc[i] == "linear_interpolation", (
                f"Position {i} attendue 'linear_interpolation'"
            )
        # Les positions au-delà → forward_fill
        for i in range(MAX_IMPUTABLE_GAP + 1, MAX_IMPUTABLE_GAP + extra + 1):
            assert method.iloc[i] == "forward_fill", (
                f"Position {i} attendue 'forward_fill' (au-delà de la limite)"
            )
            assert math.isclose(imputed.iloc[i], 5.0), (
                f"forward-fill doit copier la valeur 5.0 à la position {i}"
            )

    def test_all_nulls_stay_null(self):
        """Une série entièrement nulle ne peut pas être imputée — reste NULL."""
        s = make_series(None, None, None)
        imputed, is_imputed, _method = _impute(s)

        assert imputed.isna().all(), "Toutes les valeurs doivent rester NaN"
        assert is_imputed.sum() == 0

    def test_imputed_flag_false_for_original_values(self):
        """is_imputed doit être False pour les valeurs originellement non-NULL."""
        s = make_series(5.0, None, 15.0)
        _, is_imputed, _ = _impute(s)

        assert not is_imputed.iloc[0], "Valeur originale → is_imputed=False"
        assert not is_imputed.iloc[2], "Valeur originale → is_imputed=False"
        assert is_imputed.iloc[1], "Valeur imputée → is_imputed=True"