"""Règles d'accès de l'API : jetons Keycloak (401), rôles (403), routes protégées.

Keycloak n'est pas démarré : les jetons sont signés avec une clé RSA générée pour
les tests, et le client des clés est remplacé par un faux qui renvoie cette clé.
"""

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from api.auth import exiger_role, get_client_cles, retrouver_id_client
from api.main import app
from api.routers.health import database_status
from common.config import get_settings
from common.db import get_session

CLE_KEYCLOAK = rsa.generate_private_key(public_exponent=65537, key_size=2048)
AUTRE_CLE = rsa.generate_private_key(public_exponent=65537, key_size=2048)

SUB = "8f2c6c1e-4b7a-4d55-9a57-1f0e3b2f6a10"
ROUTE_PROTEGEE = "/api/sites/derniere-mesure"

# Routes /api volontairement publiques : santé et documentation
ROUTES_PUBLIQUES = {
    "/api/health",
    "/api/docs",
    "/api/docs/oauth2-redirect",
    "/api/openapi.json",
}


class FausseCle:
    def __init__(self, cle: Any) -> None:
        self.key = cle


class FauxClientCles:
    """Remplace PyJWKClient : renvoie la clé publique de « Keycloak »."""

    def get_signing_key_from_jwt(self, jeton: str) -> FausseCle:
        jwt.get_unverified_header(jeton)  # un jeton illisible lève DecodeError
        return FausseCle(CLE_KEYCLOAK.public_key())


class ClientClesInjoignable:
    def get_signing_key_from_jwt(self, jeton: str) -> FausseCle:
        raise jwt.PyJWKClientConnectionError("Keycloak injoignable")


class Resultat:
    def __init__(self, lignes: list[dict[str, Any]]) -> None:
        self.lignes = lignes

    def mappings(self) -> "Resultat":
        return self

    def first(self) -> dict[str, Any] | None:
        return self.lignes[0] if self.lignes else None

    def all(self) -> list[dict[str, Any]]:
        return self.lignes


class FausseBase:
    """Session simulée : table app.utilisateur en mémoire.

    Par défaut, l'utilisateur du jeton est enregistré (compte créé par l'API,
    SMARTOPS-84) et rattaché au client 1.
    """

    def __init__(self) -> None:
        self.utilisateurs: dict[UUID, int | None] = {UUID(SUB): 1}
        self.requetes: list[str] = []

    def execute(
        self, requete: Any, parametres: dict[str, Any] | None = None
    ) -> Resultat:
        sql = str(requete)
        self.requetes.append(sql)
        parametres = parametres or {}
        if "FROM app.utilisateur" in sql:
            if parametres["id"] in self.utilisateurs:
                return Resultat([{"id_client": self.utilisateurs[parametres["id"]]}])
            return Resultat([])
        return Resultat([])  # requêtes des routes métier : aucune donnée


NUL = object()  # champ présent dans le jeton, avec la valeur null


def creer_jeton(
    cle: Any = CLE_KEYCLOAK,
    algorithme: str = "RS256",
    roles: list[str] | None = None,
    **modifications: Any,
) -> str:
    """Jeton semblable à ceux de Keycloak ; chaque test en change un champ."""
    settings = get_settings()
    maintenant = datetime.now(UTC)
    contenu: dict[str, Any] = {
        "iss": settings.keycloak_emetteur,
        "aud": [settings.keycloak_audience, "account"],
        "sub": SUB,
        "iat": maintenant,
        "exp": maintenant + timedelta(minutes=5),
        "realm_access": {"roles": ["CONSULT-SITE"] if roles is None else roles},
    }
    contenu.update(modifications)
    # None retire le champ du jeton ; NUL le garde avec la valeur null
    contenu = {
        nom: None if valeur is NUL else valeur
        for nom, valeur in contenu.items()
        if valeur is not None
    }
    return jwt.encode(contenu, cle, algorithm=algorithme)


def entete(jeton: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jeton}"}


@pytest.fixture
def base() -> FausseBase:
    return FausseBase()


@pytest.fixture
def client(base: FausseBase) -> Iterator[TestClient]:
    app.dependency_overrides[get_client_cles] = FauxClientCles
    app.dependency_overrides[get_session] = lambda: base
    yield TestClient(app)
    app.dependency_overrides.clear()


# --- 401 : jeton absent ou invalide ------------------------------------------


def test_sans_jeton_401(client: TestClient) -> None:
    response = client.get(ROUTE_PROTEGEE)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_autre_schema_que_bearer_401(client: TestClient) -> None:
    response = client.get(ROUTE_PROTEGEE, headers={"Authorization": "Basic YTpi"})
    assert response.status_code == 401


def test_jeton_illisible_401(client: TestClient) -> None:
    response = client.get(ROUTE_PROTEGEE, headers=entete("pas-un-jeton"))
    assert response.status_code == 401


def test_signature_d_une_autre_cle_401(client: TestClient) -> None:
    jeton = creer_jeton(cle=AUTRE_CLE)
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 401


