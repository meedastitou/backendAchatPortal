"""
════════════════════════════════════════════════════════════
ROUTER - DA Non Soldées (Sage X3)
════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional
from datetime import date

from app.auth.dependencies import get_current_user, get_user_famille_filter
from app.database import execute_insert, execute_query, execute_x3_query
from app.schemas.da_non_soldees import (
    DemandeAchatResponse, DemandeAchatBase,
    DATransfertRequest, DANonSoldeeResponse, StatutDA
)


router = APIRouter(prefix="/das", tags=["DA Non Soldées"])


# ──────────────────────────────────────────────────────────
# DA non soldées (Sage X3)
# ──────────────────────────────────────────────────────────

# Constantes d'exclusion
FAMILLES_EXCLUES = ["R.H", "ELECTRICITE"]
ARTICLES_EXCLUS = ["A09985", "A10107", "A10136"]


@router.get("/non-soldees", response_model=list[DANonSoldeeResponse])
async def get_das_non_soldees(
    date_debut: date = Query(..., description="Date minimale de la DA"),
    famille: Optional[str] = Query(None, description="Filtrer par famille"),
    article: Optional[str] = Query(None, description="Filtrer par code article (recherche partielle)"),
    numero_da: Optional[str] = Query(None, description="Filtrer par numéro de DA (recherche partielle)"),
    current_user: dict = Depends(get_current_user)
):
    date_debut_str = date_debut.strftime("%Y%m%d")

    conditions = ["DNS.DateDA >= ?", "DA.CLEFLG_0 = 1"]
    params = [date_debut_str]

    placeholders_familles = ", ".join(["?"] * len(FAMILLES_EXCLUES))
    conditions.append(f"DNS.Famille NOT IN ({placeholders_familles})")
    params.extend(FAMILLES_EXCLUES)

    placeholders_articles = ", ".join(["?"] * len(ARTICLES_EXCLUS))
    conditions.append(f"DNS.Article NOT IN ({placeholders_articles})")
    params.extend(ARTICLES_EXCLUS)

    if famille:
        conditions.append("DNS.Famille = ?")
        params.append(famille)

    if article:
        conditions.append("DNS.Article LIKE ?")
        params.append(f"%{article}%")

    if numero_da:
        conditions.append("DNS.DA LIKE ?")
        params.append(f"%{numero_da}%")

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT DNS.DA, DNS.Article, DNS.DésignationArticle, DNS.QteDA,
               DAD.XMARQ_0 AS marque, DNS.STU_0 AS Unite, DNS.Famille AS Famille
        FROM x3.BASE1.Y_DA_NON_SOLDEES DNS
        LEFT JOIN x3.BASE1.PREQUIS DA ON DA.PSHNUM_0 = DNS.DA
        INNER JOIN x3.BASE1.PREQUISD DAD
            ON DAD.PSHNUM_0 = DA.PSHNUM_0 AND DAD.ITMREF_0 = DNS.Article
        WHERE {where_clause}
        ORDER BY DNS.DA
    """

    return execute_x3_query(query, tuple(params))


# ──────────────────────────────────────────────────────────
# Transferer une DA non soldée vers demandes_achat
# ──────────────────────────────────────────────────────────

@router.post("/transferer", response_model=DemandeAchatResponse, status_code=status.HTTP_201_CREATED)
async def transferer_da(
    payload: DATransfertRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Transferer une DA non soldee (Sage X3) vers la table demandes_achat (MySQL),
    pour qu'elle apparaisse dans les listes de selection.
    """

    existing = execute_query(
        "SELECT id FROM demandes_achat WHERE numero_da = %s AND code_article = %s",
        (payload.numero_da, payload.code_article),
        fetch_one=True
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette DA a deja ete transferee"
        )

    insert_query = """
        INSERT INTO demandes_achat
            (numero_da, code_article, designation_article, quantite,
             unite, marque_souhaitee, priorite, statut, date_creation_da, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
    """
    new_id = execute_insert(insert_query, (
        payload.numero_da,
        payload.code_article,
        payload.designation_article,
        payload.quantite,
        payload.unite,
        payload.marque_souhaitee,
        payload.priorite.value,
        StatutDA.nouveau.value
    )) 

    created = execute_query(
        "SELECT * FROM demandes_achat WHERE id = %s",
        (new_id,),
        fetch_one=True
    )
    return DemandeAchatResponse(**created)