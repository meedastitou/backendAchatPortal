"""
════════════════════════════════════════════════════════════
SCHEMAS - Selections Articles (Pre-Bon de Commande)
════════════════════════════════════════════════════════════
Gestion des selections de fournisseurs par article avant
la generation du bon de commande.
"""

from pydantic import BaseModel
from typing import Optional, List, Union
from datetime import datetime, date
from enum import Enum


class StatutSelection(str, Enum):
    SELECTIONNE = "selectionne"
    EN_ATTENTE_BC = "en_attente_bc"
    BC_GENERE = "bc_genere"


# ──────────────────────────────────────────────────────────
# Selection d'un article
# ──────────────────────────────────────────────────────────

class SelectionArticleCreate(BaseModel):
    """Creation d'une selection d'article"""
    code_article: str
    designation: Optional[str] = None
    numero_da: str
    quantite: float
    unite: Optional[str] = None

    # Fournisseur selectionne
    code_fournisseur: str
    detail_id: int  # ID dans reponses_fournisseurs_detail

    # Prix et marque
    prix_selectionne: float
    devise: str = "MAD"
    marque_proposee: Optional[str] = None
    marque_conforme: Optional[bool] = None

    # Livraison (accepte date ou string)
    date_livraison: Optional[Union[date, str]] = None
    delai_livraison: Optional[int] = None


class SelectionArticleUpdate(BaseModel):
    """Modification d'une selection (changement de fournisseur)"""
    code_fournisseur: str
    detail_id: int
    prix_selectionne: float
    devise: str = "MAD"
    marque_proposee: Optional[str] = None
    marque_conforme: Optional[bool] = None
    date_livraison: Optional[Union[date, str]] = None
    delai_livraison: Optional[int] = None


class SelectionArticleResponse(BaseModel):
    """Selection d'article en lecture"""
    id: int
    code_article: str
    designation: Optional[str] = None
    numero_da: str
    quantite: float
    unite: Optional[str] = None

    # Fournisseur
    code_fournisseur: str
    nom_fournisseur: Optional[str] = None
    detail_id: int

    # Prix et marque
    prix_selectionne: float
    devise: str
    marque_proposee: Optional[str] = None
    marque_conforme: Optional[bool] = None

    # Livraison
    date_livraison: Optional[Union[date, str]] = None
    delai_livraison: Optional[int] = None

    # Tracabilite
    selection_auto: bool
    modifie_par: Optional[str] = None
    date_selection: datetime
    date_modification: Optional[datetime] = None

    # Statut
    statut: StatutSelection
    numero_bc: Optional[str] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────────────────
# Selection automatique (meilleur prix)
# ──────────────────────────────────────────────────────────

class SelectionAutoRequest(BaseModel):
    """Demande de selection automatique pour plusieurs articles"""
    articles: List[str]  # Liste de codes articles ou "all" pour tous


class SelectionAutoResponse(BaseModel):
    """Resultat de la selection automatique"""
    success: bool
    message: str
    nb_articles_selectionnes: int
    selections: List[SelectionArticleResponse] = []


# ──────────────────────────────────────────────────────────
# Vue Pre-BC (groupee par fournisseur)
# ──────────────────────────────────────────────────────────

class ArticleSelectionne(BaseModel):
    """Article selectionne pour un fournisseur"""
    id: int  # ID de la selection
    code_article: str
    designation: Optional[str] = None
    numero_da: str
    quantite: float
    unite: Optional[str] = None
    prix_unitaire: float
    montant_ligne: float
    devise: str
    marque_proposee: Optional[str] = None
    marque_conforme: Optional[bool] = None
    date_livraison: Optional[date] = None
    selection_auto: bool


class FournisseurPreBC(BaseModel):
    """Fournisseur avec ses articles selectionnes"""
    code_fournisseur: str
    nom_fournisseur: str
    email: Optional[str] = None
    telephone: Optional[str] = None

    # Articles selectionnes
    articles: List[ArticleSelectionne]

    # Totaux
    nb_articles: int
    nb_das: int
    das: List[str]  # Liste des numeros DA
    montant_total_ht: float
    devise: str = "MAD"


class PreBCDashboardResponse(BaseModel):
    """Dashboard Pre-BC avec tous les fournisseurs"""
    fournisseurs: List[FournisseurPreBC]
    total_fournisseurs: int
    total_articles: int
    total_das: int
    montant_global_ht: float


# ──────────────────────────────────────────────────────────
# Generation BC depuis Pre-BC
# ──────────────────────────────────────────────────────────

class GenererBCFromPreBCRequest(BaseModel):
    """Demande de generation de BC pour un fournisseur"""
    code_fournisseur: str
    selection_ids: List[int]  # IDs des selections a inclure
    conditions_paiement: Optional[str] = None
    lieu_livraison: Optional[str] = None
    commentaire: Optional[str] = None


class GenererBCFromPreBCResponse(BaseModel):
    """Resultat de la generation de BC"""
    success: bool
    message: str
    numero_bc: Optional[str] = None
    code_fournisseur: Optional[str] = None
    nom_fournisseur: Optional[str] = None
    nb_lignes: Optional[int] = None
    montant_total_ht: Optional[float] = None
    montant_total_ttc: Optional[float] = None
