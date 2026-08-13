"""
════════════════════════════════════════════════════════════
SCHEMAS - Analyse des blocages BC
════════════════════════════════════════════════════════════
Dashboard d'analyse pour comprendre pourquoi les BC ne sont pas créés
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ──────────────────────────────────────────────────────────
# Statistiques Funnel (Pipeline)
# ──────────────────────────────────────────────────────────

class FunnelStats(BaseModel):
    """Statistiques du pipeline DA -> BC"""
    # Étapes du funnel
    total_da: int = 0
    da_avec_rfq: int = 0
    da_avec_reponses: int = 0
    da_avec_selections: int = 0
    da_avec_bc: int = 0

    # Taux de conversion
    taux_rfq: float = 0  # % DA avec RFQ
    taux_reponses: float = 0  # % RFQ avec réponses
    taux_selections: float = 0  # % réponses avec sélections
    taux_bc: float = 0  # % sélections avec BC


# ──────────────────────────────────────────────────────────
# Statistiques des blocages
# ──────────────────────────────────────────────────────────

class BlocageStats(BaseModel):
    """Statistiques globales des blocages"""
    # Totaux
    total_da_non_soldees: int = 0
    total_articles_bloques: int = 0

    # Par catégorie
    nb_non_signees: int = 0
    nb_prix_superieur_tarif: int = 0
    nb_marque_differente: int = 0
    nb_marque_inexistante: int = 0  # Marque proposée n'existe pas dans X3
    nb_prix_ok_marque_inexistante: int = 0  # Prix OK mais marque n'existe pas
    nb_sans_reponse: int = 0

    # Montants
    montant_ecart_prix_total: float = 0


# ──────────────────────────────────────────────────────────
# Articles bloqués - DA non signées
# ──────────────────────────────────────────────────────────

class ArticleNonSigne(BaseModel):
    """Article sur une DA non signée"""
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite: float
    unite: Optional[str] = None
    marque_souhaitee: Optional[str] = None

    # Signature
    niveau_signature: int = 1
    libelle_signature: str = "Non signé"

    # Réponses reçues
    nb_reponses: int = 0
    meilleur_prix: Optional[float] = None
    meilleur_fournisseur: Optional[str] = None


class ArticleNonSigneListResponse(BaseModel):
    """Liste des articles non signés"""
    items: List[ArticleNonSigne]
    total: int
    page: int
    limit: int


# ──────────────────────────────────────────────────────────
# Articles bloqués - Prix > Tarif
# ──────────────────────────────────────────────────────────

class ArticlePrixSuperieur(BaseModel):
    """Article avec toutes les offres > tarif"""
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite: float

    # Tarif référence
    tarif_reference: float

    # Meilleures offres
    prix_min_propose: float
    ecart_min_pourcent: float
    ecart_min_montant: float
    fournisseur_moins_cher: str
    nom_fournisseur: Optional[str] = None

    # Stats
    nb_offres: int = 0


class ArticlePrixSuperieurListResponse(BaseModel):
    """Liste des articles avec prix > tarif"""
    items: List[ArticlePrixSuperieur]
    total: int
    page: int
    limit: int
    montant_ecart_total: float = 0


# ──────────────────────────────────────────────────────────
# Articles bloqués - Marque différente
# ──────────────────────────────────────────────────────────

class ArticleMarqueDifferente(BaseModel):
    """Article avec marque proposée différente"""
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite: float

    # Marques
    marque_souhaitee: str
    marque_proposee: str
    marque_existe_x3: bool = False

    # Offre
    code_fournisseur: str
    nom_fournisseur: Optional[str] = None
    prix_propose: float

    # Stats
    nb_offres_conformes: int = 0


class ArticleMarqueDifferenteListResponse(BaseModel):
    """Liste des articles avec marque différente"""
    items: List[ArticleMarqueDifferente]
    total: int
    page: int
    limit: int


# ──────────────────────────────────────────────────────────
# Articles bloqués - Marque inexistante dans X3
# ──────────────────────────────────────────────────────────

class ArticleMarqueInexistante(BaseModel):
    """Article avec marque proposée qui n'existe pas dans X3"""
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite: float

    # Marques
    marque_proposee: str
    marques_valides_x3: List[str] = []  # Marques autorisées pour cet article

    # Offre
    code_fournisseur: str
    nom_fournisseur: Optional[str] = None
    prix_propose: float


class ArticleMarqueInexistanteListResponse(BaseModel):
    """Liste des articles avec marque inexistante"""
    items: List[ArticleMarqueInexistante]
    total: int
    page: int
    limit: int


# ──────────────────────────────────────────────────────────
# Articles - Prix OK mais marque inexistante
# ──────────────────────────────────────────────────────────

class ArticlePrixOkMarqueInex(BaseModel):
    """Article avec prix <= tarif mais marque n'existe pas dans X3"""
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite: float

    # Prix
    tarif_reference: float
    prix_propose: float
    ecart_pourcent: float  # Négatif = moins cher que tarif

    # Marque
    marque_proposee: str
    marques_valides_x3: List[str] = []

    # Fournisseur
    code_fournisseur: str
    nom_fournisseur: Optional[str] = None


class ArticlePrixOkMarqueInexListResponse(BaseModel):
    """Liste des articles prix OK mais marque inexistante"""
    items: List[ArticlePrixOkMarqueInex]
    total: int
    page: int
    limit: int


# ──────────────────────────────────────────────────────────
# Articles bloqués - Sans réponse
# ──────────────────────────────────────────────────────────

class ArticleSansReponse(BaseModel):
    """Article sans réponse fournisseur"""
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite: float
    unite: Optional[str] = None
    marque_souhaitee: Optional[str] = None

    # RFQ
    nb_rfq_envoyees: int = 0
    fournisseurs_consultes: List[str] = []
    date_premiere_rfq: Optional[datetime] = None
    jours_depuis_rfq: int = 0


class ArticleSansReponseListResponse(BaseModel):
    """Liste des articles sans réponse"""
    items: List[ArticleSansReponse]
    total: int
    page: int
    limit: int


# ──────────────────────────────────────────────────────────
# Réponse globale du dashboard
# ──────────────────────────────────────────────────────────

class AnalyseDashboardResponse(BaseModel):
    """Réponse complète du dashboard d'analyse"""
    funnel: FunnelStats
    blocages: BlocageStats
    derniere_sync_x3: Optional[datetime] = None
