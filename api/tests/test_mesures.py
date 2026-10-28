from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.auth import utilisateur_courant
from api.main import app
from api.routers.mesures import calculer_cout, calculer_periode
from api.tests.fausse_session import FausseSession
from api.tests.utilisateur_autorise import UTILISATEUR_AUTORISE
from common.db import get_session


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[utilisateur_courant] = lambda: UTILISATEUR_AUTORISE
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_derniere_mesure_renvoie_une_ligne_par_site(client: TestClient) -> None:
    lignes: list[dict[str, Any]] = [
        {
            "id_site": "SITE001",
            "nom": "Bureau Paris La Défense",
            "type": "office",
            "capacite_kw": 200.0,
            "seuil_alerte_pct": 90.0,
            "horodatage": datetime(2026, 10, 21, 14, 30, tzinfo=UTC),
            "consommation_kw": 87.34,
            "data_quality": "good",
        },
        {
            "id_site": "SITE002",
            "nom": "Usine Lyon Vénissieux",
            "type": "factory",
            "capacite_kw": 1000.0,
            "seuil_alerte_pct": 98.0,
            "horodatage": datetime(2026, 10, 21, 14, 30, tzinfo=UTC),
            "consommation_kw": None,
            "data_quality": "degraded",
        },
    ]
    app.dependency_overrides[get_session] = lambda: FausseSession(lignes)

    response = client.get("/api/sites/derniere-mesure")

    assert response.status_code == 200
    corps = response.json()
    assert len(corps) == 2
    assert corps[0]["nom"] == "Bureau Paris La Défense"
    assert corps[0]["type"] == "office"
    assert corps[0]["capacite_kw"] == 200.0
    assert corps[1]["seuil_alerte_pct"] == 98.0
    assert corps[0]["horodatage"] == "2026-10-21T14:30:00Z"
    assert corps[1]["consommation_kw"] is None


def test_derniere_mesure_renvoie_une_liste_vide_sans_donnees(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_session] = lambda: FausseSession([])

    response = client.get("/api/sites/derniere-mesure")

    assert response.status_code == 200
    assert response.json() == []


def test_consommation_calcule_le_cout_en_euros(client: TestClient) -> None:
    lignes: list[dict[str, Any]] = [
        {
            "heure": datetime(2026, 10, 21, 13, 0, tzinfo=UTC),
            "consommation_kwh": Decimal("500.000"),
            "nb_imputees": 0,
            "taux_couverture": Decimal("1.000"),
        },
        {
            "heure": datetime(2026, 10, 21, 14, 0, tzinfo=UTC),
            "consommation_kwh": None,
            "nb_imputees": 0,
            "taux_couverture": Decimal("0.000"),
        },
    ]
    app.dependency_overrides[get_session] = lambda: FausseSession(lignes)

    response = client.get("/api/sites/SITE001/consommation")

    assert response.status_code == 200
    corps = response.json()
    assert corps[0]["consommation_kwh"] == 500.0
    assert corps[0]["cout_eur"] == 70.0
    assert corps[1]["consommation_kwh"] is None
    assert corps[1]["cout_eur"] is None


def test_consommation_signale_les_minutes_imputees(client: TestClient) -> None:
    lignes: list[dict[str, Any]] = [
        {
            "heure": datetime(2026, 10, 21, 13, 0, tzinfo=UTC),
            "consommation_kwh": Decimal("480.000"),
            "nb_imputees": 12,
            "taux_couverture": Decimal("1.000"),
        },
    ]
    app.dependency_overrides[get_session] = lambda: FausseSession(lignes)

    response = client.get("/api/sites/SITE001/consommation")

    assert response.status_code == 200
    assert response.json()[0]["nb_imputees"] == 12
    assert response.json()[0]["taux_couverture"] == 1.0


def etat(**champs: Any) -> dict[str, Any]:
    return {
        "id_site": "SITE001",
        "nom": "Bureau Paris La Défense",
        "derniere_mesure_le": datetime(2026, 10, 21, 14, 30, tzinfo=UTC),
        "collecte_a_jour": True,
        "transmet": True,
        "etat_capteurs": "ok",
        "capteurs_en_panne": [],
        "retablissement_prevu": None,
        **champs,
    }


