"""
════════════════════════════════════════════════════════════
SCHEMAS - Auto BC (Génération automatique de bons de commande)
════════════════════════════════════════════════════════════
Génération automatique de BC basée sur :
- Famille article (ex: 46 = mécanique)
- Prix < tarif référence (prix_base)
- Marque identique à marque_souhaitee
- Scoring : 60% prix + 40% délai
- Priorité : quantité complète > partielle
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ──────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────

class TypeLivraison(str, Enum):
    COMPLET = "COMPLET"
    PARTIEL = "PARTIEL"


class StatutExecution(str, Enum):
    SUCCES = "succes"
    ECHEC = "echec"
    PARTIEL = "partiel"


# ──────────────────────────────────────────────────────────
# Configuration Auto BC
# ──────────────────────────────────────────────────────────

class AutoBCConfig(BaseModel):
    """Configuration pour l'exécution Auto BC"""
    code_famille: str = Field(default="46", description="Code famille à traiter")
    periode_heures: int = Field(default=24, description="Période de collecte des réponses (heures)")
    poids_prix: float = Field(default=60.0, description="Poids du prix dans le score (0-100)")
    poids_delai: float = Field(default=40.0, description="Poids du délai dans le score (0-100)")
    delai_max_jours: int = Field(default=30, description="Délai max pour calcul score (jours)")
    dry_run: bool = Field(default=False, description="Mode preview sans création BC")


# ──────────────────────────────────────────────────────────
# Offre fournisseur éligible
# ──────────────────────────────────────────────────────────

class OffreEligible(BaseModel):
    """Offre fournisseur éligible pour Auto BC"""
    # Identifiants
    detail_id: int
    ligne_cotation_id: int
    reponse_entete_id: int

    # Article
    code_article: str
    designation_article: Optional[str] = None
    numero_da: str
    numero_rfq: Optional[str] = None

    # Demande
    quantite_demandee: float
    marque_souhaitee: Optional[str] = None
    tarif_reference: float  # prix_base de articles_ref

    # Offre fournisseur
    code_fournisseur: str
    nom_fournisseur: str
    email_fournisseur: Optional[str] = None
    telephone_fournisseur: Optional[str] = None
    prix_unitaire_ht: float
    quantite_disponible: float
    marque_proposee: Optional[str] = None
    delai_livraison: Optional[int] = None
    date_reponse: datetime

    # Calculs
    type_livraison: TypeLivraison
    score: float
    economie_pourcent: float  # (tarif_reference - prix) / tarif_reference * 100


class ArticleAvecOffres(BaseModel):
    """Article avec toutes ses offres éligibles"""
    code_article: str
    designation_article: Optional[str] = None
    numero_da: str
    quantite_demandee: float
    tarif_reference: float
    marque_souhaitee: Optional[str] = None

    # Offres
    offres_completes: List[OffreEligible] = []
    offres_partielles: List[OffreEligible] = []

    # Meilleure offre sélectionnée
    offre_selectionnee: Optional[OffreEligible] = None


# ──────────────────────────────────────────────────────────
# Preview (dry-run)
# ──────────────────────────────────────────────────────────

class BCPreviewLigne(BaseModel):
    """Ligne de BC en preview"""
    code_article: str
    designation_article: Optional[str] = None
    numero_da: str
    quantite_commandee: float
    prix_unitaire_ht: float
    montant_ligne_ht: float
    type_livraison: TypeLivraison
    score: float
    economie_pourcent: float
    delai_livraison: Optional[int] = None


class BCPreview(BaseModel):
    """Preview d'un BC à créer"""
    code_fournisseur: str
    nom_fournisseur: str
    lignes: List[BCPreviewLigne]
    nb_lignes: int
    montant_total_ht: float
    montant_tva: float
    montant_total_ttc: float
    das_incluses: List[str]


class AutoBCPreviewResponse(BaseModel):
    """Réponse du preview Auto BC"""
    config: AutoBCConfig
    date_preview: datetime

    # Statistiques
    nb_articles_eligibles: int
    nb_articles_avec_offre_complete: int
    nb_articles_avec_offre_partielle: int
    nb_articles_sans_offre: int

    # BC à créer (groupés par fournisseur)
    bcs_preview: List[BCPreview]
    nb_bc_a_creer: int

    # Articles sans offre conforme
    articles_sans_offre: List[str] = []  # Liste des code_article

    # Économie totale estimée
    economie_totale_estimee: float


# ──────────────────────────────────────────────────────────
# Exécution Auto BC
# ──────────────────────────────────────────────────────────

class AutoBCExecuteRequest(BaseModel):
    """Requête pour exécuter Auto BC"""
    config: Optional[AutoBCConfig] = None  # Si None, utilise config par défaut
    execute_par: str = Field(default="SYSTEM", description="Identifiant de l'exécuteur")


class BCCree(BaseModel):
    """BC créé avec succès"""
    numero_bc: str
    code_fournisseur: str
    nom_fournisseur: str
    nb_lignes: int
    montant_total_ht: float
    montant_total_ttc: float
    das_incluses: List[str]


class AutoBCExecuteResponse(BaseModel):
    """Réponse de l'exécution Auto BC"""
    success: bool
    statut: StatutExecution
    message: str

    # Exécution
    date_execution: datetime
    duree_execution_ms: int
    config: AutoBCConfig
    execute_par: str

    # Résultats
    nb_articles_eligibles: int
    nb_articles_traites: int
    nb_bc_crees: int

    # BC créés
    bcs_crees: List[BCCree] = []

    # Économie réalisée
    economie_totale: float

    # Alertes
    articles_sans_offre: List[str] = []
    articles_partiels: List[str] = []
    erreurs: List[str] = []

    # ID du log pour référence
    log_id: Optional[int] = None


# ──────────────────────────────────────────────────────────
# Historique
# ──────────────────────────────────────────────────────────

class LogAutoBCDetail(BaseModel):
    """Détail d'un article dans un log Auto BC"""
    code_article: str
    designation_article: Optional[str] = None
    quantite_demandee: float
    code_fournisseur: str
    nom_fournisseur: Optional[str] = None
    prix_unitaire: float
    quantite_commandee: float
    delai_livraison: Optional[int] = None
    score: float
    type_livraison: TypeLivraison
    numero_bc: Optional[str] = None


class LogAutoBC(BaseModel):
    """Log d'une exécution Auto BC"""
    id: int
    date_execution: datetime
    code_famille: str
    periode_heures: int

    # Résultats
    nb_articles_eligibles: int
    nb_articles_traites: int
    nb_bc_crees: int
    numeros_bc_crees: List[str] = []

    # Statut
    statut: StatutExecution
    message_erreur: Optional[str] = None

    # Traçabilité
    execute_par: str
    duree_execution_ms: Optional[int] = None

    # Détails (optionnel)
    details: List[LogAutoBCDetail] = []


class LogAutoBCListResponse(BaseModel):
    """Liste des logs Auto BC"""
    logs: List[LogAutoBC]
    total: int
    page: int
    limit: int
