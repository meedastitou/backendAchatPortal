"""
════════════════════════════════════════════════════════════
ROUTER - Synchronisation statuts DA avec Sage X3
════════════════════════════════════════════════════════════
Permet de synchroniser les statuts (signé/soldé) des DA
depuis Sage X3 vers le portail flux_achat
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import time
import logging

from app.auth.dependencies import get_current_user
from app.database import execute_query, execute_insert, execute_update
from app.sqlserver_db import execute_x3_query
from app.schemas.sync_x3 import (
    TypeSync,
    StatutSync,
    StatutX3Combine,
    SyncX3Request,
    SyncX3Response,
    DAStatusX3,
    StatsX3,
    DAAvecStatutX3,
    DAListX3Response,
    LogSyncX3,
    LogSyncX3ListResponse,
    # Nouveaux schemas pour alertes
    ReponseDANonSignee,
    ReponseDANonSigneeListResponse,
    OffrePrixSuperieurTarif,
    OffrePrixSuperieurTarifListResponse,
    OffreMarqueDifferente,
    OffreMarqueDifferenteListResponse,
    DANonSoldeeX3,
    DANonSoldeeX3ListResponse,
    StatsAlertesX3
)


router = APIRouter(prefix="/sync-x3", tags=["Synchronisation X3"])


# ──────────────────────────────────────────────────────────
# Constantes statuts Sage X3
# ──────────────────────────────────────────────────────────

X3_SIGNE_NON = 1
X3_SIGNE_VISA_1 = 2
X3_SIGNE_VISA_2 = 3
X3_SIGNE_VISA_3 = 4
X3_SIGNE_COMPLET = 5

X3_SOLDE_NON = 1
X3_SOLDE_OUI = 2


def get_libelle_signature(niveau: int) -> str:
    """Convertir le niveau de signature en libellé"""
    labels = {
        1: "Non signé",
        2: "Visa 1",
        3: "Visa 2",
        4: "Visa 3",
        5: "Signé complet"
    }
    return labels.get(niveau, "Inconnu")


def get_statut_combine(signe: bool, solde: bool) -> StatutX3Combine:
    """Déterminer le statut combiné"""
    if solde:
        return StatutX3Combine.SOLDE
    elif not signe:
        return StatutX3Combine.EN_ATTENTE_SIGNATURE
    else:
        return StatutX3Combine.ACTIVE


# ──────────────────────────────────────────────────────────
# Fonctions utilitaires
# ──────────────────────────────────────────────────────────

def get_das_from_x3(numeros_da: List[str]) -> Dict[str, Dict]:
    """
    Récupérer les statuts de plusieurs DA depuis Sage X3.

    Returns:
        Dict avec clé "numero_da|code_article" et valeur les infos X3
    """
    if not numeros_da:
        return {}

    try:
        # Construire la clause IN
        placeholders = ", ".join([f"'{da}'" for da in numeros_da])

        query = f"""
            SELECT
                PR.PSHNUM_0 AS numero_da,
                PRD.ITMREF_0 AS code_article,
                PRD.LINAPPFLG_0 AS niveau_signature,
                PRD.LINCLEFLG_0 AS ligne_solde,
                PR.CLEFLG_0 AS da_solde
            FROM BASE1.PREQUIS PR
            INNER JOIN BASE1.PREQUISD PRD ON PR.PSHNUM_0 = PRD.PSHNUM_0
            WHERE PR.PSHNUM_0 IN ({placeholders})
        """

        rows = execute_x3_query(query, {})

        # Construire le dictionnaire de résultats
        result = {}
        for row in rows:
            key = f"{row['numero_da']}|{row['code_article']}"

            # Déterminer si signé (niveau >= 2 signifie au moins un visa)
            est_signe = row['niveau_signature'] >= X3_SIGNE_VISA_1

            # Déterminer si soldé
            est_solde = (row['da_solde'] == X3_SOLDE_OUI or
                        row['ligne_solde'] == X3_SOLDE_OUI)

            result[key] = {
                "numero_da": row['numero_da'],
                "code_article": row['code_article'],
                "niveau_signature": row['niveau_signature'],
                "est_signe": est_signe,
                "est_solde": est_solde,
                "raw": row
            }

        return result

    except Exception as e:
        logging.error(f"Erreur récupération DA depuis X3: {e}")
        return {}


def sync_das_with_x3(das_mysql: List[Dict], das_x3: Dict[str, Dict]) -> List[DAStatusX3]:
    """
    Synchroniser les DA MySQL avec les données X3.

    Returns:
        Liste des DA avec changements détectés
    """
    changements = []

    for da in das_mysql:
        key = f"{da['numero_da']}|{da['code_article']}"

        if key not in das_x3:
            # DA non trouvée dans X3 - ignorer
            continue

        x3_data = das_x3[key]

        # Déterminer les changements
        ancien_signe = da.get('x3_signe', False) or False
        ancien_solde = da.get('x3_solde', False) or False
        ancien_niveau = da.get('x3_niveau_signature', 1) or 1

        nouveau_signe = x3_data['est_signe']
        nouveau_solde = x3_data['est_solde']
        nouveau_niveau = x3_data['niveau_signature']

        signature_changee = ancien_signe != nouveau_signe or ancien_niveau != nouveau_niveau
        solde_change = ancien_solde != nouveau_solde

        if signature_changee or solde_change:
            # Mettre à jour dans MySQL
            update_query = """
                UPDATE demandes_achat SET
                    x3_signe = %s,
                    x3_niveau_signature = %s,
                    x3_solde = %s,
                    x3_derniere_sync = NOW(),
                    x3_sync_erreur = NULL
                WHERE id = %s
            """
            execute_update(update_query, (
                nouveau_signe,
                nouveau_niveau,
                nouveau_solde,
                da['id']
            ))

            changements.append(DAStatusX3(
                numero_da=da['numero_da'],
                code_article=da['code_article'],
                x3_signe=nouveau_signe,
                x3_niveau_signature=nouveau_niveau,
                x3_solde=nouveau_solde,
                statut_combine=get_statut_combine(nouveau_signe, nouveau_solde),
                signature_changee=signature_changee,
                solde_change=solde_change
            ))
        else:
            # Juste mettre à jour la date de sync
            execute_update("""
                UPDATE demandes_achat SET
                    x3_derniere_sync = NOW()
                WHERE id = %s
            """, (da['id'],))

    return changements


# ──────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────

@router.post("/synchroniser", response_model=SyncX3Response)
async def synchroniser_statuts_x3(
    request: SyncX3Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Synchroniser les statuts des DA avec Sage X3.

    - Récupère les statuts (signé/soldé) depuis X3
    - Met à jour les colonnes x3_* dans demandes_achat
    - Log la synchronisation
    """
    start_time = time.time()
    erreurs = []

    try:
        # 1. Récupérer les DA à synchroniser depuis MySQL
        where_clause = "WHERE statut != 'annule'"
        params = []

        if request.numero_da:
            where_clause += " AND numero_da = %s"
            params.append(request.numero_da)

        if not request.force_update:
            # Ne pas re-synchroniser celles synchronisées dans les 5 dernières minutes
            where_clause += " AND (x3_derniere_sync IS NULL OR x3_derniere_sync < DATE_SUB(NOW(), INTERVAL 5 MINUTE))"

        query = f"""
            SELECT
                id, numero_da, code_article,
                x3_signe, x3_niveau_signature, x3_solde
            FROM demandes_achat
            {where_clause}
            LIMIT %s
        """
        params.append(request.limit)

        das_mysql = execute_query(query, tuple(params))

        if not das_mysql:
            return SyncX3Response(
                success=True,
                statut=StatutSync.SUCCES,
                message="Aucune DA à synchroniser",
                date_sync=datetime.now(),
                duree_ms=int((time.time() - start_time) * 1000),
                nb_da_verifiees=0,
                nb_da_mises_a_jour=0,
                nb_nouvelles_signees=0,
                nb_nouvelles_soldees=0
            )

        # 2. Récupérer les numéros de DA uniques
        numeros_da = list(set(da['numero_da'] for da in das_mysql))

        # 3. Récupérer les statuts depuis X3
        das_x3 = get_das_from_x3(numeros_da)

        if not das_x3:
            erreurs.append("Impossible de récupérer les données depuis Sage X3")
            # Mettre à jour les erreurs dans MySQL
            for da in das_mysql:
                execute_update("""
                    UPDATE demandes_achat SET
                        x3_derniere_sync = NOW(),
                        x3_sync_erreur = %s
                    WHERE id = %s
                """, ("Connexion X3 échouée", da['id']))

        # 4. Synchroniser
        changements = sync_das_with_x3(das_mysql, das_x3) if das_x3 else []

        # 5. Calculer les statistiques
        nb_nouvelles_signees = sum(1 for c in changements if c.signature_changee and c.x3_signe)
        nb_nouvelles_soldees = sum(1 for c in changements if c.solde_change and c.x3_solde)

        # 6. Logger la synchronisation
        duree_ms = int((time.time() - start_time) * 1000)

        log_id = execute_insert("""
            INSERT INTO logs_sync_x3 (
                date_sync, type_sync, nb_da_verifiees, nb_da_mises_a_jour,
                nb_nouvelles_signees, nb_nouvelles_soldees, statut,
                message_erreur, duree_ms, execute_par
            ) VALUES (
                NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            request.type_sync.value,
            len(das_mysql),
            len(changements),
            nb_nouvelles_signees,
            nb_nouvelles_soldees,
            StatutSync.SUCCES.value if not erreurs else StatutSync.PARTIEL.value,
            "; ".join(erreurs) if erreurs else None,
            duree_ms,
            current_user.get("username", "SYSTEM")
        ))

        return SyncX3Response(
            success=len(erreurs) == 0,
            statut=StatutSync.SUCCES if not erreurs else StatutSync.PARTIEL,
            message=f"Synchronisation terminée: {len(changements)} DA mises à jour sur {len(das_mysql)} vérifiées",
            date_sync=datetime.now(),
            duree_ms=duree_ms,
            nb_da_verifiees=len(das_mysql),
            nb_da_mises_a_jour=len(changements),
            nb_nouvelles_signees=nb_nouvelles_signees,
            nb_nouvelles_soldees=nb_nouvelles_soldees,
            changements=changements,
            erreurs=erreurs,
            log_id=log_id
        )

    except Exception as e:
        logging.error(f"Erreur synchronisation X3: {e}")
        duree_ms = int((time.time() - start_time) * 1000)

        # Logger l'échec
        execute_insert("""
            INSERT INTO logs_sync_x3 (
                date_sync, type_sync, statut, message_erreur, duree_ms, execute_par
            ) VALUES (NOW(), %s, %s, %s, %s, %s)
        """, (
            request.type_sync.value,
            StatutSync.ECHEC.value,
            str(e),
            duree_ms,
            current_user.get("username", "SYSTEM")
        ))

        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la synchronisation: {str(e)}"
        )


@router.get("/stats", response_model=StatsX3)
async def get_stats_x3(current_user: dict = Depends(get_current_user)):
    """Obtenir les statistiques des statuts X3"""

    query = """
        SELECT
            COUNT(*) AS total_da,
            SUM(CASE WHEN x3_signe = TRUE THEN 1 ELSE 0 END) AS nb_signees,
            SUM(CASE WHEN x3_signe = FALSE OR x3_signe IS NULL THEN 1 ELSE 0 END) AS nb_non_signees,
            SUM(CASE WHEN x3_solde = TRUE THEN 1 ELSE 0 END) AS nb_soldees,
            SUM(CASE WHEN x3_solde = FALSE OR x3_solde IS NULL THEN 1 ELSE 0 END) AS nb_non_soldees,
            SUM(CASE WHEN x3_signe = TRUE AND (x3_solde = FALSE OR x3_solde IS NULL) THEN 1 ELSE 0 END) AS nb_signees_non_soldees,
            SUM(CASE WHEN (x3_signe = FALSE OR x3_signe IS NULL) AND (x3_solde = FALSE OR x3_solde IS NULL) THEN 1 ELSE 0 END) AS nb_en_attente_signature,
            MAX(x3_derniere_sync) AS derniere_sync,
            SUM(CASE WHEN x3_derniere_sync IS NULL THEN 1 ELSE 0 END) AS nb_jamais_sync
        FROM demandes_achat
        WHERE statut != 'annule'
    """

    rows = execute_query(query)

    if not rows:
        return StatsX3(
            total_da=0, nb_signees=0, nb_non_signees=0,
            nb_soldees=0, nb_non_soldees=0,
            nb_signees_non_soldees=0, nb_en_attente_signature=0,
            nb_jamais_sync=0
        )

    row = rows[0]
    return StatsX3(
        total_da=row['total_da'] or 0,
        nb_signees=row['nb_signees'] or 0,
        nb_non_signees=row['nb_non_signees'] or 0,
        nb_soldees=row['nb_soldees'] or 0,
        nb_non_soldees=row['nb_non_soldees'] or 0,
        nb_signees_non_soldees=row['nb_signees_non_soldees'] or 0,
        nb_en_attente_signature=row['nb_en_attente_signature'] or 0,
        derniere_sync=row['derniere_sync'],
        nb_jamais_sync=row['nb_jamais_sync'] or 0
    )


@router.get("/demandes-achat", response_model=DAListX3Response)
async def get_demandes_achat_avec_statut_x3(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    x3_signe: Optional[bool] = Query(default=None, description="Filtrer par statut signé"),
    x3_solde: Optional[bool] = Query(default=None, description="Filtrer par statut soldé"),
    statut_x3: Optional[StatutX3Combine] = Query(default=None, description="Filtrer par statut combiné"),
    numero_da: Optional[str] = Query(default=None, description="Recherche par numéro DA"),
    code_article: Optional[str] = Query(default=None, description="Recherche par code article"),
    include_stats: bool = Query(default=False, description="Inclure les statistiques"),
    current_user: dict = Depends(get_current_user)
):
    """Lister les DA avec leur statut X3"""

    # Construire les conditions
    where_clauses = ["statut != 'annule'"]
    params = []

    if x3_signe is not None:
        where_clauses.append("x3_signe = %s")
        params.append(x3_signe)

    if x3_solde is not None:
        where_clauses.append("x3_solde = %s")
        params.append(x3_solde)

    if statut_x3:
        if statut_x3 == StatutX3Combine.SOLDE:
            where_clauses.append("x3_solde = TRUE")
        elif statut_x3 == StatutX3Combine.EN_ATTENTE_SIGNATURE:
            where_clauses.append("(x3_signe = FALSE OR x3_signe IS NULL) AND (x3_solde = FALSE OR x3_solde IS NULL)")
        elif statut_x3 == StatutX3Combine.ACTIVE:
            where_clauses.append("x3_signe = TRUE AND (x3_solde = FALSE OR x3_solde IS NULL)")

    if numero_da:
        where_clauses.append("numero_da LIKE %s")
        params.append(f"%{numero_da}%")

    if code_article:
        where_clauses.append("code_article LIKE %s")
        params.append(f"%{code_article}%")

    where_sql = " AND ".join(where_clauses)

    # Compter le total
    count_query = f"SELECT COUNT(*) as total FROM demandes_achat WHERE {where_sql}"
    count_result = execute_query(count_query, tuple(params))
    total = count_result[0]['total'] if count_result else 0

    # Récupérer les données paginées
    offset = (page - 1) * limit

    query = f"""
        SELECT
            id, numero_da, code_article, designation_article,
            quantite, unite, marque_souhaitee,
            date_creation_da, date_besoin,
            statut AS statut_portail, priorite,
            x3_signe, x3_niveau_signature, x3_solde,
            x3_derniere_sync
        FROM demandes_achat
        WHERE {where_sql}
        ORDER BY date_creation_da DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    rows = execute_query(query, tuple(params))

    items = []
    for row in rows:
        x3_signe = row['x3_signe'] or False
        x3_solde = row['x3_solde'] or False
        niveau_sig = row['x3_niveau_signature'] or 1

        items.append(DAAvecStatutX3(
            id=row['id'],
            numero_da=row['numero_da'],
            code_article=row['code_article'],
            designation_article=row['designation_article'],
            quantite=float(row['quantite']),
            unite=row['unite'],
            marque_souhaitee=row['marque_souhaitee'],
            date_creation_da=row['date_creation_da'],
            date_besoin=row['date_besoin'],
            statut_portail=row['statut_portail'],
            priorite=row['priorite'],
            x3_signe=x3_signe,
            x3_niveau_signature=niveau_sig,
            libelle_signature=get_libelle_signature(niveau_sig),
            x3_solde=x3_solde,
            libelle_solde="Soldée" if x3_solde else "Active",
            statut_x3_combine=get_statut_combine(x3_signe, x3_solde),
            x3_derniere_sync=row['x3_derniere_sync']
        ))

    # Inclure les stats si demandé
    stats = None
    if include_stats:
        stats_response = await get_stats_x3(current_user)
        stats = stats_response

    return DAListX3Response(
        items=items,
        total=total,
        page=page,
        limit=limit,
        stats=stats
    )


@router.get("/logs", response_model=LogSyncX3ListResponse)
async def get_logs_sync_x3(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    statut: Optional[StatutSync] = Query(default=None),
    current_user: dict = Depends(get_current_user)
):
    """Historique des synchronisations"""

    where_clauses = ["1=1"]
    params = []

    if statut:
        where_clauses.append("statut = %s")
        params.append(statut.value)

    where_sql = " AND ".join(where_clauses)

    # Compter
    count_result = execute_query(
        f"SELECT COUNT(*) as total FROM logs_sync_x3 WHERE {where_sql}",
        tuple(params)
    )
    total = count_result[0]['total'] if count_result else 0

    # Récupérer
    offset = (page - 1) * limit
    query = f"""
        SELECT * FROM logs_sync_x3
        WHERE {where_sql}
        ORDER BY date_sync DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    rows = execute_query(query, tuple(params))

    logs = [
        LogSyncX3(
            id=row['id'],
            date_sync=row['date_sync'],
            type_sync=TypeSync(row['type_sync']),
            nb_da_verifiees=row['nb_da_verifiees'] or 0,
            nb_da_mises_a_jour=row['nb_da_mises_a_jour'] or 0,
            nb_nouvelles_signees=row['nb_nouvelles_signees'] or 0,
            nb_nouvelles_soldees=row['nb_nouvelles_soldees'] or 0,
            statut=StatutSync(row['statut']),
            message_erreur=row['message_erreur'],
            duree_ms=row['duree_ms'],
            execute_par=row['execute_par']
        )
        for row in rows
    ]

    return LogSyncX3ListResponse(
        logs=logs,
        total=total,
        page=page,
        limit=limit
    )


@router.post("/synchroniser-da/{numero_da}", response_model=SyncX3Response)
async def synchroniser_da_specifique(
    numero_da: str,
    current_user: dict = Depends(get_current_user)
):
    """Synchroniser une DA spécifique avec X3"""
    return await synchroniser_statuts_x3(
        SyncX3Request(numero_da=numero_da, force_update=True),
        current_user
    )


# ══════════════════════════════════════════════════════════════
# ALERTES ET ANALYSES
# ══════════════════════════════════════════════════════════════

@router.get("/alertes/stats", response_model=StatsAlertesX3)
async def get_stats_alertes_x3(current_user: dict = Depends(get_current_user)):
    """Statistiques des alertes X3"""

    stats = StatsAlertesX3()

    # 1. Réponses sur DA non signées
    query1 = """
        SELECT COUNT(DISTINCT rd.id) as count
        FROM reponses_fournisseurs_detail rd
        INNER JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        INNER JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        INNER JOIN demandes_achat da ON lc.numero_da = da.numero_da AND lc.code_article = da.code_article
        WHERE (da.x3_signe = FALSE OR da.x3_signe IS NULL)
          AND (da.x3_solde = FALSE OR da.x3_solde IS NULL)
          AND da.statut != 'annule'
    """
    result = execute_query(query1)
    stats.nb_reponses_da_non_signees = result[0]['count'] if result else 0

    # 2. Offres prix > tarif (nécessite jointure avec X3)
    # Pour l'instant on compte dans le portail, X3 sera ajouté après
    stats.nb_offres_prix_superieur = 0
    stats.montant_ecart_total = 0

    # 3. Offres marque différente
    query3 = """
        SELECT COUNT(DISTINCT rd.id) as count
        FROM reponses_fournisseurs_detail rd
        INNER JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        WHERE lc.marque_souhaitee IS NOT NULL
          AND lc.marque_souhaitee != ''
          AND rd.marque_proposee IS NOT NULL
          AND rd.marque_proposee != ''
          AND UPPER(TRIM(lc.marque_souhaitee)) != UPPER(TRIM(rd.marque_proposee))
    """
    result = execute_query(query3)
    stats.nb_offres_marque_differente = result[0]['count'] if result else 0

    return stats


@router.get("/alertes/reponses-da-non-signees", response_model=ReponseDANonSigneeListResponse)
async def get_reponses_da_non_signees(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    numero_da: Optional[str] = Query(default=None),
    code_article: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user)
):
    """
    Liste des réponses fournisseurs sur des DA non encore signées.
    Utile pour identifier les offres en attente de validation.
    """
    where_clauses = [
        "(da.x3_signe = FALSE OR da.x3_signe IS NULL)",
        "(da.x3_solde = FALSE OR da.x3_solde IS NULL)",
        "da.statut != 'annule'"
    ]
    params = []

    if numero_da:
        where_clauses.append("lc.numero_da LIKE %s")
        params.append(f"%{numero_da}%")

    if code_article:
        where_clauses.append("lc.code_article LIKE %s")
        params.append(f"%{code_article}%")

    where_sql = " AND ".join(where_clauses)

    # Count
    count_query = f"""
        SELECT COUNT(DISTINCT rd.id) as total
        FROM reponses_fournisseurs_detail rd
        INNER JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        INNER JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        INNER JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        INNER JOIN demandes_achat da ON lc.numero_da = da.numero_da AND lc.code_article = da.code_article
        WHERE {where_sql}
    """
    count_result = execute_query(count_query, tuple(params))
    total = count_result[0]['total'] if count_result else 0

    # Data
    offset = (page - 1) * limit
    query = f"""
        SELECT
            rd.id as reponse_id,
            lc.numero_da,
            lc.code_article,
            lc.designation_article,
            lc.quantite_demandee,
            lc.marque_souhaitee,
            dc.code_fournisseur,
            f.nom_fournisseur,
            rd.prix_unitaire_ht as prix_unitaire,
            rd.quantite_disponible,
            DATEDIFF(rd.date_livraison, NOW()) as delai_livraison,
            re.date_reponse,
            da.x3_niveau_signature
        FROM reponses_fournisseurs_detail rd
        INNER JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        INNER JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        INNER JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        INNER JOIN demandes_achat da ON lc.numero_da = da.numero_da AND lc.code_article = da.code_article
        LEFT JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE {where_sql}
        ORDER BY re.date_reponse DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    rows = execute_query(query, tuple(params))

    items = [
        ReponseDANonSignee(
            numero_da=row['numero_da'],
            code_article=row['code_article'],
            designation_article=row['designation_article'],
            quantite_demandee=float(row['quantite_demandee'] or 0),
            marque_souhaitee=row['marque_souhaitee'],
            reponse_id=row['reponse_id'],
            code_fournisseur=row['code_fournisseur'],
            nom_fournisseur=row['nom_fournisseur'],
            prix_unitaire=float(row['prix_unitaire'] or 0),
            quantite_disponible=float(row['quantite_disponible'] or 0),
            delai_livraison=row['delai_livraison'],
            date_reponse=row['date_reponse'],
            x3_niveau_signature=row['x3_niveau_signature'] or 1,
            libelle_signature=get_libelle_signature(row['x3_niveau_signature'] or 1)
        )
        for row in rows
    ]

    return ReponseDANonSigneeListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit
    )


