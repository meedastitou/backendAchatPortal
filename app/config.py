"""
════════════════════════════════════════════════════════════
CONFIGURATION - Variables d'environnement
════════════════════════════════════════════════════════════
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pathlib import Path


# Chemin vers le fichier .env (à la racine du backend)
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Configuration de l'application"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    # Application
    APP_NAME: str = "Flux Achat Portal API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # Base de données MySQL
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "flux_achat_portal"
    DB_USER: str = "root"
    DB_PASSWORD: str = ""

    # JWT Authentication
    SECRET_KEY: str = "jbel@JBEL@*ANNOUR2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 heures

    # CORS
    CORS_ORIGINS: list = ["http://localhost:4200", "http://localhost:3000"]

    # RPA API
    RPA_API_URL: str = "http://localhost:8001/api/bonne-commande/data"

    # SQL Server (Sage X3)
    X3_DB_HOST: str = "localhost"
    X3_DB_PORT: int = 1433
    X3_DB_NAME: str = "x3"
    X3_DB_USER: str = ""
    X3_DB_PASSWORD: str = ""
    X3_DB_DRIVER: str = "ODBC Driver 17 for SQL Server"

    @property
    def X3_CONNECTION_STRING(self) -> str:
        """Connection string ODBC pour SQL Server (Sage X3) - supporte les instances nommées"""
        # Format: SERVER=host\\instance ou SERVER=host,port
        server = self.X3_DB_HOST
        if '\\' not in server and self.X3_DB_PORT != 1433:
            server = f"{server},{self.X3_DB_PORT}"
        return (
            f"DRIVER={{{self.X3_DB_DRIVER}}};"
            f"SERVER={server};"
            f"DATABASE={self.X3_DB_NAME};"
            f"UID={self.X3_DB_USER};"
            f"PWD={self.X3_DB_PASSWORD};"
            f"TrustServerCertificate=yes;"
        )

    @property
    def DATABASE_URL(self) -> str:
        """URL de connexion à la base de données"""
        return f"mysql+mysqlconnector://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


@lru_cache()
def get_settings() -> Settings:
    """Récupérer les settings (avec cache)"""
    return Settings()


settings = get_settings()

# Export direct pour faciliter l'import
RPA_API_URL = settings.RPA_API_URL
