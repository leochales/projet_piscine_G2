"""Comptes des utilisateurs : création dans Keycloak et enregistrement dans app.

Un compte existe à deux endroits, avec le même identifiant :
  - Keycloak : e-mail (identifiant de connexion), mot de passe et rôles ;
  - app.utilisateur : son client, et app.utilisateur_site : ses sites (rôles *-SITE).

Keycloak est appelé avec le compte de service du client enervision-admin, qui n'a de
droits que sur les utilisateurs du realm enervision. Utilisé par le seeding (api/seed.py),
et plus tard par la création des comptes depuis le dashboard (SMARTOPS-84).
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from common.config import Settings


class ErreurCompte(Exception):
    pass


class CompteExistant(ErreurCompte):
    """Un compte Keycloak a déjà cet e-mail."""


class DonneeInvalide(ErreurCompte):
    """Donnée refusée (client ou site) : réessayer ne changerait rien."""


@dataclass(frozen=True)
class NouveauCompte:
    email: str
    prenom: str
    nom: str
    roles: list[str]
    id_client: int | None  # None : administrateur EnerVision (tous les clients)


class KeycloakAdmin:
    """API d'administration de Keycloak, pour les utilisateurs du realm de l'application."""

    def __init__(self, settings: Settings) -> None:
        if settings.keycloak_admin_client_secret is None:
            raise ErreurCompte("KEYCLOAK_ADMIN_CLIENT_SECRET absent")
        base = settings.keycloak_url_interne
        realm = settings.keycloak_realm
        self.url_admin = f"{base}/admin/realms/{realm}"
        self.url_jeton = f"{base}/realms/{realm}/protocol/openid-connect/token"
        self.client_id = settings.keycloak_admin_client_id
        self.secret = settings.keycloak_admin_client_secret.get_secret_value()
        self._jeton: str | None = None

    def _envoyer(self, requete: urllib.request.Request) -> tuple[dict[str, str], bytes]:
        # Adresse interne fixée par la configuration, jamais par une donnée reçue
        if not requete.full_url.startswith(("http://", "https://")):
            raise ErreurCompte(f"Adresse de Keycloak refusée : {requete.full_url}")
        try:
            with urllib.request.urlopen(requete, timeout=10) as reponse:  # noqa: S310
                return dict(reponse.headers), reponse.read()
        except urllib.error.HTTPError as erreur:
            if erreur.code == 409:
                raise CompteExistant(requete.full_url) from None
            raise ErreurCompte(
                f"Keycloak : {requete.get_method()} {requete.full_url} : {erreur.code}"
            ) from None

    def _jeton_service(self) -> str:
        """Jeton du compte de service, demandé une fois par instance."""
        if self._jeton is None:
            corps = urllib.parse.urlencode(
                {
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.secret,
                }
            ).encode()
            _, contenu = self._envoyer(
                # Adresse vérifiée par _envoyer
                urllib.request.Request(self.url_jeton, data=corps)  # noqa: S310
            )
            self._jeton = json.loads(contenu)["access_token"]
        return self._jeton

    def _appeler(
        self, methode: str, chemin: str, corps: Any = None
    ) -> tuple[dict[str, str], Any]:
        # Adresse vérifiée par _envoyer
        requete = urllib.request.Request(  # noqa: S310
            f"{self.url_admin}{chemin}",
            method=methode,
            data=None if corps is None else json.dumps(corps).encode(),
            headers={
                "Authorization": f"Bearer {self._jeton_service()}",
                "Content-Type": "application/json",
            },
        )
        entetes, contenu = self._envoyer(requete)
        return entetes, json.loads(contenu) if contenu else None

    def chercher(self, email: str) -> UUID | None:
        """Identifiant du compte qui a cet e-mail, s'il existe."""
        query = urllib.parse.urlencode({"email": email, "exact": "true"})
        _, utilisateurs = self._appeler("GET", f"/users?{query}")
        return UUID(utilisateurs[0]["id"]) if utilisateurs else None

    def creer(self, compte: NouveauCompte, mot_de_passe: str) -> UUID:
        """Crée le compte avec son mot de passe, sans rôle ; renvoie son identifiant."""
        entetes, _ = self._appeler(
            "POST",
            "/users",
            {
                "username": compte.email,
                "email": compte.email,
                "firstName": compte.prenom,
                "lastName": compte.nom,
                "enabled": True,
                "emailVerified": True,
                "credentials": [
                    {"type": "password", "value": mot_de_passe, "temporary": False}
                ],
            },
        )
        # Adresse du compte créé : .../users/<identifiant>
        return UUID(entetes["Location"].rsplit("/", 1)[1])

    def attribuer_roles(self, id_utilisateur: UUID, roles: list[str]) -> None:
        """Ajoute les rôles du realm au compte ; sans effet sur un rôle déjà attribué."""
        representations = [
            self._appeler("GET", f"/roles/{urllib.parse.quote(role)}")[1]
            for role in roles
        ]
        self._appeler(
            "POST", f"/users/{id_utilisateur}/role-mappings/realm", representations
        )


