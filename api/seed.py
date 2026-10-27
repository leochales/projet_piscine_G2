"""Seeding : comptes de démonstration, créés au démarrage de l'API.

Comme le ferait un test, le seeding passe par les fonctions de l'application
(api/services/comptes.py) : création du compte dans Keycloak avec ses rôles, ligne en
base, puis attribution de ses sites.

  - Un compte déjà enregistré dans app.utilisateur n'est jamais modifié.
  - Un compte présent dans Keycloak mais pas en base (création interrompue) est repris :
    rôles réattribués, ligne en base, sites.
  - Un compte mal décrit (client ou site inconnu) est ignoré, avec un avertissement ;
    les suivants sont créés.
  - En prod, les comptes marqués hors_prod (accès à tous les clients) ne sont pas créés.

Sans SEED_PASSWORD ou sans KEYCLOAK_ADMIN_CLIENT_SECRET, rien n'est lancé. Le seeding
tourne en tâche de fond : l'API répond pendant qu'il attend Keycloak, et une erreur
n'est qu'écrite dans les logs.
"""

import logging
import threading
import time
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from api.services.comptes import (
    DonneeInvalide,
    KeycloakAdmin,
    NouveauCompte,
    creer_compte,
    est_enregistre,
    lier_site,
    sites_du_client,
    terminer_compte,
)
from common.config import Settings, get_settings
from common.db import get_engine

logger = logging.getLogger(__name__)

CLIENT_DEMO = "Démo EnerVision"  # client et sites créés par db/08_sites_demo.sql


@dataclass(frozen=True)
class CompteDemo:
    email: str
    prenom: str
    nom: str
    roles: list[str]
    client: str | None  # None : administrateur EnerVision (tous les clients)
    sites: list[str] = field(default_factory=list)  # rôles *-SITE seulement
    hors_prod: bool = False  # True : jamais créé en prod (DEPLOY_ENV=prod)


COMPTES_DEMO = [
    # Toutes les données de tous les clients : pas en prod
    CompteDemo(
        "admin@enervision.test",
        "Alice",
        "Admin",
        ["GESTION-CLIENT", "MONITORING"],
        None,
        hors_prod=True,
    ),
    CompteDemo(
        "gestion.client@demo.test", "Gaston", "Client", ["GESTION-CLIENT"], CLIENT_DEMO
    ),
    CompteDemo(
        "gestion.site@demo.test",
        "Gisèle",
        "Site",
        ["GESTION-SITE"],
        CLIENT_DEMO,
        ["SITE002", "SITE007"],
    ),
    CompteDemo(
        "consult.client@demo.test", "Camille", "Client", ["CONSULT-CLIENT"], CLIENT_DEMO
    ),
    CompteDemo(
        "consult.site@demo.test",
        "Cyril",
        "Site",
        ["CONSULT-SITE"],
        CLIENT_DEMO,
        ["SITE001"],
    ),
    CompteDemo(
        "monitoring@enervision.test", "Morgan", "Monitoring", ["MONITORING"], None
    ),
]

# Politique de mot de passe du realm (infra/keycloak/realm-enervision.json)
LONGUEUR_MIN_MOT_DE_PASSE = 12

# Keycloak peut finir de démarrer après l'API : nouvel essai toutes les 10 s, 5 min au plus
ESSAIS = 30
ATTENTE_ENTRE_ESSAIS = 10


def id_client(session: Session, nom: str) -> int | None:
    requete = text("SELECT id_client FROM app.client WHERE nom = :nom")
    return session.execute(requete, {"nom": nom}).scalar()


def preparer(session: Session, compte: CompteDemo) -> NouveauCompte:
    """Compte à créer, client résolu ; DonneeInvalide si le client ou un site est inconnu.

    Vérifié avant tout appel à Keycloak : un compte mal décrit n'y est jamais créé.
    """
    client = None
    if compte.client is not None:
        client = id_client(session, compte.client)
        if client is None:
            raise DonneeInvalide(f"client inconnu {compte.client!r}")
        # Requête seulement pour un compte limité à ses sites (rôles *-SITE)
        if compte.sites:
            inconnus = set(compte.sites) - sites_du_client(
                session, client, compte.sites
            )
            if inconnus:
                raise DonneeInvalide(
                    f"sites absents du client : {', '.join(sorted(inconnus))}"
                )
    elif compte.sites:
        raise DonneeInvalide("sites sans client")
    return NouveauCompte(compte.email, compte.prenom, compte.nom, compte.roles, client)


