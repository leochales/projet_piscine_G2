"""Configuration lue dans les variables d'environnement (et le .env à la racine)."""

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
    prix_kwh_eur: float = 0.14

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
