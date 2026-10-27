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

    def chercher(self, email: str) -> UUID | None:
        return self.comptes.get(email)

    def creer(self, compte: NouveauCompte, mot_de_passe: str) -> UUID:
        self.comptes[compte.email] = uuid4()
        self.crees.append(compte)
        return self.comptes[compte.email]


class FausseBase:
    """Session SQLAlchemy réduite aux requêtes du seeding (api/services/comptes.py)."""

    def __init__(self, enregistres: dict[UUID, int | None] | None = None) -> None:
        self.clients = {"Démo": 1}
        self.sites = {"SITE001": 1, "SITE-AUTRE": 2}
        self.utilisateurs = dict(enregistres or {})
        self.sites_attribues: set[tuple[UUID, str]] = set()
        self.commits = 0

    def execute(self, requete: Any, parametres: dict[str, Any]) -> "Resultat":
        sql = " ".join(str(requete).split())
        if sql.startswith("SELECT id_client FROM app.client"):
            return Resultat(self.clients.get(parametres["nom"]))
        if sql.startswith("SELECT 1 FROM app.utilisateur WHERE"):
            return Resultat(1 if parametres["id"] in self.utilisateurs else None)
        if sql.startswith("INSERT INTO app.utilisateur "):
            self.utilisateurs.setdefault(parametres["id"], parametres["id_client"])
            return Resultat(None)
        if sql.startswith("SELECT 1 FROM app.utilisateur AS u JOIN app.site"):
            client = self.utilisateurs.get(parametres["id"])
            meme_client = (
                client is not None and self.sites.get(parametres["id_site"]) == client
            )
            return Resultat(1 if meme_client else None)
        if sql.startswith("INSERT INTO app.utilisateur_site"):
            self.sites_attribues.add((parametres["id"], parametres["id_site"]))
            return Resultat(None)
        raise AssertionError(f"Requête inattendue : {sql}")

    def commit(self) -> None:
        self.commits += 1

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass


class Resultat:
    def __init__(self, valeur: Any) -> None:
        self.valeur = valeur

    def scalar(self) -> Any:
        return self.valeur

    def first(self) -> Any:
        return None if self.valeur is None else (self.valeur,)


def lancer(keycloak: FauxKeycloak, base: FausseBase, comptes: list[CompteDemo]) -> int:
    return seeder(base, keycloak, "mot-de-passe-long", comptes)  # type: ignore[arg-type]


def test_cree_les_comptes_avec_leur_client_et_leurs_sites() -> None:
    keycloak, base = FauxKeycloak(), FausseBase()

    assert lancer(keycloak, base, [SITE, ADMIN]) == 2

    assert [c.email for c in keycloak.crees] == [SITE.email, ADMIN.email]
    assert keycloak.crees[0].id_client == 1
    id_site = keycloak.comptes[SITE.email]
    assert base.utilisateurs == {id_site: 1, keycloak.comptes[ADMIN.email]: None}
    assert base.sites_attribues == {(id_site, "SITE001")}
    assert base.commits == 2


def test_un_compte_deja_en_base_n_est_pas_modifie() -> None:
    id_existant = uuid4()
    keycloak = FauxKeycloak({SITE.email: id_existant})
    base = FausseBase({id_existant: 1})

    assert lancer(keycloak, base, [SITE]) == 0

    assert keycloak.crees == []
    assert base.sites_attribues == set()


def test_un_compte_keycloak_absent_de_la_base_est_seulement_enregistre() -> None:
    id_keycloak = uuid4()
    keycloak = FauxKeycloak({SITE.email: id_keycloak})
    base = FausseBase()

    assert lancer(keycloak, base, [SITE]) == 1

    assert keycloak.crees == []
    assert base.utilisateurs == {id_keycloak: 1}
    assert base.sites_attribues == {(id_keycloak, "SITE001")}


def test_un_client_inconnu_ignore_le_compte() -> None:
    inconnu = CompteDemo("x@demo.test", "X", "X", ["CONSULT-CLIENT"], "Client inconnu")
    keycloak, base = FauxKeycloak(), FausseBase()

    assert lancer(keycloak, base, [inconnu, ADMIN]) == 1

    assert [c.email for c in keycloak.crees] == [ADMIN.email]


def test_un_site_d_un_autre_client_est_refuse() -> None:
    autre = CompteDemo(
        "y@demo.test", "Y", "Y", ["CONSULT-SITE"], "Démo", ["SITE-AUTRE"]
    )
    keycloak, base = FauxKeycloak(), FausseBase()

    with pytest.raises(ErreurCompte, match="SITE-AUTRE"):
        lancer(keycloak, base, [autre])
    assert base.commits == 0


def test_les_comptes_de_demo_sont_coherents() -> None:
    emails = [c.email for c in seed.COMPTES_DEMO]
    assert len(set(emails)) == len(emails)
    for compte in seed.COMPTES_DEMO:
        assert set(compte.roles) <= set(ROLES_APPLICATION), compte.email
        # Des sites seulement pour un compte limité à ses sites (rôles *-SITE seuls)
        limite_aux_sites = set(compte.roles) <= ROLES_SITE
        assert bool(compte.sites) == limite_aux_sites, compte.email


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


def test_reessaie_tant_que_keycloak_ne_repond_pas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(
        seed_password=SecretStr("mot-de-passe-long"),
        keycloak_admin_client_secret=SecretStr("secret"),
    )
    monkeypatch.setattr(seed, "get_settings", lambda: settings)
    monkeypatch.setattr(seed, "sessionmaker", lambda bind: FausseBase)
    monkeypatch.setattr(seed, "get_engine", lambda: None)
    appels: list[int] = []

    def seeder_qui_echoue(*_: object) -> int:
        appels.append(1)
        if len(appels) < 3:
            raise ErreurCompte("Keycloak injoignable")
        return 0

    monkeypatch.setattr(seed, "seeder", seeder_qui_echoue)
    seed.lancer_seeding(essais=5, attente=0)

    assert len(appels) == 3
