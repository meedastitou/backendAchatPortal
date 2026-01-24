"""
════════════════════════════════════════════════════════════
SCHEMAS - Demandes de Cotation (RFQ)
════════════════════════════════════════════════════════════
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum


class StatutRFQ(str, Enum):
    envoye = "envoye"
    vu = "vu"
    repondu = "repondu"
    rejete = "rejete"
    expire = "expire"
    relance_1 = "relance_1"
    relance_2 = "relance_2"
    relance_3 = "relance_3"


class StatutDA(str, Enum):
    nouveau = "nouveau"
    en_cours = "en_cours"
    cotations_recues = "cotations_recues"
    commande_creee = "commande_creee"
    annule = "annule"


class Priorite(str, Enum):
    basse = "basse"
    normale = "normale"
    haute = "haute"
    urgente = "urgente"


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


# ──────────────────────────────────────────────────────────
# Ligne de Cotation
# ──────────────────────────────────────────────────────────

class LigneCotationBase(BaseModel):
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite_demandee: float
    unite: Optional[str] = None
    marque_souhaitee: Optional[str] = None


class LigneCotationResponse(LigneCotationBase):
    id: int
    rfq_uuid: str
    created_at: datetime

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────────────────
# Demande de Cotation (RFQ)
# ──────────────────────────────────────────────────────────

class RFQBase(BaseModel):
    code_fournisseur: str
    date_limite_reponse: Optional[datetime] = None


class RFQResponse(BaseModel):
    id: int
    uuid: str
    numero_rfq: str
    code_fournisseur: str
    nom_fournisseur: Optional[str] = None
    email_fournisseur: Optional[str] = None
    date_envoi: datetime
    date_limite_reponse: Optional[datetime] = None
    statut: StatutRFQ
    nb_relances: int
    date_derniere_relance: Optional[datetime] = None
    date_ouverture_email: Optional[datetime] = None
    date_clic_formulaire: Optional[datetime] = None
    date_reponse: Optional[datetime] = None
    lignes: List[LigneCotationResponse] = []
    created_at: datetime

    class Config:
        from_attributes = True


class RFQDetailResponse(RFQResponse):
    """RFQ avec tous les détails"""
    jours_depuis_envoi: int = 0
    delai_reponse_heures: Optional[int] = None
    nb_articles: int = 0


class RFQListResponse(BaseModel):
    rfqs: List[RFQResponse]
    total: int
    page: int
    limit: int


# ──────────────────────────────────────────────────────────
# Filtres
# ──────────────────────────────────────────────────────────

class RFQFilters(BaseModel):
    statut: Optional[StatutRFQ] = None
    code_fournisseur: Optional[str] = None
    date_debut: Optional[datetime] = None
    date_fin: Optional[datetime] = None
    search: Optional[str] = None
    page: int = 1
    limit: int = 20
