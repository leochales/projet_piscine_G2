"""Actions du dashboard (US7) : prendre une alerte en compte, décider d'une recommandation.

La base est simulée : alertes, recommandations, sites attribués et actions en mémoire,
avec le même périmètre que les vraies requêtes (client, puis sites attribués pour un
rôle *-SITE seul). Le SQL lui-même et ses contraintes sont testés par
db/tests/test_actions.sql.
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from api.auth import Utilisateur, utilisateur_courant
from api.main import app
from api.tests.utilisateur_autorise import UTILISATEUR_AUTORISE
from common.db import get_session

MAINTENANT = datetime(2026, 10, 27, 14, 0, tzinfo=UTC)
AUTRE_UTILISATEUR = UUID("00000000-0000-0000-0000-000000000002")

# Sites du client 1 (celui de UTILISATEUR_AUTORISE) et d'un autre client
SITES = {"SITE001": 1, "SITE002": 1, "SITE-AUTRE": 2}


def alerte(id_alerte: int, id_site: str, fin: datetime | None = None) -> dict[str, Any]:
    return {
        "id_alerte": id_alerte,
        "id_site": id_site,
        "nom_site": f"Site {id_site}",
        "source": "etl",
        "type": "threshold",
        "severite": "high",
        "message": None,
        "debut": MAINTENANT,
        "fin": fin,
        "valeur": 752.0,
        "seuil": 720.0,
    }


def recommandation(id_recommandation: int, id_site: str) -> dict[str, Any]:
    return {
        "id_recommandation": id_recommandation,
        "id_site": id_site,
        "nom_site": f"Site {id_site}",
        "id_alerte": None,
        "regle": "pic",
        "titre": "Décaler la production",
        "description": None,
        "date_creation": MAINTENANT,
        "gain_estime_eur": 380.0,
        "periode_gain": "semaine",
    }


class Resultat:
    def __init__(self, lignes: list[dict[str, Any]]) -> None:
        self.lignes = lignes

    def mappings(self) -> "Resultat":
        return self

    def first(self) -> dict[str, Any] | None:
        return self.lignes[0] if self.lignes else None


class FausseBase:
    """Données du client 1 et d'un autre client ; actions enregistrées au commit."""

    def __init__(self) -> None:
        self.alertes = {
            1: alerte(1, "SITE001"),
            2: alerte(2, "SITE002"),
            3: alerte(3, "SITE001", fin=MAINTENANT),
            9: alerte(9, "SITE-AUTRE"),
        }
        self.recommandations = {
            1: recommandation(1, "SITE001"),
            2: recommandation(2, "SITE002"),
            9: recommandation(9, "SITE-AUTRE"),
        }
        self.sites_attribues: dict[UUID, set[str]] = {}
        # Actions confirmées : id -> (utilisateur, statut de la décision)
        self.prises: dict[int, UUID] = {}
        self.decisions: dict[int, tuple[UUID, str]] = {}
        self._en_cours: list[tuple[str, int, UUID, str | None]] = []
        # Action enregistrée par quelqu'un d'autre entre la lecture et l'ajout
        self.action_concurrente = False
        self.commits = 0

    def _visible(self, id_site: str, parametres: dict[str, Any]) -> bool:
        id_client = parametres["id_client"]
        if id_client is not None and SITES[id_site] != id_client:
            return False
        limite = parametres["id_utilisateur_sites"]
        return limite is None or id_site in self.sites_attribues.get(limite, set())

    def execute(self, requete: Any, parametres: dict[str, Any]) -> Resultat:
        sql = " ".join(str(requete).split())
        if "FROM app.alerte_etat" in sql:
            ligne = self.alertes.get(parametres["id_alerte"])
            if ligne is None or not self._visible(ligne["id_site"], parametres):
                return Resultat([])
            prise_par = self.prises.get(ligne["id_alerte"])
            return Resultat(
                [
                    {
                        **ligne,
                        "prise_en_compte": prise_par is not None,
                        "prise_par": prise_par,
                        "prise_le": MAINTENANT if prise_par else None,
                    }
                ]
            )
        if "FROM app.recommandation_etat" in sql:
            ligne = self.recommandations.get(parametres["id_recommandation"])
            if ligne is None or not self._visible(ligne["id_site"], parametres):
                return Resultat([])
            decision = self.decisions.get(ligne["id_recommandation"])
            return Resultat(
                [
                    {
                        **ligne,
                        "statut": decision[1] if decision else "proposee",
                        "decide_par": decision[0] if decision else None,
                        "decide_le": MAINTENANT if decision else None,
                    }
                ]
            )
        if sql.startswith("SELECT 1 FROM app.utilisateur_site"):
            sites = self.sites_attribues.get(parametres["id"], set())
            return Resultat([{"ok": 1}] if parametres["id_site"] in sites else [])
        if sql.startswith("INSERT INTO app.prise_en_compte_alerte"):
            if self.action_concurrente:
                return Resultat([])  # ON CONFLICT DO NOTHING : rien d'ajouté
            self._en_cours.append(
                ("prise", parametres["id_alerte"], parametres["id_utilisateur"], None)
            )
            return Resultat([{"id_prise_en_compte": 1}])
        if sql.startswith("INSERT INTO app.decision_recommandation"):
            if self.action_concurrente:
                return Resultat([])
            self._en_cours.append(
                (
                    "decision",
                    parametres["id_recommandation"],
                    parametres["id_utilisateur"],
                    parametres["statut"],
                )
            )
            return Resultat([{"id_decision": 1}])
        raise AssertionError(f"Requête inattendue : {sql}")

    def commit(self) -> None:
        for nature, id_objet, id_utilisateur, statut in self._en_cours:
            if nature == "prise":
                self.prises[id_objet] = id_utilisateur
            else:
                self.decisions[id_objet] = (id_utilisateur, statut or "")
        self._en_cours.clear()
        self.commits += 1

    def rollback(self) -> None:
        self._en_cours.clear()


