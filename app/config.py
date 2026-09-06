"""Central configuration.

Every value comes from the environment so that no secret ever lands in
source control. See .env.example for the full list.
"""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application -------------------------------------------------------
    app_name: str = "Voice Patient Registration"
    environment: str = "development"
    log_level: str = "INFO"

    # Public base URL of this service once deployed, e.g.
    # https://your-app.up.railway.app  — used only for documentation output.
    public_base_url: str = "http://localhost:8000"

    # --- Database ----------------------------------------------------------
    # Postgres in production, SQLite locally. Railway injects DATABASE_URL
    # automatically when you attach a Postgres plugin.
    database_url: str = "sqlite:///./data/patients.db"

    # --- Vapi webhook security --------------------------------------------
    # Set this to any long random string, then paste the same string into the
    # Vapi assistant's server "secret" field. Requests whose
    # x-vapi-secret header does not match are rejected with 401.
    vapi_secret: str = ""

    # Optional: only needed if you run scripts/provision_vapi.py to create the
    # assistant programmatically instead of clicking through the dashboard.
    vapi_api_key: str = ""
    vapi_public_key: str = ""
    vapi_phone_number_id: str = ""
    vapi_assistant_id: str = ""

    # --- Dashboard login ---------------------------------------------------
    dashboard_username: str = ""
    dashboard_password: str = ""
    dashboard_session_secret: str = ""

    @property
    def normalized_database_url(self) -> str:
        """Railway hands out postgres:// which SQLAlchemy 2.x no longer accepts."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    @property
    def is_sqlite(self) -> bool:
        return self.normalized_database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Make sure the SQLite folder exists before the engine tries to open the file.
if settings.is_sqlite:
    path = settings.normalized_database_url.split("///")[-1]
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
