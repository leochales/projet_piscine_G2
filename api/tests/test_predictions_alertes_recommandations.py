from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from api.auth import utilisateur_courant
from api.main import app
from api.routers.health import database_status
from api.routers.predictions import calculer_fenetre
from api.tests.fausse_session import FausseSession
from api.tests.utilisateur_autorise import UTILISATEUR_AUTORISE
from common.db import get_session

# Les requêtes SQL elles-mêmes (prévision la plus récente par heure, ordre des
# alertes, sites actifs, 0 € sans recommandation acceptée) ne sont pas
# exécutées ici : ces tests vérifient les réponses et les paramètres envoyés.
# Les règles d'accès sont testées dans test_auth.py : ici, un utilisateur autorisé.


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[utilisateur_courant] = lambda: UTILISATEUR_AUTORISE
    yield TestClient(app)
    app.dependency_overrides.clear()


def brancher(lignes: list[dict[str, Any]]) -> FausseSession:
    session = FausseSession(lignes)
    app.dependency_overrides[get_session] = lambda: session
    return session


# --- Prédictions ----------------------------------------------------------------

PREDICTION: dict[str, Any] = {
    "heure": datetime(2026, 10, 26, 15, 0, tzinfo=UTC),
    "consommation_kwh": Decimal("1790.000"),
    "consommation_basse_kwh": Decimal("1700.000"),
    "consommation_haute_kwh": Decimal("1870.000"),
    "pic_prevu": True,
    "pic_prevu_kw": Decimal("460.00"),
    "pic_bas_kw": Decimal("440.00"),
    "pic_haut_kw": Decimal("480.00"),
    "calculee_le": datetime(2026, 10, 26, 14, 5, tzinfo=UTC),
    "version_modele": "rf-3",
}


def test_predictions_renvoie_la_fourchette(client: TestClient) -> None:
    sans_fourchette = PREDICTION | {
        "heure": datetime(2026, 10, 26, 16, 0, tzinfo=UTC),
        "consommation_basse_kwh": None,
        "consommation_haute_kwh": None,
        "pic_prevu": False,
        "pic_prevu_kw": None,
        "pic_bas_kw": None,
        "pic_haut_kw": None,
    }
    session = brancher([PREDICTION, sans_fourchette])

    response = client.get("/api/sites/SITE001/predictions")

    assert response.status_code == 200
    assert "pic_prevu_kw" in session.requete
    assert "pic_bas_kw" in session.requete
    assert "pic_haut_kw" in session.requete
    corps = response.json()
    assert corps[0] == {
        "heure": "2026-10-26T15:00:00Z",
        "consommation_kwh": 1790.0,
        "consommation_basse_kwh": 1700.0,
        "consommation_haute_kwh": 1870.0,
        "pic_prevu": True,
        "pic_prevu_kw": 460.0,
        "pic_bas_kw": 440.0,
        "pic_haut_kw": 480.0,
        "calculee_le": "2026-10-26T14:05:00Z",
        "version_modele": "rf-3",
    }
    assert corps[1]["consommation_basse_kwh"] is None
    assert corps[1]["pic_prevu_kw"] is None


@pytest.mark.parametrize(
    ("horizon", "duree"), [("24h", timedelta(hours=24)), ("7j", timedelta(days=7))]
)
def test_predictions_couvre_l_horizon_demande(
    client: TestClient, horizon: str, duree: timedelta
) -> None:
    session = brancher([])

    response = client.get(f"/api/sites/SITE001/predictions?horizon={horizon}")

    assert response.status_code == 200
    parametres = session.parametres
    assert parametres["id_site"] == "SITE001"
    assert parametres["fin"] - parametres["debut"] == duree


def test_predictions_refuse_un_horizon_inconnu(client: TestClient) -> None:
    brancher([])
    response = client.get("/api/sites/SITE001/predictions?horizon=30j")
    assert response.status_code == 422


def test_predictions_refuse_un_id_site_invalide(client: TestClient) -> None:
    brancher([])
    response = client.get(f"/api/sites/{'A' * 21}/predictions")
    assert response.status_code == 422


def test_fenetre_couvre_les_24_heures_a_venir() -> None:
    # L'heure en cours (14 h) est entamée : la fenêtre part de 15 h
    maintenant = datetime(2026, 10, 26, 14, 37, 12, tzinfo=UTC)

    debut, fin = calculer_fenetre("24h", maintenant)

    assert debut == datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
    assert fin == datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


def test_fenetre_a_l_heure_pile_part_de_l_heure_suivante() -> None:
    debut, _ = calculer_fenetre("7j", datetime(2026, 10, 26, 14, 0, tzinfo=UTC))
    assert debut == datetime(2026, 10, 26, 15, 0, tzinfo=UTC)


# --- Alertes --------------------------------------------------------------------