@pytest.fixture
def base() -> FausseBase:
    return FausseBase()


@pytest.fixture
def client(base: FausseBase) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: base
    yield TestClient(app)
    app.dependency_overrides.clear()


def connecter(*roles: str, id_client: int | None = 1) -> Utilisateur:
    utilisateur = replace(
        UTILISATEUR_AUTORISE, roles=frozenset(roles), id_client=id_client
    )
    app.dependency_overrides[utilisateur_courant] = lambda: utilisateur
    return utilisateur


def prendre(client: TestClient, id_alerte: int) -> Any:
    return client.post(f"/api/alertes/{id_alerte}/prise-en-compte")


def decider(client: TestClient, id_recommandation: int, statut: str) -> Any:
    return client.post(
        f"/api/recommandations/{id_recommandation}/decision", json={"statut": statut}
    )


# Une action de chaque sorte, sur SITE001, pour les règles d'accès communes
ACTIONS = [
    pytest.param(lambda c: prendre(c, 1), id="prise-en-compte"),
    pytest.param(lambda c: decider(c, 1, "acceptee"), id="decision"),
]


# --- 401 et 403 : qui peut agir ---------------------------------------------------


@pytest.mark.parametrize("action", ACTIONS)
def test_sans_jeton_401(client: TestClient, action: Any) -> None:
    assert action(client).status_code == 401


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize(
    "roles",
    [["CONSULT-SITE"], ["CONSULT-CLIENT"], ["MONITORING"], []],
    ids=["consult-site", "consult-client", "monitoring", "sans-role"],
)
def test_role_de_consultation_403(
    client: TestClient, base: FausseBase, action: Any, roles: list[str]
) -> None:
    utilisateur = connecter(*roles)
    base.sites_attribues = {utilisateur.id: {"SITE001"}}

    assert action(client).status_code == 403
    assert base.commits == 0


@pytest.mark.parametrize("action", ACTIONS)
def test_gestion_client_agit_sur_tous_les_sites_du_client(
    client: TestClient, action: Any
) -> None:
    connecter("GESTION-CLIENT")
    assert action(client).status_code == 200


@pytest.mark.parametrize("action", ACTIONS)
def test_gestion_site_agit_sur_ses_sites(
    client: TestClient, base: FausseBase, action: Any
) -> None:
    utilisateur = connecter("GESTION-SITE")
    base.sites_attribues = {utilisateur.id: {"SITE001"}}

    assert action(client).status_code == 200


def test_gestion_site_ne_voit_pas_les_autres_sites_404(
    client: TestClient, base: FausseBase
) -> None:
    # SITE002 est au client, mais pas attribué : invisible, comme dans les listes
    utilisateur = connecter("GESTION-SITE")
    base.sites_attribues = {utilisateur.id: {"SITE001"}}

    assert prendre(client, 2).status_code == 404
    assert decider(client, 2, "acceptee").status_code == 404


def test_gestion_site_qui_voit_le_site_sans_le_gerer_403(
    client: TestClient, base: FausseBase
) -> None:
    # CONSULT-CLIENT ouvre la lecture de tout le client ; GESTION-SITE n'ouvre les
    # actions que sur les sites attribués
    utilisateur = connecter("CONSULT-CLIENT", "GESTION-SITE")
    base.sites_attribues = {utilisateur.id: {"SITE001"}}

    assert prendre(client, 2).status_code == 403
    assert decider(client, 2, "refusee").status_code == 403
    assert prendre(client, 1).status_code == 200


def test_site_d_un_autre_client_404(client: TestClient) -> None:
    connecter("GESTION-CLIENT")
    assert prendre(client, 9).status_code == 404
    assert decider(client, 9, "acceptee").status_code == 404


