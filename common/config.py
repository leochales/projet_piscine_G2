"""Configuration lue dans les variables d'environnement (et le .env à la racine)."""

from decimal import Decimal
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Pas de valeur par défaut : l'API refuse de démarrer si le .env est incomplet
    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Origines autorisées à appeler l'API depuis un navigateur (front en dev).
    # Derrière Traefik, front et API partagent la même origine : CORS inutile.
    api_cors_origins: list[str] = ["http://localhost:5173"]

    # Prix de l'électricité en € HT par kWh (tarif fixe provisoire)
    prix_kwh_eur: Decimal = Decimal("0.14")

    # API Mock externe — source de données IoT simulées
    mock_api_url: str = "http://10.43.43.80:8000"

    # Keycloak. L'API lit les clés de signature en interne (réseau Docker), mais
    # l'émetteur des jetons (iss) est l'adresse publique, vue par le navigateur.
    keycloak_url_interne: str = "http://keycloak:8080/auth"
    keycloak_realm: str = "enervision"
    keycloak_emetteur: str = "http://localhost/auth/realms/enervision"
    keycloak_audience: str = "enervision-api"

    # Client auquel est rattaché un utilisateur inconnu de app.utilisateur à sa
    # première connexion (MVP : un seul client pilote)
    client_pilote: str = "Démo EnerVision"

    @property
    def keycloak_url_cles(self) -> str:
        """Adresse des clés publiques (JWKS) du realm, jointe en interne."""
        return (
            f"{self.keycloak_url_interne}/realms/{self.keycloak_realm}"
            "/protocol/openid-connect/certs"
        )

    @property
    def database_url(self) -> str:
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    # Les champs sont remplis par l'environnement, ce que mypy ne voit pas
    return Settings()  # type: ignore[call-arg]