ALERTE: dict[str, Any] = {
    "id_alerte": 12,
    "id_site": "SITE002",
    "nom_site": "Usine Lyon Vénissieux",
    "source": "etl",
    "type": "spike",
    "severite": "critical",
    "message": "Pic à 1 150 kW",
    "debut": datetime(2026, 10, 26, 13, 12, tzinfo=UTC),
    "fin": None,
    "valeur": Decimal("1150.00"),
    "seuil": Decimal("1000.00"),
    "prise_en_compte": True,
    "prise_par": UUID("8f2c6c1e-4b7a-4d55-9a57-1f0e3b2f6a10"),
    "prise_le": datetime(2026, 10, 26, 13, 20, tzinfo=UTC),
}


def test_alertes_renvoie_la_prise_en_compte(client: TestClient) -> None:
    non_prise = ALERTE | {
        "id_alerte": 13,
        "severite": "low",
        "valeur": None,
        "seuil": None,
        "prise_en_compte": False,
        "prise_par": None,
        "prise_le": None,
    }
    brancher([ALERTE, non_prise])

    response = client.get("/api/alertes")

    assert response.status_code == 200
    corps = response.json()
    assert corps[0]["nom_site"] == "Usine Lyon Vénissieux"
    assert corps[0]["valeur"] == 1150.0
    assert corps[0]["fin"] is None
    assert corps[0]["prise_par"] == "8f2c6c1e-4b7a-4d55-9a57-1f0e3b2f6a10"
    assert corps[1]["prise_en_compte"] is False
    assert corps[1]["prise_par"] is None


def test_alertes_par_defaut_seulement_en_cours(client: TestClient) -> None:
    session = brancher([])

    client.get("/api/alertes")

    assert session.parametres == {
        "id_client": 1,
        "id_utilisateur_sites": None,
        "en_cours": True,
        "id_site": None,
        "limite": 100,
    }


def test_alertes_filtre_par_site_et_inclut_les_terminees(client: TestClient) -> None:
    session = brancher([])

    response = client.get("/api/alertes?en_cours=false&id_site=SITE002&limite=20")

    assert response.status_code == 200
    assert session.parametres == {
        "id_client": 1,
        "id_utilisateur_sites": None,
        "en_cours": False,
        "id_site": "SITE002",
        "limite": 20,
    }


@pytest.mark.parametrize("limite", [0, 501])
def test_alertes_refuse_une_limite_hors_bornes(client: TestClient, limite: int) -> None:
    brancher([])
    assert client.get(f"/api/alertes?limite={limite}").status_code == 422


def test_alertes_refuse_un_id_site_invalide(client: TestClient) -> None:
    brancher([])
    assert client.get("/api/alertes?id_site=SITE;DROP").status_code == 422


# --- Recommandations ------------------------------------------------------------

RECOMMANDATION: dict[str, Any] = {
    "id_recommandation": 7,
    "id_site": "SITE002",
    "nom_site": "Usine Lyon Vénissieux",
    "id_alerte": 12,
    "regle": "decaler_production",
    "titre": "Décaler la ligne 2 après 20 h",
    "description": None,
    "date_creation": datetime(2026, 10, 26, 13, 15, tzinfo=UTC),
    "gain_estime_eur": Decimal("380.00"),
    "periode_gain": "unique",
    "statut": "acceptee",
    "decide_par": UUID("8f2c6c1e-4b7a-4d55-9a57-1f0e3b2f6a10"),
    "decide_le": datetime(2026, 10, 26, 13, 30, tzinfo=UTC),
}


def test_recommandations_renvoie_gain_et_statut(client: TestClient) -> None:
    proposee = RECOMMANDATION | {
        "id_recommandation": 8,
        "id_alerte": None,
        "gain_estime_eur": None,
        "periode_gain": None,
        "statut": "proposee",
        "decide_par": None,
        "decide_le": None,
    }
    brancher([RECOMMANDATION, proposee])

    response = client.get("/api/recommandations")

    assert response.status_code == 200
    corps = response.json()
    assert corps[0]["gain_estime_eur"] == 380.0
    assert corps[0]["periode_gain"] == "unique"
    assert corps[0]["statut"] == "acceptee"
    assert corps[1]["statut"] == "proposee"
    assert corps[1]["gain_estime_eur"] is None
    assert corps[1]["id_alerte"] is None


def test_recommandations_filtre_par_site_et_statut(client: TestClient) -> None:
    session = brancher([])

    response = client.get("/api/recommandations?id_site=SITE002&statut=proposee")

    assert response.status_code == 200
    assert session.parametres == {
        "id_client": 1,
        "id_utilisateur_sites": None,
        "id_site": "SITE002",
        "statut": "proposee",
        "limite": 100,
    }


def test_recommandations_sans_filtre(client: TestClient) -> None:
    session = brancher([])

    client.get("/api/recommandations")

    assert session.parametres == {
        "id_client": 1,
        "id_utilisateur_sites": None,
        "id_site": None,
        "statut": None,
        "limite": 100,
    }


