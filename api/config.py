import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    database_url_async: str = "postgresql+asyncpg://pjud:pjud@localhost:5432/pjud"
    database_url_sync: str = "postgresql+psycopg://pjud:pjud@localhost:5432/pjud"

    public_base_url: str = "https://api-pjud.temposoft.cl"
    documentos_dir: str = str(BASE_DIR / "documentos")
    log_dir: str = str(BASE_DIR / "logs")

    sync_lock_timeout_minutes: int = 15
    sync_min_interval_minutes: int = 30

    playwright_headless: bool = False


settings = Settings()

os.makedirs(settings.documentos_dir, exist_ok=True)
os.makedirs(settings.log_dir, exist_ok=True)