@router.get("/alertes/offres-prix-superieur-tarif", response_model=OffrePrixSuperieurTarifListResponse)
async def get_offres_prix_superieur_tarif(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    ecart_min_pourcent: float = Query(default=0, description="Écart minimum en %"),
    current_user: dict = Depends(get_current_user)
):
    """
    Liste des offres fournisseurs avec prix supérieur au tarif X3.
    Compare le prix proposé avec le tarif de référence depuis PPRICLIST.
    """
    try:
        # 1. Récupérer les tarifs depuis X3
        tarif_query = """
            SELECT
                ITMMASTER.ITMREF_0 AS code_article,
                PPRICLIST.PRI_0 AS tarif
            FROM BASE1.PPRICLIST PPRICLIST
            INNER JOIN BASE1.ITMMASTER ITMMASTER
                ON PPRICLIST.PLICRI1_0 = ITMMASTER.ITMREF_0
            WHERE PPRICLIST.PRI_0 > 0
        """
        tarifs_x3 = execute_x3_query(tarif_query, {})

        if not tarifs_x3:
            return OffrePrixSuperieurTarifListResponse(
                items=[], total=0, page=page, limit=limit,
                nb_total_offres=0, montant_ecart_total=0
            )

        # Créer dict tarifs
        tarifs_dict = {row['code_article'].strip(): float(row['tarif']) for row in tarifs_x3}

        # 2. Récupérer les offres depuis MySQL
        query = """
            SELECT
                rd.id as reponse_id,
                lc.code_article,
                lc.designation_article,
                lc.numero_da,
                dc.code_fournisseur,
                f.nom_fournisseur,
                rd.prix_unitaire_ht as prix_propose,
                rd.quantite_disponible,
                re.date_reponse
            FROM reponses_fournisseurs_detail rd
            INNER JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
            INNER JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
            INNER JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
            LEFT JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
            WHERE lc.actif = TRUE
            ORDER BY re.date_reponse DESC
        """
        offres = execute_query(query)

        # 3. Filtrer et calculer les écarts
        items = []
        montant_ecart_total = 0

        for offre in offres:
            code_article = offre['code_article'].strip() if offre['code_article'] else ''
            tarif = tarifs_dict.get(code_article)

            if tarif is None or tarif <= 0:
                continue

            # Skip if price is NULL
            if offre['prix_propose'] is None:
                continue

            prix = float(offre['prix_propose'])
            if prix <= tarif:
                continue

            ecart_montant = prix - tarif
            ecart_pourcent = (ecart_montant / tarif) * 100

            if ecart_pourcent < ecart_min_pourcent:
                continue

            montant_ecart_total += ecart_montant

            items.append(OffrePrixSuperieurTarif(
                code_article=code_article,
                designation_article=offre['designation_article'],
                numero_da=offre['numero_da'],
                tarif_x3=tarif,
                reponse_id=offre['reponse_id'],
                code_fournisseur=offre['code_fournisseur'],
                nom_fournisseur=offre['nom_fournisseur'],
                prix_propose=prix,
                quantite_disponible=float(offre['quantite_disponible'] or 0),
                date_reponse=offre['date_reponse'],
                ecart_pourcent=round(ecart_pourcent, 2),
                ecart_montant=round(ecart_montant, 2)
            ))

        # Trier par écart décroissant
        items.sort(key=lambda x: x.ecart_pourcent, reverse=True)

        # Pagination
        total = len(items)
        offset = (page - 1) * limit
        items_page = items[offset:offset + limit]

        return OffrePrixSuperieurTarifListResponse(
            items=items_page,
            total=total,
            page=page,
            limit=limit,
            nb_total_offres=total,
            montant_ecart_total=round(montant_ecart_total, 2)
        )

    except Exception as e:
        logging.error(f"Erreur récupération offres prix > tarif: {e}")
        return OffrePrixSuperieurTarifListResponse(
            items=[], total=0, page=page, limit=limit,
            nb_total_offres=0, montant_ecart_total=0
        )


