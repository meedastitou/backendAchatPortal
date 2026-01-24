"""
════════════════════════════════════════════════════════════
SCHEMAS - Dashboard & Statistiques
════════════════════════════════════════════════════════════
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ──────────────────────────────────────────────────────────
# Statistiques globales
# ──────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    """Statistiques principales du dashboard"""
    total_da_actives: int = 0
    rfq_en_attente: int = 0
    rfq_repondues: int = 0
    rfq_rejetees: int = 0
    fournisseurs_actifs: int = 0
    fournisseurs_blacklistes: int = 0
    commandes_en_cours: int = 0
    taux_reponse_moyen: float = 0.0


class DashboardStatsDetailed(DashboardStats):
    """Statistiques détaillées"""
    total_rfq_envoyees: int = 0
    total_commandes: int = 0
    montant_total_commandes: float = 0.0
    delai_moyen_reponse_heures: float = 0.0


# ──────────────────────────────────────────────────────────
# Activité récente
# ──────────────────────────────────────────────────────────

class RecentActivity(BaseModel):
    """Élément d'activité récente"""
    id: int
    type: str  # 'rfq_envoyee', 'reponse_recue', 'commande_creee', etc.
    description: str
    date: datetime
    details: Optional[dict] = None


class RecentActivitiesResponse(BaseModel):
    """Liste des activités récentes"""
    activities: List[RecentActivity]
    total: int


# ──────────────────────────────────────────────────────────
# Graphiques
# ──────────────────────────────────────────────────────────

class ChartDataPoint(BaseModel):
    """Point de données pour graphique"""
    label: str
    value: float


class ChartData(BaseModel):
    """Données pour graphique"""
    title: str
    data: List[ChartDataPoint]


class RFQStatusChart(BaseModel):
    """Répartition des statuts RFQ"""
    envoye: int = 0
    vu: int = 0
    repondu: int = 0
    rejete: int = 0
    expire: int = 0
    relance_1: int = 0
    relance_2: int = 0
    relance_3: int = 0


# ──────────────────────────────────────────────────────────
# Top Fournisseurs
# ──────────────────────────────────────────────────────────

class TopFournisseur(BaseModel):
    """Fournisseur avec performance"""
    code_fournisseur: str
    nom_fournisseur: str
    taux_reponse: float
    note_performance: float
    nb_reponses: int


class TopFournisseursResponse(BaseModel):
    """Liste des meilleurs fournisseurs"""
    fournisseurs: List[TopFournisseur]


# ──────────────────────────────────────────────────────────
# Alertes
# ──────────────────────────────────────────────────────────

class AlertItem(BaseModel):
    """Alerte du dashboard"""
    id: int
    type: str  # 'warning', 'error', 'info'
    titre: str
    message: str
    date: datetime
    lien: Optional[str] = None


class AlertsResponse(BaseModel):
    """Liste des alertes"""
    alerts: List[AlertItem]
    total: int


# ──────────────────────────────────────────────────────────
# Dernières réponses fournisseurs
# ──────────────────────────────────────────────────────────

class ReponseDetailItem(BaseModel):
    """Détail d'un article dans une réponse"""
    code_article: str
    designation: Optional[str] = None
    prix_unitaire_ht: Optional[float] = None
    quantite_demandee: Optional[float] = None
    devise: str = "MAD"


class RecentReponse(BaseModel):
    """Réponse fournisseur récente"""
    id: int
    numero_rfq: str
    code_fournisseur: str
    nom_fournisseur: str
    date_reponse: datetime
    nb_articles: int
    montant_total_ht: Optional[float] = None
    devise: str = "MAD"
    methodes_paiement: Optional[str] = None
    articles: List[ReponseDetailItem] = []


class RecentReponsesResponse(BaseModel):
    """Liste des réponses récentes"""
    reponses: List[RecentReponse]
    total: int
