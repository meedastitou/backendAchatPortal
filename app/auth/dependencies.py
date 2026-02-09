"""
════════════════════════════════════════════════════════════
AUTHENTIFICATION - Dependencies FastAPI
════════════════════════════════════════════════════════════
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from typing import Optional

from app.auth.jwt import decode_access_token, verify_password
from app.database import execute_query
from app.schemas.auth import TokenData, UserResponse


# ──────────────────────────────────────────────────────────
# OAuth2 Scheme
# ──────────────────────────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ──────────────────────────────────────────────────────────
# User Services
# ──────────────────────────────────────────────────────────

def get_user_by_username(username: str) -> Optional[dict]:
    """Récupérer un utilisateur par son username"""
    query = """
        SELECT id, username, email, password_hash, nom, prenom, role, actif,
               derniere_connexion, created_at, updated_at
        FROM utilisateurs
        WHERE username = %s
    """
    return execute_query(query, (username,), fetch_one=True)


def get_user_by_id(user_id: int) -> Optional[dict]:
    """Récupérer un utilisateur par son ID"""
    query = """
        SELECT id, username, email, password_hash, nom, prenom, role, actif,
               derniere_connexion, created_at, updated_at
        FROM utilisateurs
        WHERE id = %s
    """
    return execute_query(query, (user_id,), fetch_one=True)


def get_user_familles(user_id: int) -> list[str]:
    """Récupérer les codes familles assignées à un utilisateur"""
    query = """
        SELECT code_famille
        FROM utilisateur_familles
        WHERE utilisateur_id = %s
    """
    rows = execute_query(query, (user_id,))
    return [row["code_famille"] for row in rows] if rows else []


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """
    Authentifier un utilisateur

    Args:
        username: Nom d'utilisateur
        password: Mot de passe en clair

    Returns:
        Utilisateur si authentifié, None sinon
    """
    user = get_user_by_username(username)

    if not user:
        return None

    if not user["actif"]:
        return None

    if not verify_password(password, user["password_hash"]):
        return None

    return user


def update_last_login(user_id: int):
    """Mettre à jour la date de dernière connexion"""
    from app.database import execute_update
    query = "UPDATE utilisateurs SET derniere_connexion = NOW() WHERE id = %s"
    execute_update(query, (user_id,))


# ──────────────────────────────────────────────────────────
# Dependencies
# ──────────────────────────────────────────────────────────

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    Dependency pour obtenir l'utilisateur courant à partir du token

    Raises:
        HTTPException 401 si token invalide
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = decode_access_token(token)
    if token_data is None:
        raise credentials_exception

    user = get_user_by_username(token_data.username)
    if user is None:
        raise credentials_exception

    if not user["actif"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé"
        )

    # Ajouter les familles de l'utilisateur
    user["familles"] = get_user_familles(user["id"])

    return user


async def get_current_active_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency pour obtenir un utilisateur actif"""
    if not current_user["actif"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé"
        )
    return current_user


# ──────────────────────────────────────────────────────────
# Role-based Access Control
# ──────────────────────────────────────────────────────────

def require_role(*allowed_roles):
    """
    Dependency factory pour vérifier le rôle

    Usage:
        @router.get("/admin", dependencies=[Depends(require_role("admin"))])
    """
    async def role_checker(current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permissions insuffisantes"
            )
        return current_user

    return role_checker


async def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency pour admin uniquement"""
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux administrateurs"
        )
    return current_user


async def get_responsable_or_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency pour responsable achat ou admin"""
    if current_user["role"] not in ["admin", "responsable_achat"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux responsables achats"
        )
    return current_user


# ──────────────────────────────────────────────────────────
# Filtrage par famille
# ──────────────────────────────────────────────────────────

def get_user_famille_filter(current_user: dict) -> Optional[list[str]]:
    """
    Retourne la liste des familles à filtrer pour l'utilisateur.

    - admin/responsable_achat: None (voit tout)
    - acheteur: liste de ses familles assignées

    Returns:
        None si l'utilisateur voit tout, sinon liste de codes familles
    """
    if current_user["role"] in ["admin", "responsable_achat"]:
        return None  # Voit tout

    return current_user.get("familles", [])
