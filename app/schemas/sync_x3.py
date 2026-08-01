"""
════════════════════════════════════════════════════════════
SCHEMAS - Synchronisation statuts DA avec Sage X3
════════════════════════════════════════════════════════════
Permet de synchroniser les statuts (signé/soldé) des DA
depuis Sage X3 vers le portail flux_achat
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ──────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────

class TypeSync(str, Enum):
    MANUEL = "manuel"
    AUTO = "auto"
    PLANIFIE = "planifie"


class StatutSync(str, Enum):
    SUCCES = "succes"
    PARTIEL = "partiel"
    ECHEC = "echec"


class NiveauSignature(int, Enum):
    NON_SIGNE = 1
    VISA_1 = 2
    VISA_2 = 3
    VISA_3 = 4
    SIGNE_COMPLET = 5


class StatutX3Combine(str, Enum):
    SOLDE = "SOLDE"
    EN_ATTENTE_SIGNATURE = "EN_ATTENTE_SIGNATURE"
    ACTIVE = "ACTIVE"


# ──────────────────────────────────────────────────────────
# Requêtes de synchronisation
# ──────────────────────────────────────────────────────────

class SyncX3Request(BaseModel):
    """Requête pour lancer une synchronisation"""
    type_sync: TypeSync = Field(default=TypeSync.MANUEL, description="Type de synchronisation")
    numero_da: Optional[str] = Field(default=None, description="Synchroniser une DA spécifique (sinon toutes)")
    limit: int = Field(default=500, description="Nombre max de DA à synchroniser")
    force_update: bool = Field(default=False, description="Forcer la mise à jour même si déjà synchronisé récemment")


# ──────────────────────────────────────────────────────────
# Résultats de synchronisation
# ──────────────────────────────────────────────────────────

class DAStatusX3(BaseModel):
    """Statut X3 d'une DA"""
    numero_da: str
    code_article: Optional[str] = None

    # Statuts X3
    x3_signe: bool = False
    x3_niveau_signature: int = 1
    x3_solde: bool = False

    # Statut combiné
    statut_combine: StatutX3Combine = StatutX3Combine.EN_ATTENTE_SIGNATURE

    # Changements détectés
    signature_changee: bool = False
    solde_change: bool = False


class SyncX3Response(BaseModel):
    """Réponse d'une synchronisation"""
    success: bool
    statut: StatutSync
    message: str

    # Timing
    date_sync: datetime
    duree_ms: int

    # Statistiques
    nb_da_verifiees: int
    nb_da_mises_a_jour: int
    nb_nouvelles_signees: int
    nb_nouvelles_soldees: int

    # Détails des changements (optionnel)
    changements: List[DAStatusX3] = []

    # Erreurs
    erreurs: List[str] = []

    # ID du log
    log_id: Optional[int] = None


# ──────────────────────────────────────────────────────────
# Stats X3 pour dashboard
# ──────────────────────────────────────────────────────────

class StatsX3(BaseModel):
    """Statistiques des statuts X3"""
    total_da: int

    # Par signature
    nb_signees: int
    nb_non_signees: int

    # Par solde
    nb_soldees: int
    nb_non_soldees: int

    # Combinaisons utiles
    nb_signees_non_soldees: int  # Prêtes pour BC
    nb_en_attente_signature: int

    # Sync
    derniere_sync: Optional[datetime] = None
    nb_jamais_sync: int


# ──────────────────────────────────────────────────────────
# Liste des DA avec statut X3
# ──────────────────────────────────────────────────────────

class DAAvecStatutX3(BaseModel):
    """DA avec son statut X3 pour affichage dans le portail"""
    id: int
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite: float
    unite: Optional[str] = None
    marque_souhaitee: Optional[str] = None
    date_creation_da: datetime
    date_besoin: Optional[datetime] = None

    # Statut portail
    statut_portail: str
    priorite: str

    # Statuts X3
    x3_signe: bool = False
    x3_niveau_signature: int = 1
    libelle_signature: str = "Non signé"
    x3_solde: bool = False
    libelle_solde: str = "Active"
    statut_x3_combine: StatutX3Combine = StatutX3Combine.EN_ATTENTE_SIGNATURE

    # Sync
    x3_derniere_sync: Optional[datetime] = None


class DAListX3Response(BaseModel):
    """Liste paginée des DA avec statut X3"""
    items: List[DAAvecStatutX3]
    total: int
    page: int
    limit: int

    # Stats rapides
    stats: Optional[StatsX3] = None


# ──────────────────────────────────────────────────────────
# Historique des syncs
# ──────────────────────────────────────────────────────────

