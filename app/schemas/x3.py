"""
════════════════════════════════════════════════════════════
SCHEMAS - Sage X3 (Réceptions)
════════════════════════════════════════════════════════════
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import date
from decimal import Decimal


# ──────────────────────────────────────────────────────────
# Dernière Réception Article
# ──────────────────────────────────────────────────────────

class DerniereReceptionResponse(BaseModel):
    """Réponse pour la dernière réception d'un article"""
    code_article: str
    designation: str
    code_fournisseur: str
    nom_fournisseur: Optional[str] = None
    prix: Decimal
    devise: str
    date_reception: date

    class Config:
        from_attributes = True


class DerniereReceptionListResponse(BaseModel):
    """Liste des dernières réceptions"""
    receptions: List[DerniereReceptionResponse]
    total: int
