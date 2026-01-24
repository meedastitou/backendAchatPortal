"""
════════════════════════════════════════════════════════════
ROUTER - Dashboard & Statistiques
════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, Depends
from typing import Optional

from app.auth.dependencies import get_current_user
from app.database import execute_query
from app.schemas.dashboard import (
    DashboardStats,
    DashboardStatsDetailed,
    RecentActivity,
    RecentActivitiesResponse,
    RFQStatusChart,
    TopFournisseur,
    TopFournisseursResponse,
    AlertItem,
    AlertsResponse,
    RecentReponse,
    RecentReponsesResponse,
    ReponseDetailItem
)


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ──────────────────────────────────────────────────────────
# Statistiques principales
# ──────────────────────────────────────────────────────────

@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(current_user: dict = Depends(get_current_user)):
    """Obtenir les statistiques principales du dashboard"""

    # Utiliser la vue si elle existe, sinon requêtes individuelles
    stats = execute_query("SELECT * FROM vue_stats_dashboard", fetch_one=True)

    if stats:
        # sanitize None values coming from the view (coerce to 0)
        for k, v in stats.items():
            if v is None:
                stats[k] = 0
        return DashboardStats(**stats)

    # Fallback: requêtes individuelles
    queries = {
        "total_da_actives": "SELECT COUNT(*) as c FROM demandes_achat WHERE statut != 'annule'",
        "rfq_en_attente": "SELECT COUNT(*) as c FROM demandes_cotation WHERE statut IN ('envoye', 'relance_1', 'relance_2', 'relance_3')",
        "rfq_repondues": "SELECT COUNT(*) as c FROM demandes_cotation WHERE statut = 'repondu'",
        "rfq_rejetees": "SELECT COUNT(*) as c FROM demandes_cotation WHERE statut = 'rejete'",
        "fournisseurs_actifs": "SELECT COUNT(*) as c FROM fournisseurs WHERE statut = 'actif' AND blacklist = FALSE",
        "fournisseurs_blacklistes": "SELECT COUNT(*) as c FROM fournisseurs WHERE blacklist = TRUE",
        "commandes_en_cours": "SELECT COUNT(*) as c FROM commandes WHERE statut IN ('validee', 'envoyee')",
        "taux_reponse_moyen": "SELECT COALESCE(ROUND(AVG(taux_reponse), 2), 0) as c FROM fournisseurs WHERE nb_total_rfq > 0"
    }

    result = {}
    for key, query in queries.items():
        row = execute_query(query, fetch_one=True)
        # ensure we never pass None to the pydantic model
        result[key] = row["c"] if (row and row.get("c") is not None) else 0

    return DashboardStats(**result)


# ──────────────────────────────────────────────────────────
# Statistiques détaillées
# ──────────────────────────────────────────────────────────

@router.get("/stats/detailed", response_model=DashboardStatsDetailed)
async def get_detailed_stats(current_user: dict = Depends(get_current_user)):
    """Obtenir les statistiques détaillées"""

    # Stats de base
    base_stats = await get_dashboard_stats(current_user)

    # Stats supplémentaires
    total_rfq = execute_query(
        "SELECT COUNT(*) as c FROM demandes_cotation",
        fetch_one=True
    )

    total_commandes = execute_query(
        "SELECT COUNT(*) as c FROM commandes",
        fetch_one=True
    )

    montant_commandes = execute_query(
        "SELECT COALESCE(SUM(montant_total_ht), 0) as c FROM commandes WHERE statut != 'annulee'",
        fetch_one=True
    )

    delai_moyen = execute_query(
        """SELECT COALESCE(AVG(TIMESTAMPDIFF(HOUR, date_envoi, date_reponse)), 0) as c
           FROM demandes_cotation WHERE date_reponse IS NOT NULL""",
        fetch_one=True
    )

    return DashboardStatsDetailed(
        **base_stats.model_dump(),
        total_rfq_envoyees=total_rfq["c"] if total_rfq else 0,
        total_commandes=total_commandes["c"] if total_commandes else 0,
        montant_total_commandes=float(montant_commandes["c"]) if montant_commandes else 0,
        delai_moyen_reponse_heures=float(delai_moyen["c"]) if delai_moyen else 0
    )


# ──────────────────────────────────────────────────────────
# Répartition des statuts RFQ
# ──────────────────────────────────────────────────────────

@router.get("/rfq-status", response_model=RFQStatusChart)
async def get_rfq_status_chart(current_user: dict = Depends(get_current_user)):
    """Obtenir la répartition des statuts RFQ"""

    query = """
        SELECT statut, COUNT(*) as count
        FROM demandes_cotation
        GROUP BY statut
    """
    results = execute_query(query)

    chart_data = RFQStatusChart()
    for row in results:
        statut = row["statut"]
        count = row["count"]
        if hasattr(chart_data, statut):
            setattr(chart_data, statut, count)

    return chart_data


# ──────────────────────────────────────────────────────────
# Activité récente
# ──────────────────────────────────────────────────────────

@router.get("/recent-activity", response_model=RecentActivitiesResponse)
async def get_recent_activity(
    limit: int = 10,
    current_user: dict = Depends(get_current_user)
):
    """Obtenir l'activité récente"""

    # Combiner différentes sources d'activité
    query = """
        (SELECT
            dc.id,
            'rfq_envoyee' as type,
            CONCAT('RFQ ', dc.numero_rfq, ' envoyée à ', f.nom_fournisseur) as description,
            dc.date_envoi as date,
            JSON_OBJECT('numero_rfq', dc.numero_rfq, 'fournisseur', f.nom_fournisseur) as details
        FROM demandes_cotation dc
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        ORDER BY dc.date_envoi DESC
        LIMIT %s)

        UNION ALL

        (SELECT
            re.id,
            'reponse_recue' as type,
            CONCAT('Réponse reçue pour RFQ ', dc.numero_rfq) as description,
            re.date_reponse as date,
            JSON_OBJECT('numero_rfq', dc.numero_rfq, 'fournisseur', f.nom_fournisseur) as details
        FROM reponses_fournisseurs_entete re
        JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        ORDER BY re.date_reponse DESC
        LIMIT %s)

        ORDER BY date DESC
        LIMIT %s
    """

    results = execute_query(query, (limit, limit, limit))

    activities = []
    for row in results:
        activities.append(RecentActivity(
            id=row["id"],
            type=row["type"],
            description=row["description"],
            date=row["date"],
            details=row["details"] if isinstance(row["details"], dict) else None
        ))

    return RecentActivitiesResponse(
        activities=activities,
        total=len(activities)
    )