class LogSyncX3(BaseModel):
    """Log d'une synchronisation"""
    id: int
    date_sync: datetime
    type_sync: TypeSync

    # Stats
    nb_da_verifiees: int
    nb_da_mises_a_jour: int
    nb_nouvelles_signees: int
    nb_nouvelles_soldees: int

    # Statut
    statut: StatutSync
    message_erreur: Optional[str] = None
    duree_ms: Optional[int] = None

    # Traçabilité
    execute_par: str


class LogSyncX3ListResponse(BaseModel):
    """Liste des logs de synchronisation"""
    logs: List[LogSyncX3]
    total: int
    page: int
    limit: int


# ──────────────────────────────────────────────────────────
# Alertes et Analyses
# ──────────────────────────────────────────────────────────

class ReponseDANonSignee(BaseModel):
    """Réponse fournisseur sur une DA non signée"""
    # DA
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite_demandee: float
    marque_souhaitee: Optional[str] = None

    # Réponse fournisseur
    reponse_id: int
    code_fournisseur: str
    nom_fournisseur: Optional[str] = None
    prix_unitaire: float
    quantite_disponible: float
    delai_livraison: Optional[int] = None
    date_reponse: datetime

    # Statut X3
    x3_niveau_signature: int = 1
    libelle_signature: str = "Non signé"


class ReponseDANonSigneeListResponse(BaseModel):
    """Liste des réponses sur DA non signées"""
    items: List[ReponseDANonSignee]
    total: int
    page: int
    limit: int


class OffrePrixSuperieurTarif(BaseModel):
    """Offre avec prix supérieur au tarif X3"""
    # Article
    code_article: str
    designation_article: Optional[str] = None
    numero_da: str

    # Tarif X3
    tarif_x3: float

    # Offre fournisseur
    reponse_id: int
    code_fournisseur: str
    nom_fournisseur: Optional[str] = None
    prix_propose: float
    quantite_disponible: float
    date_reponse: datetime

    # Calcul
    ecart_pourcent: float  # (prix - tarif) / tarif * 100
    ecart_montant: float   # prix - tarif


class OffrePrixSuperieurTarifListResponse(BaseModel):
    """Liste des offres avec prix > tarif"""
    items: List[OffrePrixSuperieurTarif]
    total: int
    page: int
    limit: int
    # Stats
    nb_total_offres: int
    montant_ecart_total: float


class MarqueX3(BaseModel):
    """Marque existant dans Sage X3"""
    code_article: str
    marque: str
    prix: Optional[float] = None


class OffreMarqueDifferente(BaseModel):
    """Offre avec marque différente de celle demandée"""
    # Article
    code_article: str
    designation_article: Optional[str] = None
    numero_da: str
    marque_souhaitee: Optional[str] = None

    # Offre fournisseur
    reponse_id: int
    code_fournisseur: str
    nom_fournisseur: Optional[str] = None
    marque_proposee: Optional[str] = None
    prix_propose: float
    quantite_disponible: float
    date_reponse: datetime

    # Validation X3
    marque_existe_x3: bool = False
    marques_disponibles_x3: List[str] = []


class OffreMarqueDifferenteListResponse(BaseModel):
    """Liste des offres avec marque différente"""
    items: List[OffreMarqueDifferente]
    total: int
    page: int
    limit: int


class DANonSoldeeX3(BaseModel):
    """DA non soldée depuis Sage X3"""
    numero_da: str
    code_article: str
    designation_article: Optional[str] = None
    quantite: float
    marque: Optional[str] = None
    unite: Optional[str] = None
    famille: Optional[str] = None
    date_da: Optional[datetime] = None

    # Infos portail (si existe)
    existe_portail: bool = False
    nb_reponses: int = 0
    statut_portail: Optional[str] = None


class DANonSoldeeX3ListResponse(BaseModel):
    """Liste des DA non soldées depuis X3"""
    items: List[DANonSoldeeX3]
    total: int
    page: int
    limit: int


# ──────────────────────────────────────────────────────────
# Stats étendues pour dashboard
# ──────────────────────────────────────────────────────────

class StatsAlertesX3(BaseModel):
    """Statistiques des alertes X3"""
    # Réponses sur DA non signées
    nb_reponses_da_non_signees: int = 0

    # Prix > tarif
    nb_offres_prix_superieur: int = 0
    montant_ecart_total: float = 0

    # Marque différente
    nb_offres_marque_differente: int = 0

    # DA non soldées X3
    nb_da_non_soldees_x3: int = 0
