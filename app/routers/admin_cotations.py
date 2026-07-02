"""
════════════════════════════════════════════════════════════
ROUTER - Admin Gestion Lignes Cotation
════════════════════════════════════════════════════════════
Permet aux admins de désactiver/réactiver des lignes de cotation
(soft delete avec audit trail)
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional

from app.auth.dependencies import get_admin_user
from app.database import execute_query, execute_update
from app.schemas.admin_cotation import (
    LigneCotationAdmin,
    LigneCotationListResponse,
    DesactiverLigneRequest,
    DesactiverLigneResponse,
    ReactiverLigneResponse,
    StatsLignesCotation
)


router = APIRouter(prefix="/admin/cotations", tags=["Admin - Cotations"])


# ──────────────────────────────────────────────────────────
# Statistiques
# ──────────────────────────────────────────────────────────

@router.get("/stats", response_model=StatsLignesCotation)
async def get_stats(current_user: dict = Depends(get_admin_user)):
    """Obtenir les statistiques des lignes de cotation"""

    stats = execute_query("""
        SELECT
            COUNT(*) as total_lignes,
            SUM(CASE WHEN actif = TRUE OR actif IS NULL THEN 1 ELSE 0 END) as lignes_actives,
            SUM(CASE WHEN actif = FALSE THEN 1 ELSE 0 END) as lignes_desactivees,
            COUNT(DISTINCT numero_da) as total_das,
            COUNT(DISTINCT code_article) as total_articles
        FROM lignes_cotation
    """, fetch_one=True)

    return StatsLignesCotation(
        total_lignes=stats["total_lignes"] or 0,
        lignes_actives=stats["lignes_actives"] or 0,
        lignes_desactivees=stats["lignes_desactivees"] or 0,
        total_das=stats["total_das"] or 0,
        total_articles=stats["total_articles"] or 0
    )


# ──────────────────────────────────────────────────────────
# Liste des lignes de cotation
# ──────────────────────────────────────────────────────────

@router.get("", response_model=LigneCotationListResponse)
async def list_lignes_cotation(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    numero_da: Optional[str] = None,
    code_article: Optional[str] = None,
    actif: Optional[bool] = None,
    search: Optional[str] = None,
    current_user: dict = Depends(get_admin_user)
):
    """Lister les lignes de cotation avec filtres"""

    # Construction de la requête
    conditions = ["1=1"]
    params = []

    if numero_da:
        conditions.append("lc.numero_da = %s")
        params.append(numero_da)

    if code_article:
        conditions.append("lc.code_article = %s")
        params.append(code_article)

    if actif is not None:
        if actif:
            conditions.append("(lc.actif = TRUE OR lc.actif IS NULL)")
        else:
            conditions.append("lc.actif = FALSE")

    if search:
        conditions.append("""
            (lc.numero_da LIKE %s
            OR lc.code_article LIKE %s
            OR lc.designation_article LIKE %s
            OR dc.numero_rfq LIKE %s)
        """)
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

    where_clause = " AND ".join(conditions)

    # Count total
    count_query = f"""
        SELECT COUNT(*) as total
        FROM lignes_cotation lc
        JOIN demandes_cotation dc ON lc.rfq_uuid = dc.uuid
        WHERE {where_clause}
    """
    total = execute_query(count_query, tuple(params), fetch_one=True)["total"]

    # Get page avec jointures
    offset = (page - 1) * limit
    query = f"""
        SELECT
            lc.*,
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur,
            (
                SELECT COUNT(*)
                FROM reponses_fournisseurs_detail rd
                WHERE rd.ligne_cotation_id = lc.id
            ) as nb_reponses
        FROM lignes_cotation lc
        JOIN demandes_cotation dc ON lc.rfq_uuid = dc.uuid
        LEFT JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE {where_clause}
        ORDER BY lc.numero_da ASC, lc.code_article ASC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    lignes = execute_query(query, tuple(params))

    return LigneCotationListResponse(
        lignes=[LigneCotationAdmin(
            id=l["id"],
            rfq_uuid=l["rfq_uuid"],
            numero_rfq=l["numero_rfq"],
            numero_da=l["numero_da"],
            code_article=l["code_article"],
            designation_article=l["designation_article"],
            quantite_demandee=float(l["quantite_demandee"]),
            unite=l["unite"],
            marque_souhaitee=l.get("marque_souhaitee"),
            created_at=l["created_at"],
            actif=l["actif"] if l["actif"] is not None else True,
            motif_desactivation=l.get("motif_desactivation"),
            date_desactivation=l.get("date_desactivation"),
            desactive_par=l.get("desactive_par"),
            code_fournisseur=l.get("code_fournisseur"),
            nom_fournisseur=l.get("nom_fournisseur"),
            nb_reponses=l.get("nb_reponses", 0)
        ) for l in lignes],
        total=total,
        page=page,
        limit=limit
    )