def est_enregistre(session: Session, id_utilisateur: UUID) -> bool:
    requete = text("SELECT 1 FROM app.utilisateur WHERE id = :id")
    return session.execute(requete, {"id": id_utilisateur}).first() is not None


def enregistrer(session: Session, id_utilisateur: UUID, id_client: int | None) -> None:
    """Rattache un compte Keycloak à son client (app.utilisateur)."""
    session.execute(
        text(
            "INSERT INTO app.utilisateur (id, id_client) VALUES (:id, :id_client) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": id_utilisateur, "id_client": id_client},
    )


def creer_compte(
    session: Session, keycloak: KeycloakAdmin, compte: NouveauCompte, mot_de_passe: str
) -> UUID:
    """Crée le compte dans Keycloak, avec ses rôles, puis l'enregistre en base.

    Renvoie son identifiant. Lève CompteExistant si l'e-mail est déjà pris. Le commit
    est laissé à l'appelant : si une étape échoue, le compte peut exister dans Keycloak
    sans ligne en base ; le reprendre avec terminer_compte.
    """
    id_utilisateur = keycloak.creer(compte, mot_de_passe)
    terminer_compte(session, keycloak, id_utilisateur, compte)
    return id_utilisateur


def terminer_compte(
    session: Session,
    keycloak: KeycloakAdmin,
    id_utilisateur: UUID,
    compte: NouveauCompte,
) -> None:
    """Rôles dans Keycloak et ligne en base d'un compte Keycloak existant.

    Rejouable : reprend une création interrompue (rôles non attribués, ligne absente).
    """
    keycloak.attribuer_roles(id_utilisateur, compte.roles)
    enregistrer(session, id_utilisateur, compte.id_client)


def sites_du_client(session: Session, id_client: int, sites: list[str]) -> set[str]:
    """Parmi les sites donnés, ceux qui appartiennent au client."""
    requete = text(
        "SELECT id_site FROM app.site WHERE id_client = :id_client AND id_site = ANY(:sites)"
    )
    lignes = session.execute(requete, {"id_client": id_client, "sites": sites})
    return set(lignes.scalars())


def lier_site(session: Session, id_utilisateur: UUID, id_site: str) -> None:
    """Attribue un site à un compte ; le site doit appartenir au client du compte."""
    requete = text(
        """
        SELECT 1 FROM app.utilisateur AS u
        JOIN app.site AS s ON s.id_client = u.id_client
        WHERE u.id = :id AND s.id_site = :id_site
        """
    )
    parametres = {"id": id_utilisateur, "id_site": id_site}
    if session.execute(requete, parametres).first() is None:
        raise DonneeInvalide(
            f"Site {id_site} absent du client du compte {id_utilisateur}"
        )
    session.execute(
        text(
            "INSERT INTO app.utilisateur_site (id_utilisateur, id_site) "
            "VALUES (:id, :id_site) ON CONFLICT DO NOTHING"
        ),
        parametres,
    )
