from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import make_url

# Ruta absoluta al .env del backend (independiente del working directory de PyCharm/uvicorn)
BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    """Configuracion de la aplicacion, cargada desde variables de entorno / .env."""

    database_url: str
    # En Docker Compose: host.docker.internal para llegar al Postgres del Mac
    database_host: str | None = None
    cors_origins: str = "http://localhost:4200"
    kucoin_api_key: str | None = None
    kucoin_secret: str | None = None
    kucoin_passphrase: str | None = None

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def resolved_database_url(self) -> str:
        """DATABASE_URL, con el host sustituido si existe DATABASE_HOST."""
        url = make_url(self.database_url)
        if self.database_host:
            url = url.set(host=self.database_host)
        return url.render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
