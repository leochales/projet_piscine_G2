"""Paramètres communs aux routes."""

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Path, Query, Request
from fastapi.dependencies.models import Dependant
from fastapi.exceptions import RequestValidationError

# Identifiant de site de l'API Mock (app.site.id_site, VARCHAR(20))
MOTIF_ID_SITE = r"^[A-Za-z0-9_-]{1,20}$"

# Site dans le chemin : /sites/{id_site}/...
IdSite = Annotated[str, Path(pattern=MOTIF_ID_SITE)]

# Filtre facultatif sur un site : ?id_site=...
FiltreSite = Annotated[str | None, Query(pattern=MOTIF_ID_SITE)]

# Identifiant BIGINT dans le chemin : /alertes/{id_alerte}/... Borné pour qu'un nombre
# trop grand donne 422, et non une erreur de PostgreSQL (500)
IdNumerique = Annotated[int, Path(ge=1, le=2**63 - 1)]

# Réponse ajoutée au Swagger des routes : un paramètre inconnu ou invalide donne 422,
# y compris sur les routes sans paramètre (contrat vérifié par Schemathesis)
REPONSE_PARAMETRES: dict[int | str, dict[str, Any]] = {
    422: {"description": "Paramètre invalide ou inconnu"},
}


def _parametres_declares(dependant: Dependant) -> Iterator[str]:
    """Noms des paramètres de requête de la route et de toutes ses dépendances."""
    for parametre in dependant.query_params:
        yield parametre.alias
    for sous_dependance in dependant.dependencies:
        yield from _parametres_declares(sous_dependance)


def refuser_parametres_inconnus(request: Request) -> None:
    """Dépendance : 422 si l'URL contient un paramètre que la route ne déclare pas.

    FastAPI ignore sinon les paramètres inconnus : une faute de frappe (?id_stie=…)
    renverrait toutes les données sans filtre, sans erreur.
    """
    route = request.scope.get("route")
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return
    inconnus = sorted(set(request.query_params) - set(_parametres_declares(dependant)))
    if inconnus:
        raise RequestValidationError(
            [
                {
                    "type": "extra_forbidden",
                    "loc": ("query", nom),
                    "msg": "Paramètre inconnu",
                    "input": request.query_params.get(nom),
                }
                for nom in inconnus
            ]
        )