# ──────────────────────────────────────────────────────────
# Obtenir une ligne
# ──────────────────────────────────────────────────────────

def get_ligne_by_id(ligne_id: int) -> Optional[dict]:
    """Helper pour récupérer une ligne par ID"""
    query = """
        SELECT
            lc.*,
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur,
            (
                SELECT COUNT(*)
                FROM reponses_fournisseurs_detail rd
                WHERE rd.ligne_cotation_id = lc.id
            ) as nb_reponses
        FROM lignes_cotation lc
        JOIN demandes_cotation dc ON lc.rfq_uuid = dc.uuid
        LEFT JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE lc.id = %s
    """
    return execute_query(query, (ligne_id,), fetch_one=True)


@router.get("/{ligne_id}", response_model=LigneCotationAdmin)
async def get_ligne(
    ligne_id: int,
    current_user: dict = Depends(get_admin_user)
):
    """Obtenir une ligne de cotation par ID"""

    ligne = get_ligne_by_id(ligne_id)

    if not ligne:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ligne de cotation non trouvée"
        )

    return LigneCotationAdmin(
        id=ligne["id"],
        rfq_uuid=ligne["rfq_uuid"],
        numero_rfq=ligne["numero_rfq"],
        numero_da=ligne["numero_da"],
        code_article=ligne["code_article"],
        designation_article=ligne["designation_article"],
        quantite_demandee=float(ligne["quantite_demandee"]),
        unite=ligne["unite"],
        marque_souhaitee=ligne.get("marque_souhaitee"),
        created_at=ligne["created_at"],
        actif=ligne["actif"] if ligne["actif"] is not None else True,
        motif_desactivation=ligne.get("motif_desactivation"),
        date_desactivation=ligne.get("date_desactivation"),
        desactive_par=ligne.get("desactive_par"),
        code_fournisseur=ligne.get("code_fournisseur"),
        nom_fournisseur=ligne.get("nom_fournisseur"),
        nb_reponses=ligne.get("nb_reponses", 0)
    )


# ──────────────────────────────────────────────────────────
# Désactiver une ligne
# ──────────────────────────────────────────────────────────

@router.put("/{ligne_id}/desactiver", response_model=DesactiverLigneResponse)
async def desactiver_ligne(
    ligne_id: int,
    data: DesactiverLigneRequest,
    current_user: dict = Depends(get_admin_user)
):
    """Désactiver une ligne de cotation (soft delete)"""

    # Vérifier existence
    ligne = get_ligne_by_id(ligne_id)
    if not ligne:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ligne de cotation non trouvée"
        )

    # Vérifier si déjà désactivée
    if ligne.get("actif") == False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette ligne est déjà désactivée"
        )

    # Désactiver
    query = """
        UPDATE lignes_cotation
        SET actif = FALSE,
            motif_desactivation = %s,
            date_desactivation = NOW(),
            desactive_par = %s
        WHERE id = %s
    """
    execute_update(query, (data.motif, current_user["username"], ligne_id))

    # Récupérer la ligne mise à jour
    ligne_updated = get_ligne_by_id(ligne_id)

    return DesactiverLigneResponse(
        success=True,
        message=f"Ligne {ligne['code_article']} de la DA {ligne['numero_da']} désactivée",
        ligne=LigneCotationAdmin(
            id=ligne_updated["id"],
            rfq_uuid=ligne_updated["rfq_uuid"],
            numero_rfq=ligne_updated["numero_rfq"],
            numero_da=ligne_updated["numero_da"],
            code_article=ligne_updated["code_article"],
            designation_article=ligne_updated["designation_article"],
            quantite_demandee=float(ligne_updated["quantite_demandee"]),
            unite=ligne_updated["unite"],
            marque_souhaitee=ligne_updated.get("marque_souhaitee"),
            created_at=ligne_updated["created_at"],
            actif=False,
            motif_desactivation=ligne_updated.get("motif_desactivation"),
            date_desactivation=ligne_updated.get("date_desactivation"),
            desactive_par=ligne_updated.get("desactive_par"),
            code_fournisseur=ligne_updated.get("code_fournisseur"),
            nom_fournisseur=ligne_updated.get("nom_fournisseur"),
            nb_reponses=ligne_updated.get("nb_reponses", 0)
        )
    )


