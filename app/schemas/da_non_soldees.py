# ──────────────────────────────────────────────────────────
# DA Non Soldées (Sage X3)
# ──────────────────────────────────────────────────────────

from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from enum import Enum


class Priorite(str, Enum):
    basse = "basse"
    normale = "normale"
    haute = "haute"
    urgente = "urgente"

class StatutDA(str, Enum):
    nouveau = "nouveau"
    en_cours = "en_cours"
    cotations_recues = "cotations_recues"
    commande_creee = "commande_creee"
    annule = "annule"

class DANonSoldeeResponse(BaseModel):
    DA: str
    Article: str
    DésignationArticle: Optional[str] = None
    QteDA: Optional[float] = None
    marque: Optional[str] = None
    Unite: Optional[str] = None
    Famille: Optional[str] = None

    class Config:
        from_attributes = True

class DATransfertRequest(BaseModel):
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite: float
    unite: Optional[str] = None
    marque_souhaitee: Optional[str] = None
    priorite: Priorite = Priorite.normale

# ──────────────────────────────────────────────────────────
# Demande d'Achat (DA)
# ──────────────────────────────────────────────────────────

class DemandeAchatBase(BaseModel):
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite: float
    unite: Optional[str] = None
    marque_souhaitee: Optional[str] = None
    date_besoin: Optional[datetime] = None
    priorite: Priorite = Priorite.normale


class DemandeAchatResponse(DemandeAchatBase):
    id: int
    date_creation_da: datetime
    statut: StatutDA
    created_at: datetime

    class Config:
        from_attributes = True


