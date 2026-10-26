from typing import Any


class FausseSession:
    """Remplace la vraie session : garde la requête reçue et renvoie des lignes écrites à la main."""

    def __init__(self, lignes: list[dict[str, Any]]) -> None:
        self.lignes = lignes
        self.requete = ""
        self.parametres: dict[str, Any] = {}

    def execute(
        self, requete: Any, parametres: dict[str, Any] | None = None
    ) -> "FausseSession":
        self.requete = str(requete)
        self.parametres = parametres or {}
        return self

    def mappings(self) -> "FausseSession":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.lignes
