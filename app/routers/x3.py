"""
════════════════════════════════════════════════════════════
ROUTER - Sage X3 (Réceptions)
════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, HTTPException, status
from typing import Optional

from app.sqlserver_db import execute_x3_query
from app.schemas.x3 import DerniereReceptionResponse


router = APIRouter(prefix="/x3", tags=["Sage X3"])


# ──────────────────────────────────────────────────────────
# Dernière réception par article
# ──────────────────────────────────────────────────────────

@router.get("/receptions/derniere/{code_article}", response_model=DerniereReceptionResponse)
async def get_derniere_reception(code_article: str):
    """
    Récupérer la dernière réception d'un article depuis Sage X3.

    Retourne le dernier fournisseur avec son prix pour l'article spécifié.

    - **code_article**: Code article (ITMREF_0)
    """

    query = """
        SELECT TOP 1
            ITMREF_0 AS code_article,
            ITMDES1_0 AS designation,
            BPSNUM_0 AS code_fournisseur,
            NETPRI_0 AS prix,
            NETCUR_0 AS devise,
            RCPDAT_0 AS date_reception
        FROM x3.BASE1.PRECEIPTD
        WHERE ITMREF_0 = :code_article
        ORDER BY RCPDAT_0 DESC
    """

    result = execute_x3_query(query, {"code_article": code_article}, fetch_one=True)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Aucune réception trouvée pour l'article {code_article}"
        )

    return DerniereReceptionResponse(**result)


@router.get("/receptions/historique/{code_article}")
async def get_historique_receptions(
    code_article: str,
    limit: int = 10
):
    """
    Récupérer l'historique des réceptions d'un article depuis Sage X3.

    - **code_article**: Code article (ITMREF_0)
    - **limit**: Nombre maximum de résultats (défaut: 10)
    """

    query = """
        SELECT TOP :limit
            ITMREF_0 AS code_article,
            ITMDES1_0 AS designation,
            BPSNUM_0 AS code_fournisseur,
            NETPRI_0 AS prix,
            NETCUR_0 AS devise,
            RCPDAT_0 AS date_reception
        FROM x3.BASE1.PRECEIPTD
        WHERE ITMREF_0 = :code_article
        ORDER BY RCPDAT_0 DESC
    """

    # Note: SQLAlchemy avec SQL Server ne supporte pas bien TOP :param
    # On utilise une requête différente
    query = f"""
        SELECT TOP {int(limit)}
            ITMREF_0 AS code_article,
            ITMDES1_0 AS designation,
            BPSNUM_0 AS code_fournisseur,
            NETPRI_0 AS prix,
            NETCUR_0 AS devise,
            RCPDAT_0 AS date_reception
        FROM x3.BASE1.PRECEIPTD
        WHERE ITMREF_0 = :code_article
        ORDER BY RCPDAT_0 DESC
    """

    results = execute_x3_query(query, {"code_article": code_article})

    return {
        "code_article": code_article,
        "receptions": results,
        "total": len(results)
    }
