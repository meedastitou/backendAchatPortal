"""
════════════════════════════════════════════════════════════
DATABASE - Connexion MySQL
════════════════════════════════════════════════════════════
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import mysql.connector
from mysql.connector import pooling

from app.config import settings


# ──────────────────────────────────────────────────────────
# SQLAlchemy Engine (pour ORM si besoin) - Lazy initialization
# ──────────────────────────────────────────────────────────

_engine = None
_SessionLocal = None


def get_engine():
    """Obtenir l'engine SQLAlchemy (création lazy)"""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=settings.DEBUG
        )
    return _engine


def get_session_local():
    """Obtenir la SessionLocal (création lazy)"""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal


# ──────────────────────────────────────────────────────────
# Connection Pool MySQL (pour requêtes directes)
# ──────────────────────────────────────────────────────────

db_config = {
    "host": settings.DB_HOST,
    "port": settings.DB_PORT,
    "database": settings.DB_NAME,
    "user": settings.DB_USER,
    "password": settings.DB_PASSWORD,
    "charset": "utf8mb4",
    "collation": "utf8mb4_unicode_ci"
}

# Pool de connexions (lazy initialization)
_connection_pool = None


def get_connection_pool():
    """Obtenir le pool de connexions (création lazy)"""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = pooling.MySQLConnectionPool(
            pool_name="flux_achat_pool",
            pool_size=5,
            pool_reset_session=False,  # Désactivé pour éviter les problèmes de transaction
            autocommit=False,
            **db_config
        )
    return _connection_pool


# ──────────────────────────────────────────────────────────
# Dependency Injection pour FastAPI
# ──────────────────────────────────────────────────────────

def get_db():
    """Dependency pour obtenir une session DB"""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_connection():
    """Obtenir une connexion du pool"""
    return get_connection_pool().get_connection()


@contextmanager
def get_cursor():
    """Context manager pour exécuter des requêtes"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


# ──────────────────────────────────────────────────────────
# Fonctions utilitaires
# ──────────────────────────────────────────────────────────

def execute_query(query: str, params: tuple = None, fetch_one: bool = False):
    """Exécuter une requête SELECT"""
    with get_cursor() as cursor:
        cursor.execute(query, params or ())
        if fetch_one:
            result = cursor.fetchone()
        else:
            result = cursor.fetchall()
        # S'assurer que le curseur est complètement consommé
        while cursor.nextset():
            pass
        return result


def execute_insert(query: str, params: tuple = None) -> int:
    """Exécuter une requête INSERT et retourner l'ID"""
    with get_cursor() as cursor:
        cursor.execute(query, params or ())
        return cursor.lastrowid


def execute_update(query: str, params: tuple = None) -> int:
    """Exécuter une requête UPDATE/DELETE et retourner le nombre de lignes affectées"""
    with get_cursor() as cursor:
        cursor.execute(query, params or ())
        return cursor.rowcount
