"""
════════════════════════════════════════════════════════════
ROUTER - Analyse des blocages BC
════════════════════════════════════════════════════════════
Dashboard d'analyse pour comprendre pourquoi les BC ne sont pas créés
Toutes les analyses partent des DA NON SOLDÉES depuis Sage X3
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional, List, Dict, Set
import logging

from app.auth.dependencies import get_current_user
from app.database import execute_query
from app.sqlserver_db import execute_x3_query
from app.schemas.analyse import (
    FunnelStats,
    BlocageStats,
    AnalyseDashboardResponse,
    ArticleNonSigne,
    ArticleNonSigneListResponse,
    ArticlePrixSuperieur,
    ArticlePrixSuperieurListResponse,
    ArticleMarqueDifferente,
    ArticleMarqueDifferenteListResponse,
    ArticleMarqueInexistante,
    ArticleMarqueInexistanteListResponse,
    ArticlePrixOkMarqueInex,
    ArticlePrixOkMarqueInexListResponse,
    ArticleSansReponse,
    ArticleSansReponseListResponse
)


router = APIRouter(prefix="/analyse", tags=["Analyse Blocages"])


# ──────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────

# Familles et articles à exclure
# FAMILLES_EXCLUES = ["R.H", "ELECTRICITE"]
# ARTICLES_EXCLUS = ["A09985", "A10107", "A10136"]

FAMILLES_EXCLUES = []
ARTICLES_EXCLUS = []


def get_libelle_signature(niveau: int) -> str:
    """Convertir le niveau de signature en libellé"""
    if niveau == 3:
        return "Signé"
    else:
        return "Non signé"


# ──────────────────────────────────────────────────────────
# Fonction principale: Récupérer les DA non soldées depuis X3
# ──────────────────────────────────────────────────────────

def get_da_non_soldees_x3(date_min: str = "20260101") -> List[Dict]:
    """
    Récupérer toutes les DA non soldées depuis Sage X3.
    C'est la source de vérité pour l'analyse.
    """
    try:
        # Construire les exclusions
        familles_exclus_str = ", ".join([f"'{f}'" for f in FAMILLES_EXCLUES])
        articles_exclus_str = ", ".join([f"'{a}'" for a in ARTICLES_EXCLUS])

        query = f"""
            SELECT
                DNS.DA AS numero_da,
                DNS.Article AS code_article,
                DNS.DésignationArticle AS designation_article,
                DNS.QteDA AS quantite,
                DAD.XMARQ_0 AS marque,
                DNS.STU_0 AS unite,
                DNS.Famille AS famille,
                DAD.LINAPPFLG_0 AS niveau_signature
            FROM x3.BASE1.Y_DA_NON_SOLDEES DNS
            LEFT JOIN x3.BASE1.PREQUIS DA ON DA.PSHNUM_0 = DNS.DA
            INNER JOIN x3.BASE1.PREQUISD DAD
                ON DAD.PSHNUM_0 = DA.PSHNUM_0 AND DAD.ITMREF_0 = DNS.Article
            WHERE DA.CLEFLG_0 = 1
            ORDER BY DNS.DA, DNS.Article
        """

        result = execute_x3_query(query, {})
        return result if result else []

    except Exception as e:
        logging.error(f"Erreur récupération DA non soldées X3: {e}")
        return []


def get_tarifs_x3() -> Dict[str, float]:
    """Récupérer les tarifs de référence depuis X3"""
    try:
        query = """
            /*SELECT
                ITMMASTER.ITMREF_0 AS code_article,
                PPRICLIST.PRI_0 AS tarif
            FROM BASE1.PPRICLIST PPRICLIST
            INNER JOIN BASE1.ITMMASTER ITMMASTER
                ON PPRICLIST.PLICRI1_0 = ITMMASTER.ITMREF_0
            WHERE PPRICLIST.PRI_0 > 0 */
            WITH CTE AS (
                SELECT 
                    PPRICLIST.PLICRI1_0 AS code_article,
                    PPRICLIST.PRI_0 AS tarif,
                    PPRICLIST.PLIENDDAT_0 AS date_fin,
                    ROW_NUMBER() OVER (
                        PARTITION BY PPRICLIST.PLICRI1_0
                        ORDER BY PPRICLIST.PLIENDDAT_0 DESC, PPRICLIST.PRI_0 DESC
                    ) AS rang
                FROM BASE1.PPRICLIST PPRICLIST
                --INNER JOIN BASE1.ITMMASTER ITMMASTER
                --  ON PPRICLIST.PLICRI1_0 = ITMMASTER.ITMREF_0
                WHERE PPRICLIST.PRI_0 > 0
            )
            SELECT code_article, tarif
            FROM CTE
            WHERE rang = 1;
        """
        
        result = execute_x3_query(query, {})
        if result:
            return {row['code_article'].strip(): float(row['tarif']) for row in result}
        return {}
    except Exception as e:
        logging.error(f"Erreur récupération tarifs X3: {e}")
        return {}


def get_marques_x3() -> Dict[str, List[str]]:
    """Récupérer les marques autorisées par article depuis X3"""
    try:
        query = """
            SELECT XART_0 AS code_article, XMARQ_0 AS marque
            FROM BASE1.XMRQART
            WHERE XMARQ_0 IS NOT NULL
        """
        result = execute_x3_query(query, {})

        marques = {}
        if result:
            for row in result:
                code = row['code_article'].strip() if row['code_article'] else ''
                marque = row['marque'].strip().upper() if row['marque'] else ''
                if code not in marques:
                    marques[code] = []
                if marque:
                    marques[code].append(marque)
        return marques
    except Exception as e:
        logging.error(f"Erreur récupération marques X3: {e}")
        return {}


# ──────────────────────────────────────────────────────────
# Dashboard principal
# ──────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=AnalyseDashboardResponse)
async def get_analyse_dashboard(current_user: dict = Depends(get_current_user)):
    """
    Dashboard principal d'analyse des blocages.
    Part des DA non soldées X3 et croise avec les données du portail.
    """
    # 1. Récupérer les DA non soldées depuis X3
    da_non_soldees = get_da_non_soldees_x3()
    da_set = {f"{d['numero_da']}|{d['code_article']}" for d in da_non_soldees}

    funnel = FunnelStats()
    funnel.total_da = len(da_non_soldees)

    if not da_non_soldees:
        return AnalyseDashboardResponse(
            funnel=funnel,
            blocages=BlocageStats(),
            derniere_sync_x3=None
        )

    # Extraire les numéros de DA uniques pour les requêtes MySQL
    numeros_da = list(set(d['numero_da'] for d in da_non_soldees))
    placeholders = ", ".join(["%s"] * len(numeros_da))

    # 2. DA avec RFQ envoyées (dans le portail)
    query_rfq = f"""
        SELECT DISTINCT CONCAT(lc.numero_da, '|', lc.code_article) as da_key
        FROM lignes_cotation lc
        INNER JOIN demandes_cotation dc ON lc.rfq_uuid = dc.uuid
        WHERE lc.numero_da IN ({placeholders}) AND lc.actif = TRUE
    """
    result = execute_query(query_rfq, tuple(numeros_da))
    rfq_set = {row['da_key'] for row in result} if result else set()
    funnel.da_avec_rfq = len(rfq_set & da_set)

    # 3. DA avec réponses
    query_reponses = f"""
        SELECT DISTINCT CONCAT(lc.numero_da, '|', lc.code_article) as da_key
        FROM lignes_cotation lc
        INNER JOIN reponses_fournisseurs_detail rd ON lc.id = rd.ligne_cotation_id
        WHERE lc.numero_da IN ({placeholders}) AND lc.actif = TRUE
    """
    result = execute_query(query_reponses, tuple(numeros_da))
    reponses_set = {row['da_key'] for row in result} if result else set()
    funnel.da_avec_reponses = len(reponses_set & da_set)

    # 4. DA avec sélections
    query_selections = f"""
        SELECT DISTINCT CONCAT(numero_da, '|', code_article) as da_key
        FROM selections_articles
        WHERE numero_da IN ({placeholders}) AND statut IN ('selectionne', 'en_attente_bc')
    """
    result = execute_query(query_selections, tuple(numeros_da))
    selections_set = {row['da_key'] for row in result} if result else set()
    funnel.da_avec_selections = len(selections_set & da_set)

    # 5. DA avec BC générés
    query_bc = f"""
        SELECT DISTINCT CONCAT(numero_da, '|', code_article) as da_key
        FROM selections_articles
        WHERE numero_da IN ({placeholders}) AND statut = 'bc_genere'
    """
    result = execute_query(query_bc, tuple(numeros_da))
    bc_set = {row['da_key'] for row in result} if result else set()
    funnel.da_avec_bc = len(bc_set & da_set)

    # Calculer les taux
    if funnel.total_da > 0:
        funnel.taux_rfq = round((funnel.da_avec_rfq / funnel.total_da) * 100, 1)
    if funnel.da_avec_rfq > 0:
        funnel.taux_reponses = round((funnel.da_avec_reponses / funnel.da_avec_rfq) * 100, 1)
    if funnel.da_avec_reponses > 0:
        funnel.taux_selections = round((funnel.da_avec_selections / funnel.da_avec_reponses) * 100, 1)
    if funnel.da_avec_selections > 0:
        funnel.taux_bc = round((funnel.da_avec_bc / funnel.da_avec_selections) * 100, 1)

    # 6. Statistiques des blocages
    blocages = BlocageStats()
    blocages.total_da_non_soldees = funnel.total_da

    # Non signées (niveau_signature != 3)
    blocages.nb_non_signees = sum(1 for d in da_non_soldees if d.get('niveau_signature') != 3)

    # Prix > Tarif
    tarifs = get_tarifs_x3()
    query_prix = f"""
        SELECT lc.code_article, rd.prix_unitaire_ht
        FROM reponses_fournisseurs_detail rd
        INNER JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        WHERE lc.numero_da IN ({placeholders})
          AND lc.actif = TRUE
          AND rd.prix_unitaire_ht IS NOT NULL
    """
    result = execute_query(query_prix, tuple(numeros_da))

    count_prix_sup = 0
    ecart_total = 0.0
    if result:
        for row in result:
            code = row['code_article'].strip() if row['code_article'] else ''
            tarif = tarifs.get(code)
            prix = float(row['prix_unitaire_ht']) if row['prix_unitaire_ht'] else 0
            if tarif and prix > tarif:
                count_prix_sup += 1
                ecart_total += prix - tarif

    blocages.nb_prix_superieur_tarif = count_prix_sup
    blocages.montant_ecart_prix_total = round(ecart_total, 2)

    # Marques différentes
    query_marques = f"""
        SELECT COUNT(DISTINCT rd.id) as total
        FROM reponses_fournisseurs_detail rd
        INNER JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        WHERE lc.numero_da IN ({placeholders})
          AND lc.actif = TRUE
          AND lc.marque_souhaitee IS NOT NULL AND lc.marque_souhaitee != ''
          AND rd.marque_proposee IS NOT NULL AND rd.marque_proposee != ''
          AND UPPER(TRIM(lc.marque_souhaitee)) != UPPER(TRIM(rd.marque_proposee))
    """
    result = execute_query(query_marques, tuple(numeros_da))
    blocages.nb_marque_differente = result[0]['total'] if result else 0

    # Marques inexistantes dans X3
    marques_x3 = get_marques_x3()
    query_marques_prop = f"""
        SELECT lc.code_article, rd.marque_proposee
        FROM reponses_fournisseurs_detail rd
        INNER JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        WHERE lc.numero_da IN ({placeholders})
          AND lc.actif = TRUE
          AND rd.marque_proposee IS NOT NULL AND rd.marque_proposee != ''
    """
    result = execute_query(query_marques_prop, tuple(numeros_da))
    count_inexistante = 0
    if result:
        for row in result:
            code = row['code_article'].strip() if row['code_article'] else ''
            marque_prop = (row['marque_proposee'] or '').strip().upper()
            marques_valides = marques_x3.get(code, [])
            if marque_prop and marque_prop not in marques_valides:
                count_inexistante += 1
    blocages.nb_marque_inexistante = count_inexistante

    # Prix OK mais marque inexistante dans X3
    query_prix_marque = f"""
        SELECT lc.code_article, rd.prix_unitaire_ht, rd.marque_proposee
        FROM reponses_fournisseurs_detail rd
        INNER JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        WHERE lc.numero_da IN ({placeholders})
          AND lc.actif = TRUE
          AND rd.prix_unitaire_ht IS NOT NULL
          AND rd.marque_proposee IS NOT NULL AND rd.marque_proposee != ''
    """
    result = execute_query(query_prix_marque, tuple(numeros_da))
    count_prix_ok_marque_inex = 0
    if result:
        for row in result:
            code = row['code_article'].strip() if row['code_article'] else ''
            tarif = tarifs.get(code)
            prix = float(row['prix_unitaire_ht']) if row['prix_unitaire_ht'] else 0
            marque_prop = (row['marque_proposee'] or '').strip().upper()
            marques_valides = marques_x3.get(code, [])
            # Prix OK (<=tarif) ET marque inexistante
            if tarif and prix <= tarif and marque_prop and marque_prop not in marques_valides:
                count_prix_ok_marque_inex += 1
    blocages.nb_prix_ok_marque_inexistante = count_prix_ok_marque_inex

    # Sans réponse (RFQ envoyée mais pas de réponse)
    sans_reponse = rfq_set - reponses_set
    blocages.nb_sans_reponse = len(sans_reponse & da_set)

    # Dernière sync
    query_sync = "SELECT MAX(x3_derniere_sync) as derniere FROM demandes_achat"
    result = execute_query(query_sync)
    derniere_sync = result[0]['derniere'] if result else None

    return AnalyseDashboardResponse(
        funnel=funnel,
        blocages=blocages,
        derniere_sync_x3=derniere_sync
    )


# ──────────────────────────────────────────────────────────
# Liste: Articles non signés
# ──────────────────────────────────────────────────────────

@router.get("/blocages/non-signes", response_model=ArticleNonSigneListResponse)
async def get_articles_non_signes(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    numero_da: Optional[str] = Query(default=None),
    code_article: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user)
):
    """Liste des articles sur DA non signées (niveau_signature != 3)"""

    # Récupérer DA non soldées depuis X3
    da_non_soldees = get_da_non_soldees_x3()

    # Filtrer les non signées (signé = 3)
    articles_non_signes = [
        d for d in da_non_soldees
        if d.get('niveau_signature') != 3
    ]

    # Appliquer les filtres
    if numero_da:
        articles_non_signes = [a for a in articles_non_signes if numero_da.lower() in a['numero_da'].lower()]
    if code_article:
        articles_non_signes = [a for a in articles_non_signes if code_article.lower() in a['code_article'].lower()]

    total = len(articles_non_signes)

    # Pagination
    offset = (page - 1) * limit
    articles_page = articles_non_signes[offset:offset + limit]

    # Récupérer les infos de réponses depuis MySQL
    numeros_da = list(set(a['numero_da'] for a in articles_page))
    reponses_info = {}

    if numeros_da:
        placeholders = ", ".join(["%s"] * len(numeros_da))
        query = f"""
            SELECT
                CONCAT(lc.numero_da, '|', lc.code_article) as da_key,
                COUNT(rd.id) as nb_reponses,
                MIN(rd.prix_unitaire_ht) as meilleur_prix,
                (SELECT f.nom_fournisseur
                 FROM reponses_fournisseurs_detail rd2
                 INNER JOIN reponses_fournisseurs_entete re ON rd2.reponse_entete_id = re.id
                 INNER JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
                 LEFT JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
                 WHERE rd2.ligne_cotation_id = lc.id
                 ORDER BY rd2.prix_unitaire_ht ASC LIMIT 1) as meilleur_fournisseur
            FROM lignes_cotation lc
            LEFT JOIN reponses_fournisseurs_detail rd ON lc.id = rd.ligne_cotation_id
            WHERE lc.numero_da IN ({placeholders}) AND lc.actif = TRUE
            GROUP BY lc.numero_da, lc.code_article, lc.id
        """
        result = execute_query(query, tuple(numeros_da))
        if result:
            for row in result:
                reponses_info[row['da_key']] = row

    # Construire la réponse
    items = []
    for art in articles_page:
        key = f"{art['numero_da']}|{art['code_article']}"
        info = reponses_info.get(key, {})

        items.append(ArticleNonSigne(
            numero_da=art['numero_da'],
            code_article=art['code_article'],
            designation_article=art.get('designation_article'),
            quantite=float(art.get('quantite') or 0),
            unite=art.get('unite'),
            marque_souhaitee=art.get('marque'),
            niveau_signature=art.get('niveau_signature') or 1,
            libelle_signature=get_libelle_signature(art.get('niveau_signature') or 1),
            nb_reponses=info.get('nb_reponses') or 0,
            meilleur_prix=float(info['meilleur_prix']) if info.get('meilleur_prix') else None,
            meilleur_fournisseur=info.get('meilleur_fournisseur')
        ))

    return ArticleNonSigneListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit
    )


# ──────────────────────────────────────────────────────────
# Liste: Articles prix > tarif
# ──────────────────────────────────────────────────────────

@router.get("/blocages/prix-superieur", response_model=ArticlePrixSuperieurListResponse)
async def get_articles_prix_superieur(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    ecart_min: float = Query(default=0, description="Écart minimum en %"),
    numero_da: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user)
):
    """Liste des articles où les offres dépassent le tarif X3"""

    # Récupérer DA non soldées et tarifs
    da_non_soldees = get_da_non_soldees_x3()
    da_set = {f"{d['numero_da']}|{d['code_article']}" for d in da_non_soldees}
    tarifs = get_tarifs_x3()

    if not da_non_soldees or not tarifs:
        return ArticlePrixSuperieurListResponse(
            items=[], total=0, page=page, limit=limit, montant_ecart_total=0
        )

    # Récupérer les offres depuis MySQL
    numeros_da = list(set(d['numero_da'] for d in da_non_soldees))
    placeholders = ", ".join(["%s"] * len(numeros_da))

    where_filter = f"lc.numero_da IN ({placeholders})"
    params = list(numeros_da)

    if numero_da:
        where_filter += " AND lc.numero_da LIKE %s"
        params.append(f"%{numero_da}%")

    query = f"""
        SELECT
            lc.numero_da,
            lc.code_article,
            lc.designation_article,
            lc.quantite_demandee as quantite,
            MIN(rd.prix_unitaire_ht) as prix_min,
            dc.code_fournisseur,
            f.nom_fournisseur,
            COUNT(rd.id) as nb_offres
        FROM lignes_cotation lc
        INNER JOIN reponses_fournisseurs_detail rd ON lc.id = rd.ligne_cotation_id
        INNER JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        INNER JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        LEFT JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE {where_filter} AND lc.actif = TRUE AND rd.prix_unitaire_ht IS NOT NULL
        GROUP BY lc.numero_da, lc.code_article, lc.designation_article,
                 lc.quantite_demandee, dc.code_fournisseur, f.nom_fournisseur
    """

    rows = execute_query(query, tuple(params))

    # Filtrer et calculer
    items = []
    montant_total = 0.0

    for row in rows or []:
        key = f"{row['numero_da']}|{row['code_article']}"
        if key not in da_set:
            continue

        code = row['code_article'].strip() if row['code_article'] else ''
        tarif = tarifs.get(code)

        if not tarif or tarif <= 0:
            continue

        prix_min = float(row['prix_min'])
        if prix_min <= tarif:
            continue

        ecart_montant = prix_min - tarif
        ecart_pourcent = (ecart_montant / tarif) * 100

        if ecart_pourcent < ecart_min:
            continue

        montant_total += ecart_montant

        items.append(ArticlePrixSuperieur(
            numero_da=row['numero_da'],
            code_article=code,
            designation_article=row['designation_article'],
            quantite=float(row['quantite'] or 0),
            tarif_reference=tarif,
            prix_min_propose=prix_min,
            ecart_min_pourcent=round(ecart_pourcent, 2),
            ecart_min_montant=round(ecart_montant, 2),
            fournisseur_moins_cher=row['code_fournisseur'],
            nom_fournisseur=row['nom_fournisseur'],
            nb_offres=row['nb_offres'] or 0
        ))

    # Trier par écart décroissant
    items.sort(key=lambda x: x.ecart_min_pourcent, reverse=True)

    # Pagination
    total = len(items)
    offset = (page - 1) * limit
    items_page = items[offset:offset + limit]

    return ArticlePrixSuperieurListResponse(
        items=items_page,
        total=total,
        page=page,
        limit=limit,
        montant_ecart_total=round(montant_total, 2)
    )


# ──────────────────────────────────────────────────────────
# Liste: Articles marque différente
# ──────────────────────────────────────────────────────────

@router.get("/blocages/marque-differente", response_model=ArticleMarqueDifferenteListResponse)
async def get_articles_marque_differente(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    numero_da: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user)
):
    """Liste des articles avec marque proposée différente de celle demandée"""

    # Récupérer DA non soldées
    da_non_soldees = get_da_non_soldees_x3()
    da_set = {f"{d['numero_da']}|{d['code_article']}" for d in da_non_soldees}
    marques_x3 = get_marques_x3()

    if not da_non_soldees:
        return ArticleMarqueDifferenteListResponse(items=[], total=0, page=page, limit=limit)

    numeros_da = list(set(d['numero_da'] for d in da_non_soldees))
    placeholders = ", ".join(["%s"] * len(numeros_da))

    where_filter = f"""
        lc.numero_da IN ({placeholders})
        AND lc.actif = TRUE
        AND lc.marque_souhaitee IS NOT NULL AND lc.marque_souhaitee != ''
        AND rd.marque_proposee IS NOT NULL AND rd.marque_proposee != ''
        AND UPPER(TRIM(lc.marque_souhaitee)) != UPPER(TRIM(rd.marque_proposee))
    """
    params = list(numeros_da)

    if numero_da:
        where_filter += " AND lc.numero_da LIKE %s"
        params.append(f"%{numero_da}%")

    query = f"""
        SELECT
            lc.numero_da,
            lc.code_article,
            lc.designation_article,
            lc.quantite_demandee as quantite,
            lc.marque_souhaitee,
            rd.marque_proposee,
            dc.code_fournisseur,
            f.nom_fournisseur,
            rd.prix_unitaire_ht as prix_propose,
            (SELECT COUNT(*) FROM reponses_fournisseurs_detail rd2
             INNER JOIN lignes_cotation lc2 ON rd2.ligne_cotation_id = lc2.id
             WHERE lc2.numero_da = lc.numero_da AND lc2.code_article = lc.code_article
               AND UPPER(TRIM(rd2.marque_proposee)) = UPPER(TRIM(lc.marque_souhaitee))) as nb_conformes
        FROM lignes_cotation lc
        INNER JOIN reponses_fournisseurs_detail rd ON lc.id = rd.ligne_cotation_id
        INNER JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        INNER JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        LEFT JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE {where_filter}
        ORDER BY lc.numero_da, lc.code_article
    """

    rows = execute_query(query, tuple(params))

    # Filtrer par DA non soldées
    items = []
    for row in rows or []:
        key = f"{row['numero_da']}|{row['code_article']}"
        if key not in da_set:
            continue

        code = row['code_article'].strip() if row['code_article'] else ''
        marque_proposee = (row['marque_proposee'] or '').strip().upper()
        marques_dispo = marques_x3.get(code, [])

        items.append(ArticleMarqueDifferente(
            numero_da=row['numero_da'],
            code_article=code,
            designation_article=row['designation_article'],
            quantite=float(row['quantite'] or 0),
            marque_souhaitee=row['marque_souhaitee'],
            marque_proposee=row['marque_proposee'],
            marque_existe_x3=marque_proposee in marques_dispo,
            code_fournisseur=row['code_fournisseur'],
            nom_fournisseur=row['nom_fournisseur'],
            prix_propose=float(row['prix_propose'] or 0),
            nb_offres_conformes=row['nb_conformes'] or 0
        ))

    # Pagination
    total = len(items)
    offset = (page - 1) * limit
    items_page = items[offset:offset + limit]

    return ArticleMarqueDifferenteListResponse(
        items=items_page,
        total=total,
        page=page,
        limit=limit
    )


# ──────────────────────────────────────────────────────────
# Liste: Articles marque inexistante dans X3
# ──────────────────────────────────────────────────────────

@router.get("/blocages/marque-inexistante", response_model=ArticleMarqueInexistanteListResponse)
async def get_articles_marque_inexistante(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    numero_da: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user)
):
    """Liste des articles avec marque proposée qui n'existe pas dans X3"""

    # Récupérer DA non soldées
    da_non_soldees = get_da_non_soldees_x3()
    da_set = {f"{d['numero_da']}|{d['code_article']}" for d in da_non_soldees}
    marques_x3 = get_marques_x3()

    if not da_non_soldees:
        return ArticleMarqueInexistanteListResponse(items=[], total=0, page=page, limit=limit)

    numeros_da = list(set(d['numero_da'] for d in da_non_soldees))
    placeholders = ", ".join(["%s"] * len(numeros_da))

    where_filter = f"""
        lc.numero_da IN ({placeholders})
        AND lc.actif = TRUE
        AND rd.marque_proposee IS NOT NULL AND rd.marque_proposee != ''
    """
    params = list(numeros_da)

    if numero_da:
        where_filter += " AND lc.numero_da LIKE %s"
        params.append(f"%{numero_da}%")

    query = f"""
        SELECT
            lc.numero_da,
            lc.code_article,
            lc.designation_article,
            lc.quantite_demandee as quantite,
            rd.marque_proposee,
            dc.code_fournisseur,
            f.nom_fournisseur,
            rd.prix_unitaire_ht as prix_propose
        FROM lignes_cotation lc
        INNER JOIN reponses_fournisseurs_detail rd ON lc.id = rd.ligne_cotation_id
        INNER JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        INNER JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        LEFT JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE {where_filter}
        ORDER BY lc.numero_da, lc.code_article
    """

    rows = execute_query(query, tuple(params))

    # Filtrer: marque proposée n'existe pas dans X3 pour cet article
    items = []
    for row in rows or []:
        key = f"{row['numero_da']}|{row['code_article']}"
        if key not in da_set:
            continue

        code = row['code_article'].strip() if row['code_article'] else ''
        marque_proposee = (row['marque_proposee'] or '').strip().upper()
        marques_valides = marques_x3.get(code, [])

        # Vérifier si la marque n'existe pas dans X3
        if marque_proposee and marque_proposee not in marques_valides:
            items.append(ArticleMarqueInexistante(
                numero_da=row['numero_da'],
                code_article=code,
                designation_article=row['designation_article'],
                quantite=float(row['quantite'] or 0),
                marque_proposee=row['marque_proposee'],
                marques_valides_x3=marques_valides,
                code_fournisseur=row['code_fournisseur'],
                nom_fournisseur=row['nom_fournisseur'],
                prix_propose=float(row['prix_propose'] or 0)
            ))

    # Pagination
    total = len(items)
    offset = (page - 1) * limit
    items_page = items[offset:offset + limit]

    return ArticleMarqueInexistanteListResponse(
        items=items_page,
        total=total,
        page=page,
        limit=limit
    )


