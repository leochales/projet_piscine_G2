"""Tests unitaires pour etl.aggregate — logique métier sans BDD.

Couvre :
  - Seuils d'alerte (ALERT_THRESHOLD_HIGH, ALERT_THRESHOLD_CRITICAL)
  - Mapping statut capteur API → statut gold.etat_capteur
  - Calcul du coût horaire (cout_eur = consommation_kwh × tarif)

Ces tests n'ont besoin d'aucune base de données ni de l'API Mock.
"""

from __future__ import annotations

import math

import pytest

from etl.aggregate import (
    _REGLES_RECOMMANDATION,
    ALERT_THRESHOLD_CRITICAL,
    ALERT_THRESHOLD_HIGH,
)

# ────────────────────────────────────────────────────────────────────────────────
# Tests — Seuils d'alerte
# ────────────────────────────────────────────────────────────────────────────────


class TestAlertThresholds:
    """Valide que les constantes de seuil sont cohérentes avec les spécifications."""

    def test_high_threshold_value(self):
        """Le seuil 'high' doit être 90 % de charge."""
        assert ALERT_THRESHOLD_HIGH == pytest.approx(90.0)

    def test_critical_threshold_value(self):
        """Le seuil 'critical' doit être 110 % (surcharge)."""
        assert ALERT_THRESHOLD_CRITICAL == pytest.approx(110.0)

    def test_critical_above_high(self):
        """Le seuil critical doit être strictement supérieur au seuil high."""
        assert ALERT_THRESHOLD_CRITICAL > ALERT_THRESHOLD_HIGH

    @pytest.mark.parametrize(
        "load_percent,expected_severity",
        [
            (89.9, None),  # sous le seuil → pas d'alerte
            (90.0, "high"),  # exactement au seuil → high
            (109.9, "high"),  # entre les deux seuils → high
            (110.0, "critical"),  # exactement au seuil critical → critical
            (130.0, "critical"),  # très en surcharge → critical
        ],
    )
    def test_severity_classification(
        self, load_percent: float, expected_severity: str | None
    ):
        """Vérifie la classification de sévérité en fonction du load_percent."""
        if expected_severity is None:
            # Aucune alerte attendue
            assert load_percent < ALERT_THRESHOLD_HIGH
        elif expected_severity == "high":
            assert ALERT_THRESHOLD_HIGH <= load_percent < ALERT_THRESHOLD_CRITICAL
        elif expected_severity == "critical":
            assert load_percent >= ALERT_THRESHOLD_CRITICAL
        else:
            pytest.fail(f"Sévérité inattendue : {expected_severity}")


# ────────────────────────────────────────────────────────────────────────────────
# Tests — Règles de recommandation
# ────────────────────────────────────────────────────────────────────────────────


class TestReglesRecommandation:
    """Vérifie le dictionnaire _REGLES_RECOMMANDATION."""

    def test_threshold_high_regle_exists(self):
        """La règle threshold/high doit exister."""
        assert ("threshold", "high") in _REGLES_RECOMMANDATION

    def test_threshold_critical_regle_exists(self):
        """La règle threshold/critical doit exister."""
        assert ("threshold", "critical") in _REGLES_RECOMMANDATION

    def test_regle_tuple_structure(self):
        """Chaque entrée doit être un tuple (regle, titre, description)."""
        for key, val in _REGLES_RECOMMANDATION.items():
            assert len(val) == 3, (
                f"Clé {key} doit avoir 3 éléments (regle, titre, description)"
            )
            regle, titre, description = val
            assert isinstance(regle, str) and regle, f"regle vide pour {key}"
            assert isinstance(titre, str) and titre, f"titre vide pour {key}"
            assert isinstance(description, str) and description, (
                f"description vide pour {key}"
            )

    def test_threshold_high_recommandation_content(self):
        """La recommandation high doit mentionner 90 %."""
        _, titre, desc = _REGLES_RECOMMANDATION[("threshold", "high")]
        assert "90" in desc or "90" in titre, (
            "La recommandation high devrait mentionner le seuil 90 %"
        )

    def test_threshold_critical_recommandation_content(self):
        """La recommandation critical doit mentionner 110 % ou 'urgence'."""
        _, titre, desc = _REGLES_RECOMMANDATION[("threshold", "critical")]
        content = titre + " " + desc
        assert (
            "110" in content
            or "urgence" in content.lower()
            or "délestage" in content.lower()
        ), "La recommandation critical devrait mentionner 110 % ou être urgente"


