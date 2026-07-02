"""
════════════════════════════════════════════════════════════
SCHEMAS - Admin Gestion Lignes Cotation
════════════════════════════════════════════════════════════
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# ──────────────────────────────────────────────────────────
# Ligne Cotation Response
# ──────────────────────────────────────────────────────────

class LigneCotationAdmin(BaseModel):
    id: int
    rfq_uuid: str
    numero_rfq: str
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite_demandee: float
    unite: Optional[str] = None
    marque_souhaitee: Optional[str] = None
    created_at: datetime

    # Champs de désactivation
    actif: bool = True
    motif_desactivation: Optional[str] = None
    date_desactivation: Optional[datetime] = None
    desactive_par: Optional[str] = None

    # Infos fournisseur (jointure)
    code_fournisseur: Optional[str] = None
    nom_fournisseur: Optional[str] = None

    # Stats réponses
    nb_reponses: int = 0

    class Config:
        from_attributes = True


class LigneCotationListResponse(BaseModel):
    lignes: list[LigneCotationAdmin]
    total: int
    page: int
    limit: int


# ──────────────────────────────────────────────────────────
# Désactivation Request
# ──────────────────────────────────────────────────────────

class DesactiverLigneRequest(BaseModel):
    motif: str


class DesactiverLigneResponse(BaseModel):
    success: bool
    message: str
    ligne: LigneCotationAdmin


class ReactiverLigneResponse(BaseModel):
    success: bool
    message: str
    ligne: LigneCotationAdmin


# ──────────────────────────────────────────────────────────
# Stats Admin
# ──────────────────────────────────────────────────────────

class StatsLignesCotation(BaseModel):
    total_lignes: int
    lignes_actives: int
    lignes_desactivees: int
    total_das: int
    total_articles: int