# ──────────────────────────────────────────────────────────
# Liste: Articles prix OK mais marque inexistante
# ──────────────────────────────────────────────────────────

@router.get("/blocages/prix-ok-marque-inexistante", response_model=ArticlePrixOkMarqueInexListResponse)
async def get_articles_prix_ok_marque_inexistante(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    numero_da: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user)
):
    """Liste des articles avec prix <= tarif mais marque n'existe pas dans X3"""

    # Récupérer DA non soldées et références
    da_non_soldees = get_da_non_soldees_x3()
    da_set = {f"{d['numero_da']}|{d['code_article']}" for d in da_non_soldees}
    tarifs = get_tarifs_x3()
    marques_x3 = get_marques_x3()

    if not da_non_soldees:
        return ArticlePrixOkMarqueInexListResponse(items=[], total=0, page=page, limit=limit)

    numeros_da = list(set(d['numero_da'] for d in da_non_soldees))
    placeholders = ", ".join(["%s"] * len(numeros_da))

    where_filter = f"""
        lc.numero_da IN ({placeholders})
        AND lc.actif = TRUE
        AND rd.prix_unitaire_ht IS NOT NULL
        AND rd.marque_proposee IS NOT NULL AND rd.marque_proposee != ''
    """
    params = list(numeros_da)

    if numero_da:
        where_filter += " AND lc.numero_da LIKE %s"
        params.append(f"%{numero_da}%")

    query = f"""
        SELECT
            lc.numero_da,
            lc.code_article,
            lc.designation_article,
            lc.quantite_demandee as quantite,
            rd.prix_unitaire_ht as prix_propose,
            rd.marque_proposee,
            dc.code_fournisseur,
            f.nom_fournisseur
        FROM lignes_cotation lc
        INNER JOIN reponses_fournisseurs_detail rd ON lc.id = rd.ligne_cotation_id
        INNER JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        INNER JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        LEFT JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE {where_filter}
        ORDER BY lc.numero_da, lc.code_article
    """

    rows = execute_query(query, tuple(params))

    # Filtrer: prix OK (<=tarif) ET marque inexistante
    items = []
    for row in rows or []:
        key = f"{row['numero_da']}|{row['code_article']}"
        if key not in da_set:
            continue

        code = row['code_article'].strip() if row['code_article'] else ''
        tarif = tarifs.get(code)
        prix = float(row['prix_propose']) if row['prix_propose'] else 0
        marque_proposee = (row['marque_proposee'] or '').strip().upper()
        marques_valides = marques_x3.get(code, [])

        # Prix OK (<=tarif) ET marque inexistante
        if tarif and prix <= tarif and marque_proposee and marque_proposee not in marques_valides:
            ecart = ((prix - tarif) / tarif) * 100 if tarif > 0 else 0
            items.append(ArticlePrixOkMarqueInex(
                numero_da=row['numero_da'],
                code_article=code,
                designation_article=row['designation_article'],
                quantite=float(row['quantite'] or 0),
                tarif_reference=tarif,
                prix_propose=prix,
                ecart_pourcent=round(ecart, 2),
                marque_proposee=row['marque_proposee'],
                marques_valides_x3=marques_valides,
                code_fournisseur=row['code_fournisseur'],
                nom_fournisseur=row['nom_fournisseur']
            ))

    # Pagination
    total = len(items)
    offset = (page - 1) * limit
    items_page = items[offset:offset + limit]

    return ArticlePrixOkMarqueInexListResponse(
        items=items_page,
        total=total,
        page=page,
        limit=limit
    )