# ──────────────────────────────────────────────────────────
# Top Fournisseurs
# ──────────────────────────────────────────────────────────

@router.get("/top-fournisseurs", response_model=TopFournisseursResponse)
async def get_top_fournisseurs(
    limit: int = 5,
    current_user: dict = Depends(get_current_user)
):
    """Obtenir les meilleurs fournisseurs"""

    query = """
        SELECT
            code_fournisseur,
            nom_fournisseur,
            taux_reponse,
            note_performance,
            nb_reponses
        FROM fournisseurs
        WHERE statut = 'actif'
          AND blacklist = FALSE
          AND nb_total_rfq > 0
        ORDER BY note_performance DESC, taux_reponse DESC
        LIMIT %s
    """

    results = execute_query(query, (limit,))

    fournisseurs = [TopFournisseur(**row) for row in results]

    return TopFournisseursResponse(fournisseurs=fournisseurs)


# ──────────────────────────────────────────────────────────
# Alertes
# ──────────────────────────────────────────────────────────

@router.get("/alerts", response_model=AlertsResponse)
async def get_alerts(
    limit: int = 10,
    current_user: dict = Depends(get_current_user)
):
    """Obtenir les alertes du dashboard"""

    alerts = []

    # RFQ sans réponse depuis longtemps
    old_rfq = execute_query("""
        SELECT dc.id, dc.numero_rfq, f.nom_fournisseur, dc.date_envoi,
               DATEDIFF(NOW(), dc.date_envoi) as jours
        FROM demandes_cotation dc
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE dc.statut IN ('envoye', 'relance_1', 'relance_2', 'relance_3')
          AND dc.date_reponse IS NULL
          AND DATEDIFF(NOW(), dc.date_envoi) > 7
        ORDER BY dc.date_envoi ASC
        LIMIT 5
    """)

    for rfq in old_rfq:
        alerts.append(AlertItem(
            id=rfq["id"],
            type="warning",
            titre="RFQ en attente",
            message=f"RFQ {rfq['numero_rfq']} envoyée à {rfq['nom_fournisseur']} depuis {rfq['jours']} jours sans réponse",
            date=rfq["date_envoi"],
            lien=f"/rfq/{rfq['id']}"
        ))

    # Fournisseurs avec faible taux de réponse
    low_response = execute_query("""
        SELECT id, code_fournisseur, nom_fournisseur, taux_reponse, updated_at
        FROM fournisseurs
        WHERE statut = 'actif'
          AND nb_total_rfq >= 5
          AND taux_reponse < 30
        ORDER BY taux_reponse ASC
        LIMIT 3
    """)

    for f in low_response:
        alerts.append(AlertItem(
            id=f["id"],
            type="info",
            titre="Faible taux de réponse",
            message=f"Fournisseur {f['nom_fournisseur']} a un taux de réponse de {f['taux_reponse']}%",
            date=f["updated_at"],
            lien=f"/fournisseurs/{f['code_fournisseur']}"
        ))

    return AlertsResponse(
        alerts=alerts[:limit],
        total=len(alerts)
    )


