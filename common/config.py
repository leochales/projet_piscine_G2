"""Configuration lue dans les variables d'environnement (et le .env à la racine)."""

from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "enervision"
    postgres_password: str = "changeme"
    postgres_db: str = "enervision"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Origines autorisées à appeler l'API depuis un navigateur (front en dev).
    # Derrière Traefik, front et API partagent la même origine : CORS inutile.
    api_cors_origins: list[str] = ["http://localhost:5173"]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
