"""
════════════════════════════════════════════════════════════
DATABASE - Connexion SQL Server (Sage X3)
════════════════════════════════════════════════════════════
"""

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
from urllib.parse import quote_plus

from app.config import settings


# ──────────────────────────────────────────────────────────
# SQLAlchemy Engine pour SQL Server - Lazy initialization
# ──────────────────────────────────────────────────────────

_x3_engine = None
_X3SessionLocal = None


def get_x3_engine():
    """Obtenir l'engine SQLAlchemy pour SQL Server (création lazy)"""
    global _x3_engine
    if _x3_engine is None:
        # Utiliser la connection string ODBC encodée pour supporter les instances nommées
        connection_string = settings.X3_CONNECTION_STRING
        connection_url = f"mssql+pyodbc:///?odbc_connect={quote_plus(connection_string)}"

        _x3_engine = create_engine(
            connection_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=settings.DEBUG
        )
    return _x3_engine


def get_x3_session_local():
    """Obtenir la SessionLocal pour SQL Server (création lazy)"""
    global _X3SessionLocal
    if _X3SessionLocal is None:
        _X3SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_x3_engine())
    return _X3SessionLocal


# ──────────────────────────────────────────────────────────
# Dependency Injection pour FastAPI
# ──────────────────────────────────────────────────────────

def get_x3_db():
    """Dependency pour obtenir une session DB SQL Server"""
    SessionLocal = get_x3_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_x3_session():
    """Context manager pour sessions SQL Server"""
    SessionLocal = get_x3_session_local()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


# ──────────────────────────────────────────────────────────
# Fonctions utilitaires
# ──────────────────────────────────────────────────────────

def execute_x3_query(query: str, params: dict = None, fetch_one: bool = False) -> Optional[List[Dict[str, Any]]]:
    """Exécuter une requête SELECT sur SQL Server"""
    with get_x3_session() as session:
        result = session.execute(text(query), params or {})
        rows = result.mappings().all()
        if fetch_one:
            return dict(rows[0]) if rows else None
        return [dict(row) for row in rows]