@router.get("/alertes/offres-marque-differente", response_model=OffreMarqueDifferenteListResponse)
async def get_offres_marque_differente(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    verifier_x3: bool = Query(default=True, description="Vérifier si marque existe dans X3"),
    current_user: dict = Depends(get_current_user)
):
    """
    Liste des offres avec une marque différente de celle demandée.
    Si verifier_x3=True, indique si la marque proposée existe dans BASE1.XMARQA.
    """
    # 1. Récupérer les marques X3 si demandé
    marques_x3 = {}
    if verifier_x3:
        try:
            marques_query = """
                SELECT ITMREF_0 AS code_article, XMARQ AS marque, PRIX_0 AS prix
                FROM BASE1.XMARQA
            """
            result = execute_x3_query(marques_query, {})

            for row in result:
                code = row['code_article'].strip() if row['code_article'] else ''
                marque = row['marque'].strip().upper() if row['marque'] else ''
                if code not in marques_x3:
                    marques_x3[code] = []
                if marque:
                    marques_x3[code].append(marque)
        except Exception as e:
            logging.error(f"Erreur récupération marques X3: {e}")

    # 2. Récupérer les offres avec marque différente
    where_sql = """
        lc.marque_souhaitee IS NOT NULL
        AND lc.marque_souhaitee != ''
        AND rd.marque_proposee IS NOT NULL
        AND rd.marque_proposee != ''
        AND UPPER(TRIM(lc.marque_souhaitee)) != UPPER(TRIM(rd.marque_proposee))
        AND lc.actif = TRUE
    """

    count_query = f"""
        SELECT COUNT(DISTINCT rd.id) as total
        FROM reponses_fournisseurs_detail rd
        INNER JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        WHERE {where_sql}
    """
    count_result = execute_query(count_query)
    total = count_result[0]['total'] if count_result else 0

    offset = (page - 1) * limit
    query = f"""
        SELECT
            rd.id as reponse_id,
            lc.code_article,
            lc.designation_article,
            lc.numero_da,
            lc.marque_souhaitee,
            dc.code_fournisseur,
            f.nom_fournisseur,
            rd.marque_proposee,
            rd.prix_unitaire_ht as prix_propose,
            rd.quantite_disponible,
            re.date_reponse
        FROM reponses_fournisseurs_detail rd
        INNER JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        INNER JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        INNER JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        LEFT JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE {where_sql}
        ORDER BY re.date_reponse DESC
        LIMIT %s OFFSET %s
    """

    rows = execute_query(query, (limit, offset))

    items = []
    for row in rows:
        code_article = row['code_article'].strip() if row['code_article'] else ''
        marque_proposee = (row['marque_proposee'] or '').strip().upper()

        # Vérifier dans X3
        marques_dispo = marques_x3.get(code_article, [])
        marque_existe_x3 = marque_proposee in marques_dispo if marque_proposee else False

        items.append(OffreMarqueDifferente(
            code_article=code_article,
            designation_article=row['designation_article'],
            numero_da=row['numero_da'],
            marque_souhaitee=row['marque_souhaitee'],
            reponse_id=row['reponse_id'],
            code_fournisseur=row['code_fournisseur'],
            nom_fournisseur=row['nom_fournisseur'],
            marque_proposee=row['marque_proposee'],
            prix_propose=float(row['prix_propose'] or 0),
            quantite_disponible=float(row['quantite_disponible'] or 0),
            date_reponse=row['date_reponse'],
            marque_existe_x3=marque_existe_x3,
            marques_disponibles_x3=marques_dispo[:5]  # Limiter à 5 marques
        ))

    return OffreMarqueDifferenteListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit
    )


