from uuid import UUID

from api.auth import Utilisateur

# Les règles d'accès sont testées dans test_auth.py : les tests des routes de données
# remplacent l'utilisateur connecté par celui-ci (dependency_overrides[utilisateur_courant])
UTILISATEUR_AUTORISE = Utilisateur(
    id=UUID("00000000-0000-0000-0000-000000000001"),
    id_client=1,
    roles=frozenset({"CONSULT-CLIENT"}),
)
