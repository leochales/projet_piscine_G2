"""Vérification des jetons Keycloak et des rôles.

Le front obtient un jeton d'accès auprès de Keycloak et l'envoie dans l'en-tête
« Authorization: Bearer <jeton> ». L'API vérifie ce jeton à chaque requête :
signature, émetteur, audience et expiration. Elle lit ensuite les rôles et
retrouve l'utilisateur dans app.utilisateur grâce au sub du jeton, pour connaître
son entreprise (le jeton ne la contient pas).

Pour protéger des routes :

    from api.auth import ROLES_METIER, exiger_role

    @router.get("/...", dependencies=[Depends(exiger_role(*ROLES_METIER))])

ou, pour récupérer l'utilisateur connecté dans la route :

    utilisateur: Annotated[Utilisateur, Depends(exiger_role("GESTION-CLIENT"))]
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from common.config import Settings, get_settings
from common.db import get_session

logger = logging.getLogger(__name__)

# Rôles du realm qui donnent accès aux données du dashboard. MONITORING sert
# seulement à la supervision : il n'ouvre pas les données métier.
ROLES_METIER = ("CONSULT-SITE", "CONSULT-CLIENT", "GESTION-SITE", "GESTION-CLIENT")

# Algorithme fixé ici, jamais lu dans l'en-tête du jeton : sinon un attaquant
# pourrait choisir « none » ou un algorithme symétrique (HS256).
ALGORITHMES = ["RS256"]

# auto_error=False : sans en-tête, FastAPI ne lève pas d'erreur lui-même.
# On renvoie nous-mêmes un 401 (selon les versions, FastAPI renverrait un 403).
schema_bearer = HTTPBearer(auto_error=False, description="Jeton d'accès Keycloak")

# Détail du 403 d'un compte absent de app.utilisateur. Le front le reconnaît pour
# afficher la page « compte non rattaché » (front/src/lib/api.ts) : à changer des deux côtés
DETAIL_COMPTE_NON_RATTACHE = "Compte non rattaché à un client"

# Réponses ajoutées au Swagger des routes protégées (contrat vérifié par Schemathesis)
REPONSES_AUTH: dict[int | str, dict[str, Any]] = {
    401: {"description": "Jeton absent ou invalide"},
    403: {"description": "Rôle insuffisant ou compte non rattaché à un client"},
    503: {"description": "Keycloak injoignable"},
}


@dataclass(frozen=True)
class Utilisateur:
    id: UUID
    id_client: int | None  # None : administrateur EnerVision, sans client
    roles: frozenset[str]


def refuser_jeton(detail: str) -> HTTPException:
    """Erreur 401 avec l'en-tête WWW-Authenticate exigé par la norme HTTP."""
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


# Délai minimal entre deux rechargements forcés des clés (s). Sans lui, des jetons
# portant un kid inventé feraient appeler Keycloak à chaque requête, sans compte.
DELAI_RECHARGEMENT_CLES = 60


@lru_cache
def get_client_cles() -> jwt.PyJWKClient:
    """Client des clés publiques de Keycloak, créé une seule fois.

    Les clés sont gardées en cache (1 h). Si un jeton est signé par une clé
    inconnue (rotation des clés dans Keycloak), le client recharge les clés, au
    plus une fois par DELAI_RECHARGEMENT_CLES.
    """
    return jwt.PyJWKClient(
        get_settings().keycloak_url_cles,
        lifespan=3600,
        timeout=5,
        cooldown_duration=DELAI_RECHARGEMENT_CLES,
    )