@router.get("/x3/da-non-soldees", response_model=DANonSoldeeX3ListResponse)
async def get_da_non_soldees_x3(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    date_min: Optional[str] = Query(default="20260623", description="Date minimum DA (format YYYYMMDD)"),
    current_user: dict = Depends(get_current_user)
):
    """
    Liste des DA non soldées directement depuis Sage X3.
    Utilise la vue Y_DA_NON_SOLDEES.
    """
    try:
        # Requête X3
        query = f"""
            SELECT
                DNS.DA as numero_da,
                DNS.Article as code_article,
                DNS.DésignationArticle as designation_article,
                DNS.QteDA as quantite,
                DAD.XMARQ_0 as marque,
                DNS.STU_0 AS unite,
                DNS.Famille as famille
            FROM BASE1.Y_DA_NON_SOLDEES DNS
            LEFT JOIN BASE1.PREQUIS DA ON DA.PSHNUM_0 = DNS.DA
            INNER JOIN BASE1.PREQUISD DAD ON DAD.PSHNUM_0 = DA.PSHNUM_0 AND DAD.ITMREF_0 = DNS.Article
            WHERE DNS.Famille NOT LIKE 'SERVICE%'
              AND DNS.Famille NOT LIKE 'LOGISTIQUE%'
              AND DNS.Famille NOT LIKE 'R.H'
              AND DNS.Article NOT IN ('A09985', 'A10107', 'A10136')
              AND DNS.DateDA >= '{date_min}'
              AND DA.CLEFLG_0 = 1
        """

        rows = execute_x3_query(query, {})

        if not rows:
            return DANonSoldeeX3ListResponse(
                items=[], total=0, page=page, limit=limit
            )

        # Récupérer les infos du portail pour ces DA
        numeros_da = list(set(row['numero_da'] for row in rows if row['numero_da']))

        portail_info = {}
        if numeros_da:
            placeholders = ", ".join(["%s"] * len(numeros_da))
            portail_query = f"""
                SELECT
                    da.numero_da,
                    da.code_article,
                    da.statut,
                    COUNT(rd.id) as nb_reponses
                FROM demandes_achat da
                LEFT JOIN lignes_cotation lc ON da.numero_da = lc.numero_da AND da.code_article = lc.code_article
                LEFT JOIN reponses_fournisseurs_detail rd ON lc.id = rd.ligne_cotation_id
                WHERE da.numero_da IN ({placeholders})
                GROUP BY da.numero_da, da.code_article, da.statut
            """
            portail_rows = execute_query(portail_query, tuple(numeros_da))

            for pr in portail_rows:
                key = f"{pr['numero_da']}|{pr['code_article']}"
                portail_info[key] = {
                    'existe': True,
                    'statut': pr['statut'],
                    'nb_reponses': pr['nb_reponses'] or 0
                }

        # Construire les items
        items = []
        for row in rows:
            key = f"{row['numero_da']}|{row['code_article']}"
            info = portail_info.get(key, {})

            items.append(DANonSoldeeX3(
                numero_da=row['numero_da'],
                code_article=row['code_article'],
                designation_article=row['designation_article'],
                quantite=float(row['quantite']) if row['quantite'] else 0,
                marque=row['marque'],
                unite=row['unite'],
                famille=row['famille'],
                existe_portail=info.get('existe', False),
                nb_reponses=info.get('nb_reponses', 0),
                statut_portail=info.get('statut')
            ))

        # Pagination
        total = len(items)
        offset = (page - 1) * limit
        items_page = items[offset:offset + limit]

        return DANonSoldeeX3ListResponse(
            items=items_page,
            total=total,
            page=page,
            limit=limit
        )

    except Exception as e:
        logging.error(f"Erreur récupération DA non soldées X3: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur connexion Sage X3: {str(e)}"
        )
