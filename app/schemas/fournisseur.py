"""
════════════════════════════════════════════════════════════
SCHEMAS - Fournisseurs
════════════════════════════════════════════════════════════
"""

from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum


class StatutFournisseur(str, Enum):
    actif = "actif"
    inactif = "inactif"
    suspendu = "suspendu"


# ──────────────────────────────────────────────────────────
# Fournisseur
# ──────────────────────────────────────────────────────────

class FournisseurBase(BaseModel):
    code_fournisseur: str
    nom_fournisseur: str
    email: Optional[EmailStr] = None
    telephone: Optional[str] = None
    fax: Optional[str] = None
    adresse: Optional[str] = None
    pays: Optional[str] = "Maroc"
    ville: Optional[str] = None


class FournisseurCreate(FournisseurBase):
    pass


class FournisseurUpdate(BaseModel):
    nom_fournisseur: Optional[str] = None
    email: Optional[EmailStr] = None
    telephone: Optional[str] = None
    fax: Optional[str] = None
    adresse: Optional[str] = None
    pays: Optional[str] = None
    ville: Optional[str] = None
    statut: Optional[StatutFournisseur] = None


class FournisseurResponse(FournisseurBase):
    id: int
    statut: StatutFournisseur
    blacklist: bool
    motif_blacklist: Optional[str] = None
    date_blacklist: Optional[datetime] = None
    note_performance: float
    nb_total_rfq: int
    nb_reponses: int
    taux_reponse: float
    delai_moyen_reponse_heures: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FournisseurListResponse(BaseModel):
    fournisseurs: List[FournisseurResponse]
    total: int
    page: int
    limit: int


# ──────────────────────────────────────────────────────────
# Blacklist
# ──────────────────────────────────────────────────────────

class BlacklistRequest(BaseModel):
    motif: str


class BlacklistResponse(BaseModel):
    success: bool
    message: str
    fournisseur: FournisseurResponse


# ──────────────────────────────────────────────────────────
# Performance Fournisseur
# ──────────────────────────────────────────────────────────

class FournisseurPerformance(BaseModel):
    code_fournisseur: str
    nom_fournisseur: str
    nb_rfq_total: int
    nb_reponses: int
    nb_rejets: int
    taux_reponse: float
    delai_moyen_reponse: float
    note_prix: float
    note_delai: float
    note_globale: float
    historique_prix: List[dict]


# ──────────────────────────────────────────────────────────
# Filtres
# ──────────────────────────────────────────────────────────

class FournisseurFilters(BaseModel):
    statut: Optional[StatutFournisseur] = None
    blacklist: Optional[bool] = None
    search: Optional[str] = None
    min_taux_reponse: Optional[float] = None
    page: int = 1
    limit: int = 20