# ──────────────────────────────────────────────────────────
# Dernières réponses fournisseurs
# ──────────────────────────────────────────────────────────

@router.get("/recent-reponses", response_model=RecentReponsesResponse)
async def get_recent_reponses(
    limit: int = 10,
    current_user: dict = Depends(get_current_user)
):
    """Obtenir les dernières réponses fournisseurs avec détails"""

    # Récupérer les dernières réponses
    query = """
        SELECT
            re.id,
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur,
            re.date_reponse,
            re.devise,
            re.methodes_paiement,
            re.rfq_uuid,
            (SELECT COUNT(*) FROM reponses_fournisseurs_detail rd WHERE rd.reponse_entete_id = re.id) as nb_articles,
            (SELECT COALESCE(SUM(rd.prix_unitaire_ht * lc.quantite_demandee), 0)
             FROM reponses_fournisseurs_detail rd
             JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
             WHERE rd.reponse_entete_id = re.id) as montant_total_ht
        FROM reponses_fournisseurs_entete re
        JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        ORDER BY re.date_reponse DESC
        LIMIT %s
    """

    entetes = execute_query(query, (limit,))

    reponses = []
    for entete in entetes:
        # Récupérer les détails des articles
        details_query = """
            SELECT
                rd.code_article,
                lc.designation_article as designation,
                rd.prix_unitaire_ht,
                lc.quantite_demandee
            FROM reponses_fournisseurs_detail rd
            JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
            WHERE rd.reponse_entete_id = %s
            ORDER BY rd.code_article
        """
        details = execute_query(details_query, (entete["id"],))

        articles = [
            ReponseDetailItem(
                code_article=d["code_article"],
                designation=d["designation"],
                prix_unitaire_ht=float(d["prix_unitaire_ht"]) if d["prix_unitaire_ht"] else None,
                quantite_demandee=float(d["quantite_demandee"]) if d["quantite_demandee"] else None,
                devise=entete["devise"] or "MAD"
            )
            for d in details
        ]

        reponses.append(RecentReponse(
            id=entete["id"],
            numero_rfq=entete["numero_rfq"],
            code_fournisseur=entete["code_fournisseur"],
            nom_fournisseur=entete["nom_fournisseur"],
            date_reponse=entete["date_reponse"],
            nb_articles=entete["nb_articles"] or 0,
            montant_total_ht=float(entete["montant_total_ht"]) if entete["montant_total_ht"] else None,
            devise=entete["devise"] or "MAD",
            methodes_paiement=entete.get("methodes_paiement"),
            articles=articles
        ))

    return RecentReponsesResponse(
        reponses=reponses,
        total=len(reponses)
    )
