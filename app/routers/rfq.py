"""
════════════════════════════════════════════════════════════
ROUTER - Demandes de Cotation (RFQ)
════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional
from datetime import datetime

from app.auth.dependencies import get_current_user
from app.database import execute_query
from app.schemas.rfq import (
    RFQResponse,
    RFQDetailResponse,
    RFQListResponse,
    LigneCotationResponse,
    StatutRFQ
)


router = APIRouter(prefix="/rfq", tags=["Demandes de Cotation"])


# ──────────────────────────────────────────────────────────
# Liste des RFQ
# ──────────────────────────────────────────────────────────

@router.get("", response_model=RFQListResponse)
async def list_rfq(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    statut: Optional[StatutRFQ] = None,
    code_fournisseur: Optional[str] = None,
    date_debut: Optional[datetime] = None,
    date_fin: Optional[datetime] = None,
    search: Optional[str] = None,
    code_article: Optional[str] = None,
    numero_da: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Lister les demandes de cotation avec filtres"""

    conditions = ["1=1"]
    params = []
    join_lignes = False

    if statut:
        conditions.append("dc.statut = %s")
        params.append(statut.value)

    if code_fournisseur:
        conditions.append("dc.code_fournisseur = %s")
        params.append(code_fournisseur)

    if date_debut:
        conditions.append("dc.date_envoi >= %s")
        params.append(date_debut)

    if date_fin:
        conditions.append("dc.date_envoi <= %s")
        params.append(date_fin)

    if search:
        conditions.append("(dc.numero_rfq LIKE %s OR f.nom_fournisseur LIKE %s)")
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern])

    if code_article:
        join_lignes = True
        conditions.append("lc.code_article LIKE %s")
        params.append(f"%{code_article}%")

    if numero_da:
        join_lignes = True
        conditions.append("lc.numero_da LIKE %s")
        params.append(f"%{numero_da}%")

    where_clause = " AND ".join(conditions)
    lignes_join = "JOIN lignes_cotation lc ON dc.uuid = lc.rfq_uuid" if join_lignes else ""

    # Count
    count_query = f"""
        SELECT COUNT(DISTINCT dc.id) as total
        FROM demandes_cotation dc
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        {lignes_join}
        WHERE {where_clause}
    """
    total = execute_query(count_query, tuple(params), fetch_one=True)["total"]

    # Get RFQs
    offset = (page - 1) * limit
    query = f"""
        SELECT DISTINCT
            dc.*,
            f.nom_fournisseur,
            f.email as email_fournisseur
        FROM demandes_cotation dc
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        {lignes_join}
        WHERE {where_clause}
        ORDER BY dc.date_envoi DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    rfqs = execute_query(query, tuple(params))

    # Ajouter les lignes pour chaque RFQ
    rfq_responses = []
    for rfq in rfqs:
        lignes = execute_query(
            "SELECT * FROM lignes_cotation WHERE rfq_uuid = %s",
            (rfq["uuid"],)
        )
        rfq_responses.append(RFQResponse(
            **rfq,
            lignes=[LigneCotationResponse(**l) for l in lignes]
        ))

    return RFQListResponse(
        rfqs=rfq_responses,
        total=total,
        page=page,
        limit=limit
    )


# ──────────────────────────────────────────────────────────
# Détail d'une RFQ
# ──────────────────────────────────────────────────────────

@router.get("/{rfq_id}", response_model=RFQDetailResponse)
async def get_rfq(
    rfq_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Obtenir les détails d'une RFQ"""

    query = """
        SELECT
            dc.*,
            f.nom_fournisseur,
            f.email as email_fournisseur,
            DATEDIFF(NOW(), dc.date_envoi) as jours_depuis_envoi,
            TIMESTAMPDIFF(HOUR, dc.date_envoi, dc.date_reponse) as delai_reponse_heures
        FROM demandes_cotation dc
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE dc.id = %s
    """
    rfq = execute_query(query, (rfq_id,), fetch_one=True)

    if not rfq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RFQ non trouvée"
        )

    # Récupérer les lignes
    lignes = execute_query(
        "SELECT * FROM lignes_cotation WHERE rfq_uuid = %s",
        (rfq["uuid"],)
    )

    return RFQDetailResponse(
        **rfq,
        lignes=[LigneCotationResponse(**l) for l in lignes],
        nb_articles=len(lignes)
    )


# ──────────────────────────────────────────────────────────
# RFQ par UUID
# ──────────────────────────────────────────────────────────

@router.get("/uuid/{uuid}", response_model=RFQDetailResponse)
async def get_rfq_by_uuid(
    uuid: str,
    current_user: dict = Depends(get_current_user)
):
    """Obtenir une RFQ par son UUID"""

    query = """
        SELECT
            dc.*,
            f.nom_fournisseur,
            f.email as email_fournisseur,
            DATEDIFF(NOW(), dc.date_envoi) as jours_depuis_envoi,
            TIMESTAMPDIFF(HOUR, dc.date_envoi, dc.date_reponse) as delai_reponse_heures
        FROM demandes_cotation dc
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE dc.uuid = %s
    """
    rfq = execute_query(query, (uuid,), fetch_one=True)

    if not rfq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RFQ non trouvée"
        )

    lignes = execute_query(
        "SELECT * FROM lignes_cotation WHERE rfq_uuid = %s",
        (uuid,)
    )

    return RFQDetailResponse(
        **rfq,
        lignes=[LigneCotationResponse(**l) for l in lignes],
        nb_articles=len(lignes)
    )


# ──────────────────────────────────────────────────────────
# Statistiques par statut
# ──────────────────────────────────────────────────────────

@router.get("/stats/by-status")
async def get_rfq_stats_by_status(current_user: dict = Depends(get_current_user)):
    """Statistiques des RFQ par statut"""

    query = """
        SELECT statut, COUNT(*) as count
        FROM demandes_cotation
        GROUP BY statut
        ORDER BY count DESC
    """
    results = execute_query(query)

    return {
        "stats": results,
        "total": sum(r["count"] for r in results)
    }


# ──────────────────────────────────────────────────────────
# RFQ en attente de réponse
# ──────────────────────────────────────────────────────────

@router.get("/pending/list")
async def get_pending_rfq(
    days_old: int = Query(7, ge=1),
    current_user: dict = Depends(get_current_user)
):
    """Lister les RFQ en attente depuis plus de X jours"""

    query = """
        SELECT
            dc.*,
            f.nom_fournisseur,
            f.email as email_fournisseur,
            DATEDIFF(NOW(), dc.date_envoi) as jours_depuis_envoi
        FROM demandes_cotation dc
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE dc.statut IN ('envoye', 'relance_1', 'relance_2', 'relance_3')
          AND dc.date_reponse IS NULL
          AND DATEDIFF(NOW(), dc.date_envoi) >= %s
        ORDER BY dc.date_envoi ASC
    """
    rfqs = execute_query(query, (days_old,))

    return {
        "rfqs": rfqs,
        "total": len(rfqs),
        "days_threshold": days_old
    }
