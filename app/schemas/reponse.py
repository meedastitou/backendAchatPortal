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
    quantite_demandee: Optional[float] = None
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


# ──────────────────────────────────────────────────────────
# Saisie Manuelle de Reponse (Tables _acheteur)
# ──────────────────────────────────────────────────────────

class LigneReponseAcheteur(BaseModel):
    """Ligne de reponse saisie par l'acheteur - avec info fournisseur par ligne"""
    code_article: str

    # Fournisseur pour CETTE ligne
    code_fournisseur: Optional[str] = None
    nom_fournisseur: str
    email_fournisseur: str
    telephone_fournisseur: Optional[str] = None

    # Infos cotation
    prix_unitaire_ht: Optional[float] = None
    quantite_disponible: Optional[float] = None
    delai_livraison_jours: Optional[int] = None
    date_livraison_prevue: Optional[datetime] = None

    # Marque
    marque_conforme: Optional[bool] = True
    marque_proposee: Optional[str] = None

    # Reference fournisseur
    reference_fournisseur: Optional[str] = None

    # Commentaire
    commentaire_ligne: Optional[str] = None


class ReponseAcheteurRequest(BaseModel):
    """Requete pour saisir une reponse acheteur"""
    # DA source
    numero_da: str

    # Infos globales
    devise: str = "MAD"
    conditions_paiement: Optional[str] = None
    commentaire_global: Optional[str] = None

    # Lignes avec fournisseur par ligne
    lignes: List[LigneReponseAcheteur]


class ReponseAcheteurResponse(BaseModel):
    """Reponse apres saisie acheteur"""
    success: bool
    message: str
    numero_rfq: Optional[str] = None
    uuid_reponse: Optional[str] = None
    nb_lignes: int = 0


# ──────────────────────────────────────────────────────────
# Lecture des reponses acheteur
# ──────────────────────────────────────────────────────────

class LigneReponseAcheteurDetail(BaseModel):
    """Detail d'une ligne de reponse acheteur"""
    id: int
    code_article: str
    designation_article: Optional[str] = None
    quantite_demandee: Optional[float] = None

    # Fournisseur
    code_fournisseur: Optional[str] = None
    nom_fournisseur: str
    email_fournisseur: str

    # Cotation
    prix_unitaire_ht: Optional[float] = None
    quantite_disponible: Optional[float] = None
    delai_livraison_jours: Optional[int] = None
    marque_proposee: Optional[str] = None
    statut_ligne: str

    class Config:
        from_attributes = True


class ReponseAcheteurComplete(BaseModel):
    """Reponse acheteur complete"""
    id: int
    uuid_reponse: str
    rfq_uuid: str
    numero_rfq: str
    numero_da: str
    devise: str
    conditions_paiement: Optional[str] = None
    date_soumission: datetime
    commentaire_global: Optional[str] = None
    saisi_par_email: Optional[str] = None

    lignes: List[LigneReponseAcheteurDetail]

    class Config:
        from_attributes = True


class ReponseAcheteurListResponse(BaseModel):
    """Liste des reponses acheteur"""
    reponses: List[ReponseAcheteurComplete]
    total: int
    page: int
    limit: int
