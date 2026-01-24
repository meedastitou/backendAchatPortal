"""
════════════════════════════════════════════════════════════
SCHEMAS - Bon de Commande (Multi-DA par Fournisseur)
════════════════════════════════════════════════════════════
Un BC peut contenir des lignes de plusieurs DA
Un BC est toujours pour UN seul fournisseur
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum


class StatutBonCommande(str, Enum):
    BROUILLON = "brouillon"
    VALIDE = "valide"
    ENVOYE = "envoye"
    LIVRE = "livre"
    ANNULE = "annule"


# ──────────────────────────────────────────────────────────
# Fournisseurs disponibles pour BC
# ──────────────────────────────────────────────────────────

class DADisponible(BaseModel):
    """DA disponible pour un fournisseur"""
    numero_da: str
    numero_rfq: str
    reponse_id: int
    date_reponse: Optional[datetime] = None
    nb_lignes: int
    montant_total_ht: float


class FournisseurDisponibleBC(BaseModel):
    """Fournisseur ayant des réponses disponibles pour BC"""
    code_fournisseur: str
    nom_fournisseur: str
    email: Optional[str] = None
    telephone: Optional[str] = None

    # Statistiques
    nb_da_disponibles: int
    nb_lignes_total: int
    montant_total_ht: float

    # Liste des DA
    das_disponibles: List[DADisponible] = []


class FournisseursDisponiblesResponse(BaseModel):
    """Liste des fournisseurs disponibles pour BC"""
    fournisseurs: List[FournisseurDisponibleBC]
    total: int


# ──────────────────────────────────────────────────────────
# Lignes disponibles d'un fournisseur (toutes DA confondues)
# ──────────────────────────────────────────────────────────

class LigneDisponibleBC(BaseModel):
    """Ligne disponible pour inclusion dans un BC"""
    # Identifiants
    ligne_id: int  # ID de la ligne réponse détail
    reponse_id: int

    # Infos DA/RFQ
    numero_da: str
    numero_rfq: str

    # Article
    code_article: str
    designation: Optional[str] = None

    # Quantités
    quantite_demandee: float
    quantite_disponible: float  # Proposée par le fournisseur
    unite: Optional[str] = None

    # Prix
    prix_unitaire_ht: float
    montant_ligne_ht: float
    tva_pourcent: float = 20.0
    montant_ligne_ttc: float

    # Délai
    delai_livraison_jours: Optional[int] = None
    date_livraison_prevue: Optional[datetime] = None

    # Marque
    marque_proposee: Optional[str] = None

    # Pour validation prix
    prix_historique_moyen: Optional[float] = None
    ecart_prix_pourcent: Optional[float] = None

    # Sélection par défaut
    selectionne: bool = True


class LignesDisponiblesResponse(BaseModel):
    """Toutes les lignes disponibles d'un fournisseur"""
    code_fournisseur: str
    nom_fournisseur: str
    email_fournisseur: Optional[str] = None

    # Lignes groupées par DA
    lignes: List[LigneDisponibleBC]

    # Totaux (si tout sélectionné)
    montant_total_ht: float
    montant_tva: float
    montant_total_ttc: float

    nb_lignes: int
    nb_da: int


# ──────────────────────────────────────────────────────────
# Préparation du BC (avec sélection)
# ──────────────────────────────────────────────────────────

class LigneBCPreparation(BaseModel):
    """Ligne sélectionnée pour le BC (éditable)"""
    ligne_id: int  # Référence à la ligne source
    reponse_id: int
    numero_da: str
    numero_rfq: str

    code_article: str
    designation: Optional[str] = None

    # Quantités (modifiables)
    quantite_demandee: float
    quantite_commandee: float  # Peut être inférieure à quantite_disponible
    unite: Optional[str] = None

    # Prix (modifiables)
    prix_unitaire_ht: float
    montant_ligne_ht: float
    tva_pourcent: float = 20.0
    montant_ligne_ttc: float

    # Délai (modifiable)
    date_livraison_prevue: Optional[datetime] = None

    marque_proposee: Optional[str] = None
    commentaire_ligne: Optional[str] = None


class BCPreparation(BaseModel):
    """BC en préparation (à vérifier/modifier avant génération)"""
    # Fournisseur
    code_fournisseur: str
    nom_fournisseur: str
    email_fournisseur: Optional[str] = None

    # Devise
    devise: str = "MAD"

    # Lignes sélectionnées (éditables)
    lignes: List[LigneBCPreparation]

    # Totaux calculés
    montant_total_ht: float
    montant_tva: float
    montant_total_ttc: float

    # Résumé des DA incluses
    das_incluses: List[str]  # Liste des numéros de DA
    nb_lignes: int

    # Champs éditables
    conditions_paiement: Optional[str] = None
    lieu_livraison: Optional[str] = None
    commentaire_bc: Optional[str] = None

    # Validation
    date_preparation: datetime


