"""
════════════════════════════════════════════════════════════
CONFIGURATION - Variables d'environnement
════════════════════════════════════════════════════════════
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Configuration de l'application"""

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
    SECRET_KEY: str = "votre-cle-secrete-a-changer-en-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 heures

    # CORS
    CORS_ORIGINS: list = ["http://localhost:4200", "http://localhost:3000"]

    @property
    def DATABASE_URL(self) -> str:
        """URL de connexion à la base de données"""
        return f"mysql+mysqlconnector://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Récupérer les settings (avec cache)"""
    return Settings()


settings = get_settings()