# ──────────────────────────────────────────────────────────
# Réactiver une ligne
# ──────────────────────────────────────────────────────────

@router.put("/{ligne_id}/reactiver", response_model=ReactiverLigneResponse)
async def reactiver_ligne(
    ligne_id: int,
    current_user: dict = Depends(get_admin_user)
):
    """Réactiver une ligne de cotation désactivée"""

    # Vérifier existence
    ligne = get_ligne_by_id(ligne_id)
    if not ligne:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ligne de cotation non trouvée"
        )

    # Vérifier si déjà active
    if ligne.get("actif") != False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette ligne est déjà active"
        )

    # Réactiver (garder l'historique du motif)
    query = """
        UPDATE lignes_cotation
        SET actif = TRUE
        WHERE id = %s
    """
    execute_update(query, (ligne_id,))

    # Récupérer la ligne mise à jour
    ligne_updated = get_ligne_by_id(ligne_id)

    return ReactiverLigneResponse(
        success=True,
        message=f"Ligne {ligne['code_article']} de la DA {ligne['numero_da']} réactivée",
        ligne=LigneCotationAdmin(
            id=ligne_updated["id"],
            rfq_uuid=ligne_updated["rfq_uuid"],
            numero_rfq=ligne_updated["numero_rfq"],
            numero_da=ligne_updated["numero_da"],
            code_article=ligne_updated["code_article"],
            designation_article=ligne_updated["designation_article"],
            quantite_demandee=float(ligne_updated["quantite_demandee"]),
            unite=ligne_updated["unite"],
            marque_souhaitee=ligne_updated.get("marque_souhaitee"),
            created_at=ligne_updated["created_at"],
            actif=True,
            motif_desactivation=ligne_updated.get("motif_desactivation"),
            date_desactivation=ligne_updated.get("date_desactivation"),
            desactive_par=ligne_updated.get("desactive_par"),
            code_fournisseur=ligne_updated.get("code_fournisseur"),
            nom_fournisseur=ligne_updated.get("nom_fournisseur"),
            nb_reponses=ligne_updated.get("nb_reponses", 0)
        )
    )


# ──────────────────────────────────────────────────────────
# Liste des DAs uniques
# ──────────────────────────────────────────────────────────

@router.get("/filters/das")
async def get_das_list(current_user: dict = Depends(get_admin_user)):
    """Obtenir la liste des DAs pour les filtres"""

    query = """
        SELECT DISTINCT numero_da
        FROM lignes_cotation
        ORDER BY numero_da ASC
    """
    das = execute_query(query)

    return {"das": [d["numero_da"] for d in das]}


# ──────────────────────────────────────────────────────────
# Liste des articles uniques
# ──────────────────────────────────────────────────────────

@router.get("/filters/articles")
async def get_articles_list(current_user: dict = Depends(get_admin_user)):
    """Obtenir la liste des articles pour les filtres"""

    query = """
        SELECT DISTINCT code_article, MAX(designation_article) as designation
        FROM lignes_cotation
        GROUP BY code_article
        ORDER BY code_article ASC
    """
    articles = execute_query(query)

    return {"articles": [{"code": a["code_article"], "designation": a["designation"]} for a in articles]}
