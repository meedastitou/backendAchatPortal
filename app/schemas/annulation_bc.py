"""
════════════════════════════════════════════════════════════
SCHEMAS - Annulation Bon de Commande
════════════════════════════════════════════════════════════
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum


class StatutAnnulation(str, Enum):
    EN_ATTENTE = "en_attente"
    EN_COURS = "en_cours"
    VALIDEE = "validee"
    REFUSEE = "refusee"


# ──────────────────────────────────────────────────────────
# Request Models
# ──────────────────────────────────────────────────────────

class AnnulationBCCreate(BaseModel):
    numero_commande: str
    motif_annulation: str


# ──────────────────────────────────────────────────────────
# Response Models
# ──────────────────────────────────────────────────────────

class AnnulationBC(BaseModel):
    id: int
    numero_commande: str
    motif_annulation: str
    demande_par: str
    statut: StatutAnnulation = StatutAnnulation.EN_ATTENTE
    numero_abc: Optional[str] = None
    code_tier: Optional[str] = None
    email_fournisseur: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AnnulationBCResponse(BaseModel):
    success: bool
    message: str
    annulation: AnnulationBC


class AnnulationBCListResponse(BaseModel):
    annulations: list[AnnulationBC]
    total: int
    page: int
    limit: int
