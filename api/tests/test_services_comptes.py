import json
import urllib.error
import urllib.request
from email.message import Message
from typing import Any, ClassVar, Self
from uuid import UUID

import pytest
from pydantic import SecretStr

from api.services.comptes import (
    CompteExistant,
    ErreurCompte,
    KeycloakAdmin,
    NouveauCompte,
)
from common.config import Settings

ID = "19d0729a-e576-4c63-ae6a-8aa5842fc33a"
COMPTE = NouveauCompte("site@demo.test", "Cyril", "Site", ["CONSULT-SITE"], 1)


def _settings(**valeurs: Any) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        postgres_user="u",
        postgres_password=SecretStr("p"),
        postgres_db="d",
        keycloak_admin_client_secret=SecretStr("secret"),
        **valeurs,
    )


class FauxServeur:
    """Réponses de Keycloak, et requêtes reçues (méthode, chemin, corps)."""

    def __init__(self) -> None:
        self.requetes: list[tuple[str, str, Any]] = []

    def __call__(self, requete: urllib.request.Request) -> tuple[dict[str, str], bytes]:
        chemin = requete.full_url.split("/auth", 1)[1]
        corps = requete.data.decode() if isinstance(requete.data, bytes) else None
        self.requetes.append((requete.get_method(), chemin, corps))
        if chemin.endswith("/token"):
            return {}, json.dumps({"access_token": "jeton"}).encode()
        if chemin.endswith("/users"):
            return {
                "Location": f"http://keycloak:8080/auth/admin/realms/enervision/users/{ID}"
            }, b""
        if "/users?" in chemin:
            return {}, json.dumps([{"id": ID}]).encode()
        if "/roles/" in chemin:
            return {}, json.dumps({"name": chemin.rsplit("/", 1)[1]}).encode()
        return {}, b""


@pytest.fixture
def serveur(monkeypatch: pytest.MonkeyPatch) -> FauxServeur:
    faux = FauxServeur()
    monkeypatch.setattr(KeycloakAdmin, "_envoyer", lambda self, requete: faux(requete))
    return faux


def test_creer_envoie_le_compte_puis_ses_roles(serveur: FauxServeur) -> None:
    keycloak = KeycloakAdmin(_settings())

    assert keycloak.creer(COMPTE, "mot-de-passe-long") == UUID(ID)
    keycloak.attribuer_roles(UUID(ID), COMPTE.roles)

    assert [(m, c) for m, c, _ in serveur.requetes] == [
        ("POST", "/realms/enervision/protocol/openid-connect/token"),
        ("POST", "/admin/realms/enervision/users"),
        ("GET", "/admin/realms/enervision/roles/CONSULT-SITE"),
        ("POST", f"/admin/realms/enervision/users/{ID}/role-mappings/realm"),
    ]
    assert "client_id=enervision-admin" in serveur.requetes[0][2]
    creation = json.loads(serveur.requetes[1][2])
    assert creation["username"] == creation["email"] == COMPTE.email
    assert creation["credentials"] == [
        {"type": "password", "value": "mot-de-passe-long", "temporary": False}
    ]
    assert json.loads(serveur.requetes[3][2]) == [{"name": "CONSULT-SITE"}]


def test_chercher_par_email_exact(serveur: FauxServeur) -> None:
    keycloak = KeycloakAdmin(_settings())

    assert keycloak.chercher("site@demo.test") == UUID(ID)
    assert keycloak.chercher("autre@demo.test") == UUID(
        ID
    )  # le faux serveur répond toujours

    recherches = [c for m, c, _ in serveur.requetes if m == "GET"]
    assert recherches[0].endswith("/users?email=site%40demo.test&exact=true")
    # Jeton du compte de service demandé une seule fois
    assert sum(c.endswith("/token") for _, c, _ in serveur.requetes) == 1


def test_sans_secret_pas_de_client_keycloak() -> None:
    settings = _settings()
    settings.keycloak_admin_client_secret = None
    with pytest.raises(ErreurCompte, match="KEYCLOAK_ADMIN_CLIENT_SECRET"):
        KeycloakAdmin(settings)


def test_adresse_non_http_refusee() -> None:
    keycloak = KeycloakAdmin(_settings(keycloak_url_interne="file:///etc"))
    with pytest.raises(ErreurCompte, match="refusée"):
        keycloak.chercher("site@demo.test")


class ReponseJeton:
    status = 200
    headers: ClassVar[dict[str, str]] = {}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def read(self) -> bytes:
        return json.dumps({"access_token": "jeton"}).encode()


def test_email_deja_pris_leve_compte_existant(monkeypatch: pytest.MonkeyPatch) -> None:
    def keycloak(requete: urllib.request.Request, timeout: int) -> ReponseJeton:
        if requete.full_url.endswith("/token"):
            return ReponseJeton()
        # Création d'un compte dont l'e-mail existe : 409 Conflict
        raise urllib.error.HTTPError(requete.full_url, 409, "Conflict", Message(), None)

    monkeypatch.setattr(urllib.request, "urlopen", keycloak)
    with pytest.raises(CompteExistant):
        KeycloakAdmin(_settings()).creer(COMPTE, "mot-de-passe-long")
