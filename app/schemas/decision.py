"""
════════════════════════════════════════════════════════════
SCHEMAS - Décision Achat (DA avec réponses sans commande)
════════════════════════════════════════════════════════════
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ──────────────────────────────────────────────────────────
# Offre Fournisseur pour comparaison
# ──────────────────────────────────────────────────────────

class OffreFournisseur(BaseModel):
    """Offre d'un fournisseur pour un article"""
    code_fournisseur: str
    nom_fournisseur: str
    numero_rfq: str
    prix_unitaire_ht: Optional[float] = None
    quantite_disponible: Optional[float] = None
    date_livraison: Optional[datetime] = None
    delai_jours: Optional[int] = None
    marque_conforme: Optional[bool] = None
    marque_proposee: Optional[str] = None
    devise: str = "MAD"
    commentaire: Optional[str] = None
    date_reponse: datetime
    # Scores calculés
    score_prix: Optional[float] = None  # 0-100, plus haut = meilleur
    score_delai: Optional[float] = None  # 0-100, plus haut = meilleur
    score_global: Optional[float] = None  # 0-100, combiné


# ──────────────────────────────────────────────────────────
# Article en comparaison
# ──────────────────────────────────────────────────────────

class ArticleComparaison(BaseModel):
    """Article avec toutes les offres reçues"""
    code_article: str
    designation: Optional[str] = None
    quantite_demandee: float
    unite: Optional[str] = None
    marque_souhaitee: Optional[str] = None

    # Offres reçues
    offres: List[OffreFournisseur] = []
    nb_offres: int = 0

    # Analyse
    prix_min: Optional[float] = None
    prix_max: Optional[float] = None
    prix_moyen: Optional[float] = None
    ecart_prix_pourcent: Optional[float] = None  # Écart entre min et max

    # Recommandations
    meilleur_prix_fournisseur: Optional[str] = None
    meilleur_delai_fournisseur: Optional[str] = None
    recommande_fournisseur: Optional[str] = None
    recommande_raison: Optional[str] = None


# ──────────────────────────────────────────────────────────
# DA en attente de décision
# ──────────────────────────────────────────────────────────

class DAEnAttenteDecision(BaseModel):
    """Demande d'Achat avec réponses en attente de décision"""
    id: int
    numero_da: str
    date_creation_da: datetime
    date_besoin: Optional[datetime] = None
    priorite: str
    statut: str

    # Statistiques
    nb_articles: int
    nb_fournisseurs_sollicites: int
    nb_reponses_recues: int
    taux_reponse: float  # Pourcentage

    # Articles avec comparaison
    articles: List[ArticleComparaison] = []

    # Montants estimés
    montant_min_total: Optional[float] = None
    montant_max_total: Optional[float] = None
    devise: str = "MAD"

    # Dates
    date_premiere_reponse: Optional[datetime] = None
    date_derniere_reponse: Optional[datetime] = None
    jours_depuis_premiere_reponse: Optional[int] = None


# ──────────────────────────────────────────────────────────
# Réponse Liste DA en attente
# ──────────────────────────────────────────────────────────

class DAAttenteListResponse(BaseModel):
    """Liste des DA en attente de décision"""
    da_list: List[DAEnAttenteDecision]
    total: int
    page: int
    limit: int

    # Stats globales
    total_articles_a_decider: int
    montant_potentiel_min: Optional[float] = None
    montant_potentiel_max: Optional[float] = None


# ──────────────────────────────────────────────────────────
# Détail d'une DA pour décision
# ──────────────────────────────────────────────────────────

class DADecisionDetail(DAEnAttenteDecision):
    """Détail complet d'une DA pour prise de décision"""
    # Historique des RFQ envoyées
    rfqs_envoyees: List[dict] = []

    # Recommandation globale
    fournisseur_recommande_global: Optional[str] = None
    raison_recommandation: Optional[str] = None
    montant_recommande: Optional[float] = None


# ──────────────────────────────────────────────────────────
# Création de commande
# ──────────────────────────────────────────────────────────

class CreateCommandeRequest(BaseModel):
    """Requête pour créer une commande"""
    numero_da: str
    code_fournisseur: str
    articles: List[dict]  # [{code_article, quantite, prix_unitaire_ht}]
    commentaire: Optional[str] = None


class CreateCommandeResponse(BaseModel):
    """Réponse après création de commande"""
    success: bool
    numero_commande: Optional[str] = None
    message: str
    montant_total_ht: Optional[float] = None