def test_recommandations_refuse_un_statut_inconnu(client: TestClient) -> None:
    brancher([])
    assert client.get("/api/recommandations?statut=en_cours").status_code == 422


def test_economies_par_site(client: TestClient) -> None:
    brancher(
        [
            {
                "id_site": "SITE001",
                "nb_recommandations_acceptees": 0,
                "economies_eur": Decimal(0),
            },
            {
                "id_site": "SITE002",
                "nb_recommandations_acceptees": 2,
                "economies_eur": Decimal("500.00"),
            },
        ]
    )

    response = client.get("/api/recommandations/economies")

    assert response.status_code == 200
    assert response.json() == [
        {"id_site": "SITE001", "nb_recommandations_acceptees": 0, "economies_eur": 0.0},
        {
            "id_site": "SITE002",
            "nb_recommandations_acceptees": 2,
            "economies_eur": 500.0,
        },
    ]


# --- Cloisonnement par client ---------------------------------------------------

ROUTES_DE_DONNEES = [
    "/api/sites/derniere-mesure",
    "/api/sites/SITE001/consommation",
    "/api/sites/SITE001/predictions",
    "/api/alertes",
    "/api/recommandations",
    "/api/recommandations/economies",
]


@pytest.mark.parametrize("url", ROUTES_DE_DONNEES)
def test_chaque_route_ne_lit_que_le_client_de_l_utilisateur(
    client: TestClient, url: str
) -> None:
    session = brancher([])

    assert client.get(url).status_code == 200

    assert session.parametres["id_client"] == UTILISATEUR_AUTORISE.id_client
    assert "s.id_client = :id_client" in session.requete


@pytest.mark.parametrize("url", ROUTES_DE_DONNEES)
def test_un_administrateur_enervision_voit_tous_les_clients(
    client: TestClient, url: str
) -> None:
    administrateur = replace(UTILISATEUR_AUTORISE, id_client=None)
    app.dependency_overrides[utilisateur_courant] = lambda: administrateur
    session = brancher([])

    assert client.get(url).status_code == 200

    assert session.parametres["id_client"] is None


@pytest.mark.parametrize("url", ROUTES_DE_DONNEES)
@pytest.mark.parametrize("role", ["CONSULT-SITE", "GESTION-SITE"])
def test_un_role_site_ne_lit_que_ses_sites(
    client: TestClient, url: str, role: str
) -> None:
    utilisateur = replace(UTILISATEUR_AUTORISE, roles=frozenset({role}))
    app.dependency_overrides[utilisateur_courant] = lambda: utilisateur
    session = brancher([])

    assert client.get(url).status_code == 200

    assert session.parametres["id_client"] == UTILISATEUR_AUTORISE.id_client
    assert session.parametres["id_utilisateur_sites"] == UTILISATEUR_AUTORISE.id
    assert "app.utilisateur_site" in session.requete


@pytest.mark.parametrize("url", ROUTES_DE_DONNEES)
def test_un_role_client_voit_tous_les_sites_du_client(
    client: TestClient, url: str
) -> None:
    # Rôle *-SITE en plus d'un rôle *-CLIENT : c'est le plus large qui compte
    utilisateur = replace(
        UTILISATEUR_AUTORISE, roles=frozenset({"CONSULT-CLIENT", "GESTION-SITE"})
    )
    app.dependency_overrides[utilisateur_courant] = lambda: utilisateur
    session = brancher([])

    assert client.get(url).status_code == 200

    assert session.parametres["id_utilisateur_sites"] is None


# --- Paramètres inconnus ----------------------------------------------------------


@pytest.mark.parametrize("url", ROUTES_DE_DONNEES)
@pytest.mark.parametrize("parametre", ["inconnu=1", "=null", "id_stie=SITE001"])
def test_un_parametre_inconnu_est_refuse(
    client: TestClient, url: str, parametre: str
) -> None:
    # Sinon une faute de frappe renverrait les données sans filtre, sans erreur
    brancher([])

    response = client.get(f"{url}?{parametre}")

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


def test_les_parametres_declares_restent_acceptes(client: TestClient) -> None:
    brancher([])
    url = "/api/recommandations?id_site=SITE001&statut=proposee&limite=10"
    assert client.get(url).status_code == 200


def test_un_parametre_inconnu_est_refuse_sur_health(client: TestClient) -> None:
    app.dependency_overrides[database_status] = lambda: True
    assert client.get("/api/health?debug=1").status_code == 422


def test_sans_jeton_le_401_passe_avant_le_422() -> None:
    # Pas d'utilisateur simulé ici : l'authentification est vérifiée pour de bon
    with TestClient(app) as anonyme:
        assert anonyme.get("/api/alertes?inconnu=1").status_code == 401