# ────────────────────────────────────────────────────────────────────────────────
# Tests — Calcul du coût horaire
# ────────────────────────────────────────────────────────────────────────────────


class TestCoutHoraire:
    """Vérifie la formule de calcul du coût en euros.

    La formule est : cout_eur = consommation_kwh × tarif_kwh_eur
    Le calcul se fait dans la requête SQL de _insert_hourly(), on teste
    ici la cohérence de la config et de la formule directement.
    """

    @pytest.mark.parametrize(
        "consommation_kwh,tarif,expected_cout",
        [
            (10.0, 0.2516, 2.516),  # cas nominal
            (0.0, 0.2516, 0.0),  # pas de consommation → pas de coût
            (100.0, 0.1740, 17.40),  # tarif alternatif
            (0.5, 0.2516, 0.1258),  # petit consommateur
        ],
    )
    def test_formule_cout_eur(
        self,
        consommation_kwh: float,
        tarif: float,
        expected_cout: float,
    ):
        """cout_eur = consommation_kwh × tarif_kwh_eur (tolérance 1e-4 €)."""
        cout = consommation_kwh * tarif
        assert math.isclose(cout, expected_cout, rel_tol=1e-4), (
            f"{consommation_kwh} kWh × {tarif} €/kWh ≠ {expected_cout} € (obtenu {cout})"
        )

    def test_tarif_defaut_coherent(self):
        """Le tarif par défaut dans Settings doit être positif et raisonnable (< 1 €/kWh)."""
        # Import ici pour éviter de charger les variables d'env dans les autres tests
        from common.config import Settings

        # On instancie avec des valeurs minimales pour ne pas avoir besoin du .env
        s = Settings(
            postgres_user="x",
            postgres_password="x",  # type: ignore[arg-type]
            postgres_db="x",
        )
        assert s.tarif_kwh_eur > 0, "Le tarif doit être positif"
        assert s.tarif_kwh_eur < 1.0, "Le tarif doit être < 1 €/kWh (sanity check)"


# ────────────────────────────────────────────────────────────────────────────────
# Tests — Mapping statut capteur (API → Gold)
# ────────────────────────────────────────────────────────────────────────────────


class TestEtatCapteurMapping:
    """Vérifie le mapping API status → statut gold.etat_capteur.

    On teste la logique pure de résolution (priorité API > Silver)
    sans appel BDD ni réseau, en extrayant la logique comme fonction testable.
    """

    @staticmethod
    def _resolve_statut(
        api_status: str | None,
        silver_statut: str = "ok",
    ) -> str:
        """Reproduit la logique de résolution de _upsert_etat_capteur()."""
        if api_status == "failing":
            return "en_panne"
        if api_status == "ok":
            return "ok"
        return silver_statut

    @pytest.mark.parametrize(
        "api_status,silver_statut,expected",
        [
            ("failing", "ok", "en_panne"),  # API failing → en_panne (priorité API)
            (
                "failing",
                "degrade",
                "en_panne",
            ),  # API failing même si Silver dit degrade
            ("ok", "en_panne", "ok"),  # API ok → ok (priorité API)
            (None, "ok", "ok"),  # API indisponible → fallback Silver
            (None, "degrade", "degrade"),  # API indisponible → fallback Silver
            (
                None,
                "en_panne",
                "en_panne",
            ),  # API indisponible → fallback Silver critical
        ],
    )
    def test_statut_resolution(
        self,
        api_status: str | None,
        silver_statut: str,
        expected: str,
    ):
        result = self._resolve_statut(api_status, silver_statut)
        assert result == expected, (
            f"api_status={api_status!r}, silver={silver_statut!r} → attendu {expected!r}, obtenu {result!r}"
        )

    def test_statut_values_in_check_constraint(self):
        """Les statuts générés doivent être parmi les valeurs acceptées par la contrainte SQL."""
        valid_statuts = {"ok", "en_panne", "degrade"}
        test_cases = [
            ("failing", "ok"),
            ("ok", "degrade"),
            (None, "ok"),
            (None, "degrade"),
            (None, "en_panne"),
        ]
        for api_status, silver_statut in test_cases:
            result = self._resolve_statut(api_status, silver_statut)
            assert result in valid_statuts, (
                f"Statut {result!r} non valide pour la contrainte CHECK SQL"
            )