# ──────────────────────────────────────────────────────────
# Liste: Articles sans réponse
# ──────────────────────────────────────────────────────────

@router.get("/blocages/sans-reponse", response_model=ArticleSansReponseListResponse)
async def get_articles_sans_reponse(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    numero_da: Optional[str] = Query(default=None),
    jours_min: int = Query(default=0, description="Jours minimum depuis la RFQ"),
    current_user: dict = Depends(get_current_user)
):
    """Liste des articles avec RFQ envoyées mais sans réponse"""

    # Récupérer DA non soldées
    da_non_soldees = get_da_non_soldees_x3()
    da_dict = {f"{d['numero_da']}|{d['code_article']}": d for d in da_non_soldees}

    if not da_non_soldees:
        return ArticleSansReponseListResponse(items=[], total=0, page=page, limit=limit)

    numeros_da = list(set(d['numero_da'] for d in da_non_soldees))
    placeholders = ", ".join(["%s"] * len(numeros_da))

    where_filter = f"""
        lc.numero_da IN ({placeholders})
        AND lc.actif = TRUE
        AND rd.id IS NULL
    """
    params = list(numeros_da)

    if numero_da:
        where_filter += " AND lc.numero_da LIKE %s"
        params.append(f"%{numero_da}%")

    if jours_min > 0:
        where_filter += " AND DATEDIFF(NOW(), dc.created_at) >= %s"
        params.append(jours_min)

    query = f"""
        SELECT
            lc.numero_da,
            lc.code_article,
            lc.designation_article,
            lc.quantite_demandee as quantite,
            lc.marque_souhaitee,
            COUNT(DISTINCT dc.id) as nb_rfq,
            GROUP_CONCAT(DISTINCT dc.code_fournisseur) as fournisseurs,
            MIN(dc.created_at) as date_premiere_rfq,
            DATEDIFF(NOW(), MIN(dc.created_at)) as jours_depuis
        FROM lignes_cotation lc
        INNER JOIN demandes_cotation dc ON lc.rfq_uuid = dc.uuid
        LEFT JOIN reponses_fournisseurs_detail rd ON lc.id = rd.ligne_cotation_id
        WHERE {where_filter}
        GROUP BY lc.numero_da, lc.code_article, lc.designation_article,
                 lc.quantite_demandee, lc.marque_souhaitee
        ORDER BY jours_depuis DESC
    """

    rows = execute_query(query, tuple(params))

    # Filtrer par DA non soldées et enrichir avec données X3
    items = []
    for row in rows or []:
        key = f"{row['numero_da']}|{row['code_article']}"
        if key not in da_dict:
            continue

        da_info = da_dict[key]

        items.append(ArticleSansReponse(
            numero_da=row['numero_da'],
            code_article=row['code_article'],
            designation_article=row['designation_article'] or da_info.get('designation_article'),
            quantite=float(row['quantite'] or da_info.get('quantite') or 0),
            unite=da_info.get('unite'),
            marque_souhaitee=row['marque_souhaitee'] or da_info.get('marque'),
            nb_rfq_envoyees=row['nb_rfq'] or 0,
            fournisseurs_consultes=(row['fournisseurs'] or '').split(',') if row['fournisseurs'] else [],
            date_premiere_rfq=row['date_premiere_rfq'],
            jours_depuis_rfq=row['jours_depuis'] or 0
        ))

    # Pagination
    total = len(items)
    offset = (page - 1) * limit
    items_page = items[offset:offset + limit]

    return ArticleSansReponseListResponse(
        items=items_page,
        total=total,
        page=page,
        limit=limit
    )
