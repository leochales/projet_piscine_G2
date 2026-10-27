from typing import Any, Self
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from api import seed
from api.auth import ROLES_APPLICATION, ROLES_SITE
from api.seed import CompteDemo, mot_de_passe_demo, seeder
from api.services.comptes import ErreurCompte, NouveauCompte
from common.config import Settings

SITE = CompteDemo(
    "site@demo.test", "Cyril", "Site", ["CONSULT-SITE"], "Démo", ["SITE001"]
)
ADMIN = CompteDemo("admin@demo.test", "Alice", "Admin", ["GESTION-CLIENT"], None)


class FauxKeycloak:
    def __init__(self, existants: dict[str, UUID] | None = None) -> None:
        self.comptes = dict(existants or {})
        self.crees: list[NouveauCompte] = []
        self.roles: dict[UUID, list[str]] = {}
        self.echecs_roles = 0  # nombre d'attributions de rôles qui échouent (timeout)

    def chercher(self, email: str) -> UUID | None:
        return self.comptes.get(email)

    def creer(self, compte: NouveauCompte, mot_de_passe: str) -> UUID:
        self.comptes[compte.email] = uuid4()
        self.crees.append(compte)
        return self.comptes[compte.email]

    def attribuer_roles(self, id_utilisateur: UUID, roles: list[str]) -> None:
        if self.echecs_roles:
            self.echecs_roles -= 1
            raise ErreurCompte("Keycloak : délai dépassé")
        self.roles[id_utilisateur] = roles


class FausseBase:
    """Session SQLAlchemy réduite aux requêtes du seeding, avec commit et rollback."""

    def __init__(self, enregistres: dict[UUID, int | None] | None = None) -> None:
        self.clients = {"Démo": 1}
        self.sites = {"SITE001": 1, "SITE-AUTRE": 2}
        self.utilisateurs = dict(enregistres or {})
        self.sites_attribues: set[tuple[UUID, str]] = set()
        self._en_cours: list[tuple[str, Any]] = []
        self.commits = 0

    def execute(self, requete: Any, parametres: dict[str, Any]) -> "Resultat":
        sql = " ".join(str(requete).split())
        if sql.startswith("SELECT id_client FROM app.client"):
            return Resultat(self.clients.get(parametres["nom"]))
        if sql.startswith("SELECT id_site FROM app.site"):
            client = parametres["id_client"]
            sites = [s for s in parametres["sites"] if self.sites.get(s) == client]
            return Resultat(sites)
        if sql.startswith("SELECT 1 FROM app.utilisateur WHERE"):
            return Resultat(1 if parametres["id"] in self.utilisateurs else None)
        if sql.startswith("INSERT INTO app.utilisateur "):
            self._en_cours.append(("utilisateur", parametres))
            return Resultat(None)
        if sql.startswith("SELECT 1 FROM app.utilisateur AS u JOIN app.site"):
            client = self._client(parametres["id"])
            site = self.sites.get(parametres["id_site"])
            return Resultat(1 if client is not None and site == client else None)
        if sql.startswith("INSERT INTO app.utilisateur_site"):
            self._en_cours.append(("site", parametres))
            return Resultat(None)
        raise AssertionError(f"Requête inattendue : {sql}")

    def _client(self, id_utilisateur: UUID) -> int | None:
        for nature, p in self._en_cours:
            if nature == "utilisateur" and p["id"] == id_utilisateur:
                return p["id_client"]
        return self.utilisateurs.get(id_utilisateur)

    def commit(self) -> None:
        for nature, p in self._en_cours:
            if nature == "utilisateur":
                self.utilisateurs.setdefault(p["id"], p["id_client"])
            else:
                self.sites_attribues.add((p["id"], p["id_site"]))
        self._en_cours.clear()
        self.commits += 1

    def rollback(self) -> None:
        self._en_cours.clear()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.rollback()


class Resultat:
    def __init__(self, valeur: Any) -> None:
        self.valeur = valeur

    def scalar(self) -> Any:
        return self.valeur

    def scalars(self) -> Any:
        return iter(self.valeur)

    def first(self) -> Any:
        return None if self.valeur is None else (self.valeur,)


def lancer(
    keycloak: FauxKeycloak,
    base: FausseBase,
    comptes: list[CompteDemo],
    prod: bool = False,
) -> int:
    return seeder(base, keycloak, "mot-de-passe-long", comptes, prod)  # type: ignore[arg-type]


def test_cree_les_comptes_avec_roles_client_et_sites() -> None:
    keycloak, base = FauxKeycloak(), FausseBase()

    assert lancer(keycloak, base, [SITE, ADMIN]) == 2

    id_site, id_admin = keycloak.comptes[SITE.email], keycloak.comptes[ADMIN.email]
    assert keycloak.roles == {id_site: ["CONSULT-SITE"], id_admin: ["GESTION-CLIENT"]}
    assert base.utilisateurs == {id_site: 1, id_admin: None}
    assert base.sites_attribues == {(id_site, "SITE001")}


