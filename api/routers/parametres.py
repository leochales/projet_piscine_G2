"""Paramètres communs aux routes."""

from typing import Annotated

from fastapi import Path, Query

# Identifiant de site de l'API Mock (app.site.id_site, VARCHAR(20))
MOTIF_ID_SITE = r"^[A-Za-z0-9_-]{1,20}$"

# Site dans le chemin : /sites/{id_site}/...
IdSite = Annotated[str, Path(pattern=MOTIF_ID_SITE)]

# Filtre facultatif sur un site : ?id_site=...
FiltreSite = Annotated[str | None, Query(pattern=MOTIF_ID_SITE)]