def test_administrateur_enervision_agit_sur_tous_les_clients(
    client: TestClient,
) -> None:
    connecter("GESTION-CLIENT", id_client=None)
    assert prendre(client, 9).status_code == 200
    assert decider(client, 9, "acceptee").status_code == 200


# --- Prise en compte d'une alerte ---------------------------------------------------


def test_prise_en_compte_enregistree_et_renvoyee(
    client: TestClient, base: FausseBase
) -> None:
    utilisateur = connecter("GESTION-CLIENT")

    response = prendre(client, 1)

    assert response.status_code == 200
    corps = response.json()
    assert corps["id_alerte"] == 1
    assert corps["prise_en_compte"] is True
    assert corps["prise_par"] == str(utilisateur.id)
    assert base.prises == {1: utilisateur.id}


def test_deuxieme_prise_en_compte_409(client: TestClient, base: FausseBase) -> None:
    connecter("GESTION-CLIENT")
    base.prises = {1: AUTRE_UTILISATEUR}

    response = prendre(client, 1)

    assert response.status_code == 409
    assert base.prises == {1: AUTRE_UTILISATEUR}


def test_alerte_terminee_409(client: TestClient, base: FausseBase) -> None:
    connecter("GESTION-CLIENT")

    assert prendre(client, 3).status_code == 409
    assert base.prises == {}


def test_prise_en_compte_simultanee_409(client: TestClient, base: FausseBase) -> None:
    # Une autre personne a pris l'alerte entre la lecture et l'ajout
    connecter("GESTION-CLIENT")
    base.action_concurrente = True

    assert prendre(client, 1).status_code == 409
    assert base.commits == 0


def test_alerte_inconnue_404(client: TestClient) -> None:
    connecter("GESTION-CLIENT")
    assert prendre(client, 404).status_code == 404


@pytest.mark.parametrize("id_alerte", ["0", "abc", str(2**63)])
def test_identifiant_invalide_422(client: TestClient, id_alerte: str) -> None:
    connecter("GESTION-CLIENT")
    assert client.post(f"/api/alertes/{id_alerte}/prise-en-compte").status_code == 422


# --- Décision sur une recommandation ------------------------------------------------


@pytest.mark.parametrize("statut", ["acceptee", "refusee"])
def test_decision_enregistree_et_renvoyee(
    client: TestClient, base: FausseBase, statut: str
) -> None:
    utilisateur = connecter("GESTION-CLIENT")

    response = decider(client, 1, statut)

    assert response.status_code == 200
    corps = response.json()
    assert corps["statut"] == statut
    assert corps["decide_par"] == str(utilisateur.id)
    assert base.decisions == {1: (utilisateur.id, statut)}


def test_pas_de_changement_de_decision_409(
    client: TestClient, base: FausseBase
) -> None:
    connecter("GESTION-CLIENT")
    base.decisions = {1: (AUTRE_UTILISATEUR, "acceptee")}

    response = decider(client, 1, "refusee")

    assert response.status_code == 409
    assert base.decisions == {1: (AUTRE_UTILISATEUR, "acceptee")}


def test_decision_simultanee_409(client: TestClient, base: FausseBase) -> None:
    connecter("GESTION-CLIENT")
    base.action_concurrente = True

    assert decider(client, 1, "acceptee").status_code == 409
    assert base.commits == 0


def test_recommandation_inconnue_404(client: TestClient) -> None:
    connecter("GESTION-CLIENT")
    assert decider(client, 404, "acceptee").status_code == 404


@pytest.mark.parametrize(
    "corps",
    [{"statut": "proposee"}, {"statut": "peut-etre"}, {}, None],
    ids=["proposee", "inconnu", "sans-statut", "sans-corps"],
)
def test_statut_invalide_422(client: TestClient, base: FausseBase, corps: Any) -> None:
    connecter("GESTION-CLIENT")

    response = client.post("/api/recommandations/1/decision", json=corps)

    assert response.status_code == 422
    assert base.decisions == {}


def test_corps_illisible_400(client: TestClient, base: FausseBase) -> None:
    """Octets quelconques, comme ceux de Schemathesis : FastAPI ne peut pas lire le corps
    et répond 400 (un JSON mal formé, lui, donne 422), documenté dans le contrat."""
    connecter("GESTION-CLIENT")

    response = client.post(
        "/api/recommandations/1/decision",
        content=b"\xff\xfe.\xc3[",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert base.decisions == {}


def test_corps_illisible_400_documente(client: TestClient) -> None:
    chemins = client.get("/api/openapi.json").json()["paths"]
    route = chemins["/api/recommandations/{id_recommandation}/decision"]["post"]
    assert "400" in route["responses"]
