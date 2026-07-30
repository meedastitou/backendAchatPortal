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
    manuel: bool
    created_by: Optional[str] = None
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


# ──────────────────────────────────────────────────────────
# Création manuelle de RFQ
# ──────────────────────────────────────────────────────────

class FournisseurSelectionResponse(BaseModel):
    """Fournisseur pour sélection dans création RFQ"""
    code_fournisseur: str
    nom_fournisseur: str
    email: Optional[str] = None
    blacklist: bool = False

    class Config:
        from_attributes = True


class FournisseurSearchResponse(BaseModel):
    fournisseurs: List[FournisseurSelectionResponse]
    total: int


class DADisponibleResponse(BaseModel):
    """DA disponible pour création RFQ"""
    numero_da: str
    nb_articles: int


class DAListResponse(BaseModel):
    da_list: List[DADisponibleResponse]
    total: int


class ArticleDAResponse(BaseModel):
    """Article d'une DA pour création RFQ"""
    id: int
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite: float
    unite: Optional[str] = None
    marque_souhaitee: Optional[str] = None

    class Config:
        from_attributes = True


class ArticlesDAListResponse(BaseModel):
    numero_da: str
    articles: List[ArticleDAResponse]
    total: int


class ArticleSelectionCreate(BaseModel):
    """Article sélectionné pour création RFQ"""
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite: float
    unite: Optional[str] = None
    marque_souhaitee: Optional[str] = None


class CreerRFQManuelRequest(BaseModel):
    """Requête de création manuelle de RFQ"""
    fournisseurs: List[str]  # codes fournisseurs
    articles: List[ArticleSelectionCreate]
    date_limite_reponse: Optional[datetime] = None


class RFQCreatedResponse(BaseModel):
    """Réponse après création d'une RFQ"""
    uuid: str
    numero_rfq: str
    code_fournisseur: str
    nom_fournisseur: Optional[str] = None
    email: Optional[str] = None
    nb_articles: int
    email_envoye: bool = False
    email_error: Optional[str] = None


class CreerRFQManuelResponse(BaseModel):
    """Réponse de création manuelle de RFQ"""
    success: bool
    message: str
    rfqs_crees: List[RFQCreatedResponse]
    nb_rfqs: int
    nb_emails_envoyes: int