def test_un_compte_deja_en_base_n_est_pas_modifie() -> None:
    id_existant = uuid4()
    keycloak = FauxKeycloak({SITE.email: id_existant})
    base = FausseBase({id_existant: 1})

    assert lancer(keycloak, base, [SITE]) == 0

    assert keycloak.crees == []
    assert keycloak.roles == {}
    assert base.sites_attribues == set()


def test_une_creation_interrompue_est_reprise_avec_ses_roles() -> None:
    # 1er démarrage : compte créé dans Keycloak, puis l'attribution des rôles échoue
    keycloak, base = FauxKeycloak(), FausseBase()
    keycloak.echecs_roles = 1
    with pytest.raises(ErreurCompte):
        lancer(keycloak, base, [SITE])
    id_keycloak = keycloak.comptes[SITE.email]
    assert base.utilisateurs == {}

    # Essai suivant : pas de nouveau compte, mais rôles, ligne en base et sites
    assert lancer(keycloak, base, [SITE]) == 1

    assert len(keycloak.crees) == 1
    assert keycloak.roles == {id_keycloak: ["CONSULT-SITE"]}
    assert base.utilisateurs == {id_keycloak: 1}
    assert base.sites_attribues == {(id_keycloak, "SITE001")}


@pytest.mark.parametrize(
    "mal_decrit",
    [
        CompteDemo("x@demo.test", "X", "X", ["CONSULT-CLIENT"], "Client inconnu"),
        CompteDemo("y@demo.test", "Y", "Y", ["CONSULT-SITE"], "Démo", ["SITE-AUTRE"]),
        CompteDemo("z@demo.test", "Z", "Z", ["CONSULT-SITE"], None, ["SITE001"]),
    ],
    ids=["client-inconnu", "site-d-un-autre-client", "sites-sans-client"],
)
def test_un_compte_mal_decrit_est_ignore_sans_bloquer_les_suivants(
    mal_decrit: CompteDemo,
) -> None:
    keycloak, base = FauxKeycloak(), FausseBase()

    assert lancer(keycloak, base, [mal_decrit, ADMIN]) == 1

    # Jamais créé dans Keycloak : vérifié avant
    assert [c.email for c in keycloak.crees] == [ADMIN.email]


def test_en_prod_les_comptes_hors_prod_ne_sont_pas_crees() -> None:
    tous_clients = CompteDemo(
        "t@demo.test", "T", "T", ["GESTION-CLIENT"], None, hors_prod=True
    )
    keycloak, base = FauxKeycloak(), FausseBase()

    assert lancer(keycloak, base, [tous_clients, SITE], prod=True) == 1

    assert [c.email for c in keycloak.crees] == [SITE.email]


def test_les_comptes_de_demo_sont_coherents() -> None:
    emails = [c.email for c in seed.COMPTES_DEMO]
    assert len(set(emails)) == len(emails)
    for compte in seed.COMPTES_DEMO:
        assert set(compte.roles) <= set(ROLES_APPLICATION), compte.email
        # Des sites seulement pour un compte limité à ses sites (rôles *-SITE seuls)
        limite_aux_sites = set(compte.roles) <= ROLES_SITE
        assert bool(compte.sites) == limite_aux_sites, compte.email
        # Sans client avec un rôle métier : toutes les données de tous les clients
        tous_les_clients = compte.client is None and set(compte.roles) - {"MONITORING"}
        assert compte.hors_prod == bool(tous_les_clients), compte.email


def _settings(**valeurs: Any) -> Settings:
    # _env_file=None : le test ne dépend pas du .env de la machine
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        postgres_user="u",
        postgres_password=SecretStr("p"),
        postgres_db="d",
        **valeurs,
    )


@pytest.mark.parametrize(
    "valeurs",
    [
        {},
        {"keycloak_admin_client_secret": "secret"},
        {"seed_password": "mot-de-passe-long"},
        {"seed_password": "", "keycloak_admin_client_secret": "secret"},
        {"seed_password": "court", "keycloak_admin_client_secret": "secret"},
    ],
    ids=["rien", "sans-mot-de-passe", "sans-secret", "mot-de-passe-vide", "trop-court"],
)
def test_seeding_desactive_sans_configuration_complete(valeurs: dict[str, str]) -> None:
    assert mot_de_passe_demo(_settings(**valeurs)) is None


def test_pas_de_tache_de_fond_sans_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seed, "get_settings", lambda: _settings())
    assert seed.lancer_en_arriere_plan() is None


def test_reessaie_tant_que_keycloak_ne_repond_pas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seed, "sessionmaker", lambda bind: FausseBase)
    monkeypatch.setattr(seed, "get_engine", lambda: None)
    appels: list[bool] = []

    def seeder_qui_echoue(*_: object, prod: bool) -> int:
        appels.append(prod)
        if len(appels) < 3:
            raise ErreurCompte("Keycloak injoignable")
        return 0

    monkeypatch.setattr(seed, "seeder", seeder_qui_echoue)
    settings = _settings(
        keycloak_admin_client_secret=SecretStr("secret"), deploy_env="prod"
    )
    seed.lancer_seeding(settings, "mot-de-passe-long", essais=5, attente=0)

    assert appels == [True, True, True]
