from pydantic import SecretStr

from common.config import Settings


def make_settings() -> Settings:
    # _env_file=None : le test ne dépend pas du .env de la machine
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        postgres_user="api",
        postgres_password=SecretStr("s3cret"),
        postgres_db="enervision",
        postgres_host="db",
        postgres_port=5432,
    )


def test_database_url_assemble_les_identifiants() -> None:
    url = make_settings().database_url
    assert url == "postgresql+psycopg://api:s3cret@db:5432/enervision"


def test_le_mot_de_passe_reste_masque_a_l_affichage() -> None:
    settings = make_settings()
    assert "s3cret" not in repr(settings)
    assert "s3cret" not in str(settings.model_dump())
