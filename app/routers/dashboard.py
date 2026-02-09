"""
════════════════════════════════════════════════════════════
ROUTER - Dashboard & Statistiques
════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.auth.dependencies import get_current_user, get_user_famille_filter
from app.database import execute_query, get_db
from app.models.demandes_achat import DemandeAchat
from app.models.demandes_cotation import DemandeCotation
from app.models.fournisseurs import Fournisseur
from app.models.commandes import Commande
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
async def get_dashboard_stats(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Obtenir les statistiques principales du dashboard"""

    # Filtrage par famille pour les acheteurs
    familles_filter = get_user_famille_filter(current_user)

    if familles_filter is not None and len(familles_filter) == 0:
        # Acheteur sans famille = tout à zéro
        return DashboardStats(
            total_da_actives=0,
            rfq_en_attente=0,
            rfq_repondues=0,
            rfq_rejetees=0,
            fournisseurs_actifs=0,
            fournisseurs_blacklistes=0,
            commandes_en_cours=0,
            taux_reponse_moyen=0
        )

    if familles_filter is not None:
        # Acheteur avec familles - utiliser SQL brut pour filtrer
        placeholders = ", ".join(["%s"] * len(familles_filter))
        famille_join = f"""
            JOIN lignes_cotation lc ON dc.uuid = lc.rfq_uuid
            JOIN articles_ref ar ON lc.code_article = ar.code_article
            AND ar.code_famille IN ({placeholders})
        """

        # DA actives filtrées par famille
        da_query = f"""
            SELECT COUNT(DISTINCT da.id) as total
            FROM demandes_achat da
            JOIN articles_ref ar ON da.code_article = ar.code_article
            WHERE da.statut != 'annule' AND ar.code_famille IN ({placeholders})
        """
        total_da_actives = execute_query(da_query, tuple(familles_filter), fetch_one=True)["total"]

        # RFQ filtrées
        rfq_attente_query = f"""
            SELECT COUNT(DISTINCT dc.id) as total
            FROM demandes_cotation dc
            {famille_join}
            WHERE dc.statut IN ('envoye', 'relance_1', 'relance_2', 'relance_3')
        """
        rfq_en_attente = execute_query(rfq_attente_query, tuple(familles_filter), fetch_one=True)["total"]

        rfq_repondues_query = f"""
            SELECT COUNT(DISTINCT dc.id) as total
            FROM demandes_cotation dc
            {famille_join}
            WHERE dc.statut = 'repondu'
        """
        rfq_repondues = execute_query(rfq_repondues_query, tuple(familles_filter), fetch_one=True)["total"]

        rfq_rejetees_query = f"""
            SELECT COUNT(DISTINCT dc.id) as total
            FROM demandes_cotation dc
            {famille_join}
            WHERE dc.statut = 'rejete'
        """
        rfq_rejetees = execute_query(rfq_rejetees_query, tuple(familles_filter), fetch_one=True)["total"]

        # Commandes filtrées par famille
        commandes_query = f"""
            SELECT COUNT(DISTINCT c.id) as total
            FROM bons_commande c
            JOIN lignes_bon_commande lbc ON c.id = lbc.bon_commande_id
            JOIN articles_ref ar ON lbc.code_article = ar.code_article
            WHERE c.statut IN ('validee', 'envoyee') AND ar.code_famille IN ({placeholders})
        """
        commandes_en_cours = execute_query(commandes_query, tuple(familles_filter), fetch_one=True)["total"]

    else:
        # Admin/Responsable - requêtes normales via ORM
        total_da_actives = db.query(func.count(DemandeAchat.id)).filter(
            DemandeAchat.statut != 'annule'
        ).scalar() or 0

        rfq_en_attente = db.query(func.count(DemandeCotation.id)).filter(
            DemandeCotation.statut.in_(['envoye', 'relance_1', 'relance_2', 'relance_3'])
        ).scalar() or 0

        rfq_repondues = db.query(func.count(DemandeCotation.id)).filter(
            DemandeCotation.statut == 'repondu'
        ).scalar() or 0

        rfq_rejetees = db.query(func.count(DemandeCotation.id)).filter(
            DemandeCotation.statut == 'rejete'
        ).scalar() or 0

        commandes_en_cours = db.query(func.count(Commande.id)).filter(
            Commande.statut.in_(['validee', 'envoyee'])
        ).scalar() or 0

    # Fournisseurs (pas filtrés par famille - info globale)
    fournisseurs_actifs = db.query(func.count(Fournisseur.id)).filter(
        (Fournisseur.statut == 'actif') & (Fournisseur.blacklist == False)
    ).scalar() or 0

    fournisseurs_blacklistes = db.query(func.count(Fournisseur.id)).filter(
        Fournisseur.blacklist == True
    ).scalar() or 0

    # Taux de réponse moyen des fournisseurs
    taux_reponse_moyen = db.query(func.avg(Fournisseur.taux_reponse)).filter(
        Fournisseur.nb_total_rfq > 0
    ).scalar() or 0
    taux_reponse_moyen = round(float(taux_reponse_moyen), 2) if taux_reponse_moyen else 0

    return DashboardStats(
        total_da_actives=int(total_da_actives),
        rfq_en_attente=int(rfq_en_attente),
        rfq_repondues=int(rfq_repondues),
        rfq_rejetees=int(rfq_rejetees),
        fournisseurs_actifs=int(fournisseurs_actifs),
        fournisseurs_blacklistes=int(fournisseurs_blacklistes),
        commandes_en_cours=int(commandes_en_cours),
        taux_reponse_moyen=taux_reponse_moyen
    )