def lire_jeton(
    identifiants: Annotated[
        HTTPAuthorizationCredentials | None, Depends(schema_bearer)
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    client_cles: Annotated[jwt.PyJWKClient, Depends(get_client_cles)],
) -> dict[str, Any]:
    """Vérifie le jeton et renvoie son contenu. Lève 401 s'il est absent ou invalide."""
    if identifiants is None:
        raise refuser_jeton("Jeton manquant")
    jeton = identifiants.credentials

    try:
        cle = client_cles.get_signing_key_from_jwt(jeton)
        return jwt.decode(
            jeton,
            cle.key,
            algorithms=ALGORITHMES,
            audience=settings.keycloak_audience,
            issuer=settings.keycloak_emetteur,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWKClientConnectionError:
        # Problème de notre côté, pas un mauvais jeton : 503 et non 401
        logger.error("Clés de Keycloak injoignables : %s", settings.keycloak_url_cles)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Service d'authentification injoignable",
        ) from None
    except jwt.PyJWTError as erreur:
        # Le type d'erreur suffit pour comprendre un refus ; le jeton n'est jamais écrit
        logger.info("Jeton refusé : %s", type(erreur).__name__)
        raise refuser_jeton("Jeton invalide") from None


def retrouver_id_client(session: Session, id_utilisateur: UUID) -> int | None:
    """Renvoie le client de l'utilisateur, lu dans app.utilisateur.

    La ligne est écrite à la création du compte par l'API (SMARTOPS-84), qui
    connaît l'entreprise : celle du gestionnaire qui crée le compte. Le jeton ne
    contient pas l'entreprise, donc l'API ne crée jamais de ligne elle-même.
    Lève 403 si l'utilisateur est absent : compte créé hors de l'API (par exemple
    dans la console Keycloak), on ne sait pas à quelle entreprise il appartient.
    """
    requete = text("SELECT id_client FROM app.utilisateur WHERE id = :id")
    ligne = session.execute(requete, {"id": id_utilisateur}).mappings().first()
    if ligne is None:
        signaler_compte_absent(id_utilisateur)
        raise HTTPException(status.HTTP_403_FORBIDDEN, DETAIL_COMPTE_NON_RATTACHE)
    return ligne["id_client"]


# Un compte absent de app.utilisateur est signalé une fois par heure : le dashboard
# rappelle l'API chaque minute, chaque refus ne doit pas produire un avertissement
DELAI_SIGNALEMENT = 3600
_derniers_signalements: dict[UUID, float] = {}


def signaler_compte_absent(id_utilisateur: UUID) -> None:
    maintenant = time.monotonic()
    dernier = _derniers_signalements.get(id_utilisateur)
    if dernier is not None and maintenant - dernier < DELAI_SIGNALEMENT:
        logger.debug("Utilisateur absent de app.utilisateur : %s", id_utilisateur)
        return
    # Mémoire bornée : des jetons valides de comptes absents restent rares
    if len(_derniers_signalements) >= 1000:
        _derniers_signalements.clear()
    _derniers_signalements[id_utilisateur] = maintenant
    logger.warning(
        "Utilisateur absent de app.utilisateur (403 jusqu'à son enregistrement) : %s",
        id_utilisateur,
    )


def lire_roles(contenu: dict[str, Any]) -> frozenset[str]:
    """Rôles du realm (realm_access.roles), ou aucun si le champ est mal formé.

    Seule une liste de textes est acceptée : un texte seul ("GESTION-CLIENT")
    serait sinon découpé en caractères, et null ou un objet donnerait une erreur 500.
    Sans rôle, les routes protégées répondent 403.
    """
    realm_access = contenu.get("realm_access")
    roles = realm_access.get("roles") if isinstance(realm_access, dict) else None
    if not isinstance(roles, list):
        return frozenset()
    return frozenset(role for role in roles if isinstance(role, str))


def utilisateur_courant(
    contenu: Annotated[dict[str, Any], Depends(lire_jeton)],
    session: Annotated[Session, Depends(get_session)],
) -> Utilisateur:
    """Utilisateur connecté : identifiant (sub), client et rôles du realm."""
    try:
        id_utilisateur = UUID(contenu["sub"])
    except ValueError:
        raise refuser_jeton("Jeton invalide") from None

    roles = lire_roles(contenu)
    id_client = retrouver_id_client(session, id_utilisateur)
    return Utilisateur(id=id_utilisateur, id_client=id_client, roles=roles)


def client_courant(
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
) -> int | None:
    """Client dont l'utilisateur voit les données ; None : administrateur EnerVision (tous).

    utilisateur_courant n'est évalué qu'une fois par requête (cache des dépendances
    FastAPI) : pas de deuxième lecture de app.utilisateur.
    """
    return utilisateur.id_client


# Périmètre des routes de données : chaque requête ne lit que les sites du client de
# l'utilisateur. Condition écrite dans le SQL de chaque route (app.site en alias s) :
#   (CAST(:id_client AS BIGINT) IS NULL OR s.id_client = :id_client)
ClientCourant = Annotated[int | None, Depends(client_courant)]


def exiger_role(*roles_autorises: str) -> Callable[..., Utilisateur]:
    """Dépendance FastAPI : l'utilisateur doit avoir au moins un des rôles donnés (sinon 403)."""
    if not roles_autorises:
        raise ValueError("exiger_role attend au moins un rôle")

    def verifier_role(
        utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
    ) -> Utilisateur:
        if utilisateur.roles.isdisjoint(roles_autorises):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Rôle insuffisant")
        return utilisateur

    return verifier_role