def seeder(
    session: Session,
    keycloak: KeycloakAdmin,
    mot_de_passe: str,
    comptes: list[CompteDemo] = COMPTES_DEMO,
    prod: bool = False,
) -> int:
    """Crée les comptes absents de la base ; renvoie le nombre de comptes ajoutés.

    Une panne de Keycloak ou de la base remonte à l'appelant, qui réessaie.
    """
    ajoutes = 0
    for compte in comptes:
        if prod and compte.hors_prod:
            continue
        existant = keycloak.chercher(compte.email)
        if existant is not None and est_enregistre(session, existant):
            continue
        try:
            nouveau = preparer(session, compte)
        except DonneeInvalide as erreur:
            logger.warning(
                "Compte de démonstration %s ignoré : %s", compte.email, erreur
            )
            continue

        if existant is None:
            id_utilisateur = creer_compte(session, keycloak, nouveau, mot_de_passe)
        else:
            # Création interrompue : rôles et ligne en base à reprendre
            id_utilisateur = existant
            terminer_compte(session, keycloak, id_utilisateur, nouveau)
        for id_site in compte.sites:
            lier_site(session, id_utilisateur, id_site)
        session.commit()
        logger.info("Compte de démonstration créé : %s", compte.email)
        ajoutes += 1
    return ajoutes


def mot_de_passe_demo(settings: Settings) -> str | None:
    """Mot de passe des comptes, ou None si le seeding n'est pas configuré."""
    # Variable vide (SEED_PASSWORD: ${SEED_PASSWORD:-} dans compose-prod.yml) : absente
    mot_de_passe = (
        settings.seed_password.get_secret_value() if settings.seed_password else ""
    )
    secret = settings.keycloak_admin_client_secret
    if not mot_de_passe or not (secret and secret.get_secret_value()):
        logger.info(
            "Seeding désactivé : SEED_PASSWORD ou KEYCLOAK_ADMIN_CLIENT_SECRET absent"
        )
        return None
    if len(mot_de_passe) < LONGUEUR_MIN_MOT_DE_PASSE:
        logger.error(
            "Seeding désactivé : SEED_PASSWORD fait moins de %d caractères",
            LONGUEUR_MIN_MOT_DE_PASSE,
        )
        return None
    return mot_de_passe


def lancer_seeding(
    settings: Settings,
    mot_de_passe: str,
    essais: int = ESSAIS,
    attente: float = ATTENTE_ENTRE_ESSAIS,
) -> None:
    """Seeding complet ; réessaie tant que Keycloak ou la base ne répondent pas."""
    session_factory = sessionmaker(bind=get_engine())
    prod = settings.deploy_env == "prod"
    for essai in range(1, essais + 1):
        try:
            with session_factory() as session:
                ajoutes = seeder(
                    session, KeycloakAdmin(settings), mot_de_passe, prod=prod
                )
        except Exception as erreur:  # noqa: BLE001 : le seeding n'arrête jamais l'API
            logger.warning("Seeding, essai %d/%d : %s", essai, essais, erreur)
            time.sleep(attente)
            continue
        logger.info("Seeding terminé : %d compte(s) créé(s)", ajoutes)
        return
    logger.error("Seeding abandonné après %d essais", essais)


def lancer_en_arriere_plan() -> threading.Thread | None:
    """Au démarrage de l'API : tâche de fond, seulement si le seeding est configuré."""
    settings = get_settings()
    mot_de_passe = mot_de_passe_demo(settings)
    if mot_de_passe is None:
        return None
    tache = threading.Thread(
        target=lancer_seeding,
        args=(settings, mot_de_passe),
        name="seeding",
        daemon=True,
    )
    tache.start()
    return tache