# ──────────────────────────────────────────────────────────
# Statistiques du jour (aujourd'hui)
# ──────────────────────────────────────────────────────────

@router.get("/stats/today")
async def get_today_stats(
    filter_date: Optional[date] = Query(None, description="Date de filtre (format: YYYY-MM-DD). Si non fournie, utilise la date du jour."),
    current_user: dict = Depends(get_current_user)
):
    """Obtenir les statistiques d'une journee specifique (par defaut aujourd'hui)"""

    # Utiliser la date fournie ou la date du jour
    if filter_date:
        date_str = filter_date.strftime('%Y-%m-%d')
        date_condition = f"= '{date_str}'"
    else:
        date_condition = "= CURDATE()"

    # RFQ envoyées ce jour
    rfq_envoyees = execute_query(
        f"SELECT COUNT(*) as c FROM demandes_cotation WHERE DATE(date_envoi) {date_condition}",
        fetch_one=True
    )

    # Réponses reçues ce jour
    reponses_recues = execute_query(
        f"SELECT COUNT(*) as c FROM reponses_fournisseurs_entete WHERE DATE(date_reponse) {date_condition}",
        fetch_one=True
    )

    # Rejets reçus ce jour
    rejets_recus = execute_query(
        f"SELECT COUNT(*) as c FROM rejets_fournisseurs WHERE DATE(date_rejet) {date_condition}",
        fetch_one=True
    )

    # Commandes créées ce jour
    commandes_creees = execute_query(
        f"SELECT COUNT(*) as c FROM bons_commande WHERE DATE(date_creation) {date_condition}",
        fetch_one=True
    )

    # Montant total des réponses de ce jour
    # montant_reponses = execute_query(
    #     f"""
    #     SELECT COALESCE(SUM(rd.prix_unitaire_ht * lc.quantite_demandee), 0) as c
    #     FROM reponses_fournisseurs_detail rd
    #     JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
    #     JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
    #     WHERE DATE(re.date_reponse) {date_condition}
    #     """,
    #     fetch_one=True
    # )

    # Nouveaux fournisseurs ajoutés ce jour
    nouveaux_fournisseurs = execute_query(
        f"SELECT COUNT(*) as c FROM fournisseurs WHERE DATE(created_at) {date_condition}",
        fetch_one=True
    )

    # Articles cotés ce jour (nombre d'articles uniques dans les réponses)
    articles_cotes = execute_query(
        f"""
        SELECT COUNT(DISTINCT rd.code_article) as c
        FROM reponses_fournisseurs_detail rd
        JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        WHERE DATE(re.date_reponse) {date_condition}
        """,
        fetch_one=True
    )

    # Récupérer la date utilisée
    if filter_date:
        result_date = date_str
    else:
        result_date = str(execute_query("SELECT CURDATE() as d", fetch_one=True)["d"])

    return {
        "date": result_date,
        "rfq_envoyees": rfq_envoyees["c"] if rfq_envoyees else 0,
        "reponses_recues": reponses_recues["c"] if reponses_recues else 0,
        "rejets_recus": rejets_recus["c"] if rejets_recus else 0,
        "commandes_creees": commandes_creees["c"] if commandes_creees else 0,
        # "montant_reponses": float(montant_reponses["c"]) if montant_reponses else 0,
        "nouveaux_fournisseurs": nouveaux_fournisseurs["c"] if nouveaux_fournisseurs else 0,
        "articles_cotes": articles_cotes["c"] if articles_cotes else 0
    }


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