def test_etat_renvoie_la_transmission_et_les_capteurs(client: TestClient) -> None:
    lignes = [
        etat(),
        etat(
            id_site="SITE002",
            nom="Usine Lyon Vénissieux",
            transmet=False,
            etat_capteurs="critical",
            capteurs_en_panne=["network"],
            retablissement_prevu=datetime(2026, 10, 21, 15, 0, tzinfo=UTC),
        ),
    ]
    app.dependency_overrides[get_session] = lambda: FausseSession(lignes)

    response = client.get("/api/sites/etat")

    assert response.status_code == 200
    corps = response.json()
    assert corps[0]["transmet"] is True
    assert corps[1]["transmet"] is False
    assert corps[1]["capteurs_en_panne"] == ["network"]
    assert corps[1]["retablissement_prevu"] == "2026-10-21T15:00:00Z"


def test_etat_garde_une_transmission_inconnue_si_la_collecte_est_arretee(
    client: TestClient,
) -> None:
    lignes = [etat(collecte_a_jour=False, transmet=None, etat_capteurs=None)]
    app.dependency_overrides[get_session] = lambda: FausseSession(lignes)

    response = client.get("/api/sites/etat")

    assert response.status_code == 200
    assert response.json()[0]["collecte_a_jour"] is False
    assert response.json()[0]["transmet"] is None
    assert response.json()[0]["etat_capteurs"] is None


def test_etat_filtre_sur_le_perimetre_de_l_utilisateur(client: TestClient) -> None:
    session = FausseSession([])
    app.dependency_overrides[get_session] = lambda: session

    response = client.get("/api/sites/etat")

    assert response.status_code == 200
    assert ":id_client" in session.requete
    assert ":id_utilisateur_sites" in session.requete


def test_consommation_refuse_une_date_invalide(client: TestClient) -> None:
    app.dependency_overrides[get_session] = lambda: FausseSession([])

    response = client.get("/api/sites/SITE001/consommation?debut=pas-une-date")

    assert response.status_code == 422


def test_consommation_refuse_un_id_site_invalide(client: TestClient) -> None:
    app.dependency_overrides[get_session] = lambda: FausseSession([])

    response = client.get(f"/api/sites/{'A' * 21}/consommation")

    assert response.status_code == 422


def test_consommation_refuse_un_nombre_a_la_place_d_une_date(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_session] = lambda: FausseSession([])

    response = client.get("/api/sites/SITE001/consommation?fin=0.5")

    assert response.status_code == 422


def test_periode_par_defaut_couvre_24_heures_completes() -> None:
    debut, fin = calculer_periode(None, None)

    assert (fin.minute, fin.second, fin.microsecond) == (0, 0, 0)
    assert fin - debut == timedelta(hours=24)


def test_periode_refuse_une_fin_trop_ancienne() -> None:
    with pytest.raises(HTTPException) as erreur:
        calculer_periode(None, datetime(1, 1, 1, tzinfo=UTC))

    assert erreur.value.status_code == 400


def test_consommation_refuse_debut_apres_fin(client: TestClient) -> None:
    app.dependency_overrides[get_session] = lambda: FausseSession([])
    periode = {"debut": "2026-10-21T12:00:00Z", "fin": "2026-10-20T12:00:00Z"}

    response = client.get("/api/sites/SITE001/consommation", params=periode)

    assert response.status_code == 400


def test_consommation_refuse_une_periode_de_plus_de_31_jours(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_session] = lambda: FausseSession([])
    periode = {"debut": "2026-01-01T00:00:00Z", "fin": "2026-10-20T00:00:00Z"}

    response = client.get("/api/sites/SITE001/consommation", params=periode)

    assert response.status_code == 400


def test_consommation_refuse_une_date_sans_fuseau(client: TestClient) -> None:
    app.dependency_overrides[get_session] = lambda: FausseSession([])

    response = client.get(
        "/api/sites/SITE001/consommation", params={"fin": "2026-10-21T12:00:00"}
    )

    assert response.status_code == 422


def test_cout_arrondi_au_centime_superieur_quand_on_est_au_milieu() -> None:
    assert calculer_cout(Decimal("0.5"), Decimal("0.25")) == 0.13
