"""
════════════════════════════════════════════════════════════
ROUTER - Demandes de Cotation (RFQ)
════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from typing import Optional
from datetime import datetime, date
from io import BytesIO

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


# ──────────────────────────────────────────────────────────
# Export Excel - RFQ sans réponse
# ──────────────────────────────────────────────────────────

@router.get("/export/sans-reponse")
async def export_rfq_sans_reponse(
    date_debut: Optional[date] = None,
    date_fin: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Exporter les RFQ sans réponse en Excel.
    Statuts inclus: envoye, relance_1, relance_2, relance_3
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="Module openpyxl non installé. Exécutez: pip install openpyxl"
        )
    print("test===================")
    # Construire la requête
    conditions = ["dc.statut IN ('envoye', 'relance_1', 'relance_2', 'relance_3')"]
    params = []

    if date_debut:
        conditions.append("DATE(dc.date_envoi) >= %s")
        params.append(date_debut)

    if date_fin:
        conditions.append("DATE(dc.date_envoi) <= %s")
        params.append(date_fin)

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur,
            f.email as email_fournisseur,
            dc.date_envoi,
            dc.nb_relances,
            dc.date_derniere_relance,
            dc.uuid,
            DATEDIFF(NOW(), dc.date_envoi) as jours_depuis_envoi
        FROM demandes_cotation dc
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE {where_clause}
        ORDER BY dc.date_envoi DESC
    """

    rfqs = execute_query(query, tuple(params) if params else None)

    # Récupérer les articles pour chaque RFQ
    for rfq in rfqs:
        lignes = execute_query(
            "SELECT code_article, numero_da FROM lignes_cotation WHERE rfq_uuid = %s",
            (rfq["uuid"],)
        )
        rfq["articles"] = ", ".join([l["code_article"] for l in lignes])
        rfq["das"] = ", ".join(list(set([l["numero_da"] for l in lignes])))

    # Créer le workbook Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "RFQ Sans Réponse"

    # Styles
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2D5A87", end_color="2D5A87", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # En-têtes
    headers = [
        "N° RFQ",
        "Code Fournisseur",
        "Nom Fournisseur",
        "Email",
        "Date Envoi",
        "Nb Relances",
        "Dernière Relance",
        "Jours Depuis Envoi",
        "Articles",
        "N° DA"
    ]

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # Données
    for row_num, rfq in enumerate(rfqs, 2):
        data = [
            rfq["numero_rfq"],
            rfq["code_fournisseur"],
            rfq["nom_fournisseur"],
            rfq["email_fournisseur"],
            rfq["date_envoi"].strftime("%d/%m/%Y %H:%M") if rfq["date_envoi"] else "",
            rfq["nb_relances"],
            rfq["date_derniere_relance"].strftime("%d/%m/%Y") if rfq["date_derniere_relance"] else "",
            rfq["jours_depuis_envoi"],
            rfq["articles"],
            rfq["das"]
        ]

        for col, value in enumerate(data, 1):
            cell = ws.cell(row=row_num, column=col, value=value)
            cell.border = thin_border
            if col == 8 and value and value > 7:  # Jours depuis envoi > 7
                cell.font = Font(color="DC2626", bold=True)

    # Ajuster la largeur des colonnes
    column_widths = [15, 18, 30, 35, 18, 12, 18, 18, 40, 30]
    for col, width in enumerate(column_widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width

    # Figer la première ligne
    ws.freeze_panes = "A2"

    # Générer le fichier
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    # Nom du fichier
    date_str_debut = date_debut.strftime("%Y-%m-%d") if date_debut else "debut"
    date_str_fin = date_fin.strftime("%Y-%m-%d") if date_fin else "fin"
    filename = f"RFQ_sans_reponse_{date_str_debut}_{date_str_fin}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ──────────────────────────────────────────────────────────
# Export Excel - RFQ avec filtres
# ──────────────────────────────────────────────────────────

@router.get("/export/filtered")
async def export_rfq_filtered(
    statut: Optional[StatutRFQ] = None,
    code_fournisseur: Optional[str] = None,
    date_debut: Optional[date] = None,
    date_fin: Optional[date] = None,
    search: Optional[str] = None,
    code_article: Optional[str] = None,
    numero_da: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Exporter les RFQ en Excel selon les filtres appliqués.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="Module openpyxl non installé. Exécutez: pip install openpyxl"
        )

    # Construire la requête avec les mêmes filtres que list_rfq
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
        conditions.append("DATE(dc.date_envoi) >= %s")
        params.append(date_debut)

    if date_fin:
        conditions.append("DATE(dc.date_envoi) <= %s")
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

    query = f"""
        SELECT DISTINCT
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur,
            f.email as email_fournisseur,
            dc.date_envoi,
            dc.statut,
            dc.nb_relances,
            dc.date_derniere_relance,
            dc.date_reponse,
            dc.uuid,
            DATEDIFF(NOW(), dc.date_envoi) as jours_depuis_envoi
        FROM demandes_cotation dc
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        {lignes_join}
        WHERE {where_clause}
        ORDER BY dc.date_envoi DESC
    """

    rfqs = execute_query(query, tuple(params) if params else None)

    # Récupérer les articles pour chaque RFQ
    for rfq in rfqs:
        lignes = execute_query(
            "SELECT code_article, numero_da FROM lignes_cotation WHERE rfq_uuid = %s",
            (rfq["uuid"],)
        )
        rfq["articles"] = ", ".join([l["code_article"] for l in lignes])
        rfq["das"] = ", ".join(list(set([l["numero_da"] for l in lignes])))

    # Créer le workbook Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Export RFQ"

    # Styles
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2D5A87", end_color="2D5A87", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # En-têtes
    headers = [
        "N° RFQ",
        "Code Fournisseur",
        "Nom Fournisseur",
        "Email",
        "Date Envoi",
        "Statut",
        "Nb Relances",
        "Dernière Relance",
        "Date Réponse",
        "Jours Depuis Envoi",
        "Articles",
        "N° DA"
    ]

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # Mapping des statuts pour affichage
    statut_map = {
        'envoye': 'Envoyé',
        'vu': 'Vu',
        'repondu': 'Répondu',
        'rejete': 'Rejeté',
        'expire': 'Expiré',
        'relance_1': 'Relance 1',
        'relance_2': 'Relance 2',
        'relance_3': 'Relance 3'
    }

    # Données
    for row_num, rfq in enumerate(rfqs, 2):
        data = [
            rfq["numero_rfq"],
            rfq["code_fournisseur"],
            rfq["nom_fournisseur"],
            rfq["email_fournisseur"],
            rfq["date_envoi"].strftime("%d/%m/%Y %H:%M") if rfq["date_envoi"] else "",
            statut_map.get(rfq["statut"], rfq["statut"]),
            rfq["nb_relances"],
            rfq["date_derniere_relance"].strftime("%d/%m/%Y") if rfq["date_derniere_relance"] else "",
            rfq["date_reponse"].strftime("%d/%m/%Y %H:%M") if rfq["date_reponse"] else "",
            rfq["jours_depuis_envoi"],
            rfq["articles"],
            rfq["das"]
        ]

        for col, value in enumerate(data, 1):
            cell = ws.cell(row=row_num, column=col, value=value)
            cell.border = thin_border

            # Colorer selon le statut
            if col == 6:  # Colonne Statut
                if rfq["statut"] == "repondu":
                    cell.font = Font(color="059669", bold=True)
                elif rfq["statut"] == "rejete":
                    cell.font = Font(color="DC2626", bold=True)
                elif rfq["statut"] in ("relance_1", "relance_2", "relance_3"):
                    cell.font = Font(color="D97706", bold=True)

    # Ajuster la largeur des colonnes
    column_widths = [15, 18, 30, 35, 18, 12, 12, 18, 18, 15, 40, 30]
    for col, width in enumerate(column_widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width

    # Figer la première ligne
    ws.freeze_panes = "A2"

    # Générer le fichier
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    # Nom du fichier
    from datetime import datetime as dt
    filename = f"Export_RFQ_{dt.now().strftime('%Y-%m-%d_%H%M%S')}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