def test_jeton_signe_en_hs256_401(client: TestClient) -> None:
    # Algorithme symétrique refusé : seul RS256 (clé publique de Keycloak) est accepté
    jeton = creer_jeton(cle="secret-devine-par-un-attaquant-32o", algorithme="HS256")
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 401


def test_jeton_non_signe_401(client: TestClient) -> None:
    jeton = creer_jeton(cle=None, algorithme="none")
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 401


def test_mauvais_emetteur_401(client: TestClient) -> None:
    # Ex. jeton obtenu sur l'adresse interne de Keycloak au lieu de l'adresse publique
    jeton = creer_jeton(iss="http://keycloak:8080/auth/realms/enervision")
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 401


def test_mauvaise_audience_401(client: TestClient) -> None:
    jeton = creer_jeton(aud="account")
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 401


def test_jeton_expire_401(client: TestClient) -> None:
    jeton = creer_jeton(exp=datetime.now(UTC) - timedelta(minutes=1))
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 401


def test_jeton_sans_expiration_401(client: TestClient) -> None:
    jeton = creer_jeton(exp=None)
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 401


def test_sub_qui_n_est_pas_un_uuid_401(client: TestClient) -> None:
    jeton = creer_jeton(sub="service-account-enervision-admin")
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 401


# --- 403 : rôle insuffisant ---------------------------------------------------


def test_sans_role_403(client: TestClient) -> None:
    jeton = creer_jeton(roles=[])
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 403


def test_role_monitoring_seul_403(client: TestClient) -> None:
    jeton = creer_jeton(roles=["MONITORING"])
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 403


def test_jeton_sans_realm_access_403(client: TestClient) -> None:
    jeton = creer_jeton(realm_access=None)
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 403


def test_realm_access_null_403_et_pas_500(client: TestClient) -> None:
    jeton = creer_jeton(realm_access=NUL)
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 403


def test_roles_null_403_et_pas_500(client: TestClient) -> None:
    jeton = creer_jeton(realm_access={"roles": None})
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 403


# --- Accès autorisé -----------------------------------------------------------


@pytest.mark.parametrize(
    "role", ["CONSULT-SITE", "CONSULT-CLIENT", "GESTION-SITE", "GESTION-CLIENT"]
)
def test_role_metier_autorise(client: TestClient, role: str) -> None:
    jeton = creer_jeton(roles=[role])
    assert client.get(ROUTE_PROTEGEE, headers=entete(jeton)).status_code == 200


def test_utilisateur_absent_de_la_base_403(
    client: TestClient, base: FausseBase
) -> None:
    # Compte créé hors de l'API (ex. console Keycloak) : entreprise inconnue
    base.utilisateurs = {}

    response = client.get(ROUTE_PROTEGEE, headers=entete(creer_jeton()))

    assert response.status_code == 403
    assert response.json() == {"detail": "Compte non rattaché à un client"}


def test_l_api_ne_cree_jamais_d_utilisateur(
    client: TestClient, base: FausseBase
) -> None:
    base.utilisateurs = {}

    client.get(ROUTE_PROTEGEE, headers=entete(creer_jeton()))

    assert base.utilisateurs == {}
    assert not any("INSERT" in requete for requete in base.requetes)


@pytest.mark.parametrize("id_client", [7, None])
def test_retrouver_id_client_lit_le_client_enregistre(id_client: int | None) -> None:
    # None : administrateur EnerVision, rattaché à aucun client
    base = FausseBase()
    base.utilisateurs = {UUID(SUB): id_client}

    assert retrouver_id_client(base, UUID(SUB)) == id_client  # type: ignore[arg-type]


# --- Keycloak injoignable -----------------------------------------------------


def test_keycloak_injoignable_503(client: TestClient) -> None:
    app.dependency_overrides[get_client_cles] = ClientClesInjoignable
    response = client.get(ROUTE_PROTEGEE, headers=entete(creer_jeton()))
    assert response.status_code == 503


# --- Routes protégées ---------------------------------------------------------


def test_health_reste_public(client: TestClient) -> None:
    app.dependency_overrides[database_status] = lambda: True
    assert client.get("/api/health").status_code == 200


def test_toutes_les_routes_api_exigent_un_jeton(client: TestClient) -> None:
    """Filet de sécurité : une nouvelle route oubliée sans exiger_role fait échouer ce test."""
    chemins = client.get("/api/openapi.json").json()["paths"]
    routes = [
        (methode.upper(), chemin)
        for chemin, operations in chemins.items()
        if chemin not in ROUTES_PUBLIQUES
        for methode in operations
    ]
    assert routes, "aucune route protégée trouvée"

    for methode, chemin in routes:
        url = re.sub(r"\{[^}]+\}", "x", chemin)  # paramètres de chemin quelconques
        response = client.request(methode, url)
        assert response.status_code == 401, f"{methode} {chemin} est ouverte"


def test_swagger_declare_le_jeton_bearer(client: TestClient) -> None:
    schema = client.get("/api/openapi.json").json()

    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    reponses = schema["paths"][ROUTE_PROTEGEE]["get"]["responses"]
    assert {"401", "403"} <= set(reponses)


def test_exiger_role_sans_role_est_une_erreur_de_code() -> None:
    with pytest.raises(ValueError):
        exiger_role()
