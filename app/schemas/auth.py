"""
════════════════════════════════════════════════════════════
SCHEMAS - Authentification
════════════════════════════════════════════════════════════
"""

from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from enum import Enum


class RoleEnum(str, Enum):
    acheteur = "acheteur"
    responsable_achat = "responsable_achat"
    admin = "admin"


# ──────────────────────────────────────────────────────────
# Token
# ──────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None
    role: Optional[str] = None


# ──────────────────────────────────────────────────────────
# Utilisateur
# ──────────────────────────────────────────────────────────

class UserBase(BaseModel):
    username: str
    email: EmailStr
    nom: Optional[str] = None
    prenom: Optional[str] = None
    role: RoleEnum = RoleEnum.acheteur


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    nom: Optional[str] = None
    prenom: Optional[str] = None
    role: Optional[RoleEnum] = None
    actif: Optional[bool] = None


class UserResponse(UserBase):
    id: int
    actif: bool
    derniere_connexion: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────────────────
# Login
# ──────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