# ──────────────────────────────────────────────────────────
# Génération du BC
# ──────────────────────────────────────────────────────────

class LigneBCCreate(BaseModel):
    """Ligne pour création de BC"""
    ligne_id: int  # ID de la ligne source (reponse_detail)
    reponse_id: int

    code_article: str
    designation: Optional[str] = None
    quantite: float
    prix_unitaire_ht: float
    tva_pourcent: float = 20.0
    date_livraison_prevue: Optional[datetime] = None
    commentaire: Optional[str] = None


class GenerateBCRequest(BaseModel):
    """Requête pour générer un bon de commande"""
    code_fournisseur: str
    lignes: List[LigneBCCreate]

    # Champs optionnels
    conditions_paiement: Optional[str] = None
    lieu_livraison: Optional[str] = None
    commentaire: Optional[str] = None


class GenerateBCResponse(BaseModel):
    """Réponse après génération du BC"""
    success: bool
    numero_bc: Optional[str] = None
    message: str

    montant_total_ht: Optional[float] = None
    montant_total_ttc: Optional[float] = None

    # Détails
    code_fournisseur: Optional[str] = None
    nom_fournisseur: Optional[str] = None
    nb_lignes: Optional[int] = None
    das_incluses: Optional[List[str]] = None


# ──────────────────────────────────────────────────────────
# Bon de Commande (lecture)
# ──────────────────────────────────────────────────────────

class LigneBCResponse(BaseModel):
    """Ligne de BC en lecture"""
    id: int
    numero_bc: str

    # Traçabilité source
    ligne_source_id: Optional[int] = None
    reponse_id: Optional[int] = None
    numero_da: Optional[str] = None
    numero_rfq: Optional[str] = None

    # Article
    code_article: str
    designation: Optional[str] = None
    quantite: float
    unite: Optional[str] = None

    # Prix
    prix_unitaire_ht: float
    montant_ligne_ht: float
    tva_pourcent: float
    montant_ligne_ttc: float

    date_livraison_prevue: Optional[datetime] = None
    commentaire: Optional[str] = None

    class Config:
        from_attributes = True


class BonCommandeResponse(BaseModel):
    """Bon de commande complet"""
    id: int
    numero_bc: str

    # Fournisseur
    code_fournisseur: str
    nom_fournisseur: str

    # Dates
    date_creation: datetime
    date_validation: Optional[datetime] = None
    validee_par: Optional[str] = None

    # Montants
    montant_total_ht: float
    montant_tva: float
    montant_total_ttc: float
    devise: str

    # Statut
    statut: StatutBonCommande

    # Conditions
    conditions_paiement: Optional[str] = None
    lieu_livraison: Optional[str] = None
    commentaire: Optional[str] = None

    # Lignes
    lignes: List[LigneBCResponse] = []

    # Résumé
    das_incluses: List[str] = []
    nb_lignes: int = 0

    class Config:
        from_attributes = True


class BCListResponse(BaseModel):
    """Liste des bons de commande"""
    bons_commande: List[BonCommandeResponse]
    total: int
    page: int
    limit: int


# ──────────────────────────────────────────────────────────
# Conversion Offre vers BC (pour RPA Sage X3)
# ──────────────────────────────────────────────────────────

class ArticleRPABC(BaseModel):
    """Article sélectionné pour conversion vers BC via RPA"""
    ligne_detail_id: int  # ID dans reponses_fournisseurs_detail
    code_article: str
    designation: Optional[str] = None
    quantite: float  # Peut être modifié
    unite: Optional[str] = None
    prix_unitaire_ht: float  # Peut être modifié
    tva_pourcent: float = 20.0
    date_livraison: Optional[str] = None  # Peut être modifié (format YYYY-MM-DD)
    marque: Optional[str] = None
    commentaire: Optional[str] = None


class ConvertOffreToRPARequest(BaseModel):
    """Requête pour convertir une offre fournisseur en BC via RPA"""
    reponse_id: int  # ID de reponses_fournisseurs_entete

    # Articles sélectionnés (avec modifications)
    articles: List[ArticleRPABC]

    # Infos BC
    conditions_paiement: Optional[str] = None
    lieu_livraison: Optional[str] = None
    commentaire_bc: Optional[str] = None


class ConvertOffreToRPAResponse(BaseModel):
    """Réponse après envoi vers RPA"""
    success: bool
    message: str

    # Identifiant pour suivi
    rpa_request_id: Optional[str] = None

    # Résumé
    code_fournisseur: Optional[str] = None
    nom_fournisseur: Optional[str] = None
    nb_articles: Optional[int] = None
    montant_total_ht: Optional[float] = None

    # Données envoyées au RPA (pour debug/traçabilité)
    payload_rpa: Optional[dict] = None
