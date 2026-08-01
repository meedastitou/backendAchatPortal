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


# ──────────────────────────────────────────────────────────
# Statut de signature DA/Article
# ──────────────────────────────────────────────────────────

@router.get("/signature/{numero_da}/{code_article}")
async def get_statut_signature(numero_da: str, code_article: str):
    """
    Vérifier le statut de signature d'un article dans une DA depuis Sage X3.

    - **numero_da**: Numéro de la demande d'achat (PSHNUM_0)
    - **code_article**: Code article (ITMREF_0)

    Retourne le statut de signature:
    - "Pas de gestion" (LINAPPFLG_0 = 0 ou 4)
    - "Non" (LINAPPFLG_0 = 1)
    - "Partiellement" (LINAPPFLG_0 = 2)
    - "Oui" (LINAPPFLG_0 = 3 ou 5)
    """

    query = """
        SELECT TOP 1
            PSHNUM_0 AS numero_da,
            ITMREF_0 AS code_article,
            LINAPPFLG_0 AS flag_signature,
            CASE
                WHEN LINAPPFLG_0 IN (0, 4) THEN 'Pas de gestion'
                WHEN LINAPPFLG_0 = 1 THEN 'Non'
                WHEN LINAPPFLG_0 = 2 THEN 'Partiellement'
                WHEN LINAPPFLG_0 IN (3, 5) THEN 'Oui'
                ELSE 'Inconnu'
            END AS statut_signature
        FROM x3.BASE1.PREQUISD
        WHERE PSHNUM_0 = :numero_da AND ITMREF_0 = :code_article
    """

    result = execute_x3_query(query, {"numero_da": numero_da, "code_article": code_article}, fetch_one=True)

    if not result:
        return {
            "numero_da": numero_da,
            "code_article": code_article,
            "statut_signature": "Non trouvé",
            "flag_signature": None
        }

    return result


@router.get("/signatures/bulk")
async def get_statuts_signatures_bulk(articles: str):
    """
    Vérifier le statut de signature pour plusieurs articles/DA en une seule requête.

    - **articles**: Liste au format "DA1:ART1,DA2:ART2,..."

    Exemple: /signatures/bulk?articles=DA171164:A14710,DA171165:A14711
    """

    # Parser les articles
    items = []
    for item in articles.split(","):
        if ":" in item:
            da, art = item.strip().split(":", 1)
            items.append((da.strip(), art.strip()))

    if not items:
        return {"signatures": []}

    # Construire la requête avec UNION ALL pour chaque paire
    queries = []
    params = {}
    for i, (da, art) in enumerate(items):
        params[f"da_{i}"] = da
        params[f"art_{i}"] = art
        queries.append(f"""
            SELECT TOP 1
                PSHNUM_0 AS numero_da,
                ITMREF_0 AS code_article,
                LINAPPFLG_0 AS flag_signature,
                CASE
                    WHEN LINAPPFLG_0 IN (0, 4) THEN 'Pas de gestion'
                    WHEN LINAPPFLG_0 = 1 THEN 'Non'
                    WHEN LINAPPFLG_0 = 2 THEN 'Partiellement'
                    WHEN LINAPPFLG_0 IN (3, 5) THEN 'Oui'
                    ELSE 'Inconnu'
                END AS statut_signature
            FROM x3.BASE1.PREQUISD
            WHERE PSHNUM_0 = :da_{i} AND ITMREF_0 = :art_{i}
        """)

    full_query = " UNION ALL ".join(queries)
    results = execute_x3_query(full_query, params)

    return {"signatures": results or []}
