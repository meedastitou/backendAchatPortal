"""
════════════════════════════════════════════════════════════
SCHEMAS - Réponses Fournisseurs
════════════════════════════════════════════════════════════
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ──────────────────────────────────────────────────────────
# Entête Réponse
# ──────────────────────────────────────────────────────────

class ReponseEnteteBase(BaseModel):
    reference_fournisseur: Optional[str] = None
    fichier_devis_url: Optional[str] = None
    devise: str = "MAD"
    methodes_paiement: Optional[str] = None
    commentaire: Optional[str] = None


class ReponseEnteteResponse(ReponseEnteteBase):
    id: int
    rfq_uuid: str
    date_reponse: datetime
    created_at: datetime

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────────────────
# Détail Réponse (par article)
# ──────────────────────────────────────────────────────────

class ReponseDetailBase(BaseModel):
    code_article: str
    prix_unitaire_ht: Optional[float] = None
    date_livraison: Optional[datetime] = None
    quantite_disponible: Optional[float] = None
    marque_conforme: Optional[bool] = True
    marque_proposee: Optional[str] = None
    fichier_joint_url: Optional[str] = None
    commentaire_article: Optional[str] = None


class ReponseDetailResponse(ReponseDetailBase):
    id: int
    reponse_entete_id: int
    rfq_uuid: str
    ligne_cotation_id: int
    # Champs depuis lignes_cotation
    designation_article: Optional[str] = None
    marque_demandee: Optional[str] = None
    numero_da: Optional[str] = None
    # Champ depuis articles_ref (prix maximum d'achat)
    tarif_reference: Optional[float] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────────────────
# Réponse Complète
# ──────────────────────────────────────────────────────────

class ReponseComplete(BaseModel):
    """Réponse complète avec entête et détails"""
    entete: ReponseEnteteResponse
    details: List[ReponseDetailResponse]

    # Infos RFQ
    numero_rfq: str
    code_fournisseur: str
    nom_fournisseur: str


class ReponseListResponse(BaseModel):
    reponses: List[ReponseComplete]
    total: int
    page: int
    limit: int


# ──────────────────────────────────────────────────────────
# Comparaison
# ──────────────────────────────────────────────────────────

class ComparaisonArticle(BaseModel):
    """Comparaison des offres pour un article"""
    code_article: str
    designation: Optional[str] = None
    quantite_demandee: float

    # Offres reçues
    offres: List[dict]  # Liste des offres par fournisseur

    # Analyse
    nb_offres: int
    prix_min: Optional[float] = None
    prix_max: Optional[float] = None
    prix_moyen: Optional[float] = None
    meilleur_fournisseur_prix: Optional[str] = None
    meilleur_fournisseur_delai: Optional[str] = None
    fournisseur_recommande: Optional[str] = None


class ComparaisonResponse(BaseModel):
    """Comparaison complète pour une DA"""
    numero_da: str
    articles: List[ComparaisonArticle]
    nb_fournisseurs_sollicites: int
    nb_reponses_recues: int
    date_analyse: datetime


# ──────────────────────────────────────────────────────────
# Rejet
# ──────────────────────────────────────────────────────────

class RejetResponse(BaseModel):
    id: int
    rfq_uuid: str
    motif_rejet: Optional[str] = None
    type_rejet: str
    date_rejet: datetime

    # Infos fournisseur
    code_fournisseur: str
    nom_fournisseur: str

    class Config:
        from_attributes = True
