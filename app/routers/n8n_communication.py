

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import time
import json
import logging
import httpx

from app.auth.dependencies import get_current_user
from app.config import RPA_API_URL
from app.database import execute_query, execute_insert, execute_update
from app.sqlserver_db import execute_x3_query
from app.schemas.auto_bc import (
    AutoBCConfig,
    TypeLivraison,
    StatutExecution,
    OffreEligible,
    ArticleAvecOffres,
    BCPreviewLigne,
    BCPreview,
    AutoBCPreviewResponse,
    AutoBCExecuteRequest,
    BCCree,
    AutoBCExecuteResponse,
    LogAutoBCDetail,
    LogAutoBC,
    LogAutoBCListResponse,
    # Analyse
    AnalyseAutoBC,
    AnalyseReponseConsultee,
    AnalyseStatutDA,
    AnalysePrixSuperieur,
    AnalyseMarqueProbleme,
    # BC X3
    LigneBCX3,
    BCX3Response,
    BCX3ListResponse
)


router = APIRouter(prefix="/n8n", tags=["n8n"])

# ──────────────────────────────────────────────────────────
# Constantes statuts Sage X3
# ──────────────────────────────────────────────────────────

# Statuts signature ligne (LINAPPFLG_0)
X3_SIGNE_NON = 1
X3_SIGNE_PARTIEL = 2
X3_SIGNE_TOTAL = 3
X3_SIGNE_NOT_MANAGED = 4
X3_SIGNE_AUTO = 5

# Statuts solde (LINCLEFLG_0 / CLEFLG_0)
X3_SOLDE_NON = 1
X3_SOLDE_OUI = 2

# ──────────────────────────────────────────────────────────
# Vérification statut DA dans Sage X3
# ──────────────────────────────────────────────────────────

def verifier_statut_da_x3(numero_da: str, code_article: str = None) -> Dict:
    """
    Vérifier le statut d'une DA/ligne dans Sage X3.

    Retourne:
    - statut: 'ok' (peut générer BC), 'solde' (DA soldée), 'non_signe' (pas encore signé)
    - details: infos brutes de X3
    """
    try:
        # Requête Sage X3
        query = """
            SELECT
                PR.PSHNUM_0 AS numero_da,
                PRD.ITMREF_0 AS article,
                PRD.LINAPPFLG_0 AS signee,
                PRD.LINCLEFLG_0 AS ligne_solde,
                PR.CLEFLG_0 AS da_solde
            FROM BASE1.PREQUIS PR
            INNER JOIN BASE1.PREQUISD PRD ON PR.PSHNUM_0 = PRD.PSHNUM_0
            WHERE PR.PSHNUM_0 = :numero_da
        """
        params = {"numero_da": numero_da}

        # Si code_article spécifié, filtrer sur l'article
        if code_article:
            query += " AND PRD.ITMREF_0 = :code_article"
            params["code_article"] = code_article

        rows = execute_x3_query(query, params)

        if not rows:
            # DA non trouvée dans X3 - on laisse passer (peut-être nouveau)
            logging.warning(f"DA {numero_da} non trouvée dans Sage X3")
            return {"statut": "ok", "details": None, "message": "DA non trouvée dans X3"}

        # Vérifier le statut (prendre la première ligne ou la ligne de l'article)
        row = rows[0]

        # 1. Vérifier si DA ou ligne soldée
        if row["da_solde"] == X3_SOLDE_OUI or row["ligne_solde"] == X3_SOLDE_OUI:
            return {
                "statut": "solde",
                "details": row,
                "message": f"DA {numero_da} soldée dans X3"
            }

        # 2. Vérifier si ligne non signée
        if row["signee"] == X3_SIGNE_NON:
            return {
                "statut": "non_signe",
                "details": row,
                "message": f"DA {numero_da} non signée (attente signature)"
            }

        # 3. Signé et non soldé = OK pour BC
        return {
            "statut": "ok",
            "details": row,
            "message": f"DA {numero_da} OK (signée={row['signee']}, soldée={row['da_solde']})"
        }

    except Exception as e:
        logging.error(f"Erreur vérification X3 pour DA {numero_da}: {e}")
        # En cas d'erreur de connexion X3, on laisse passer (fail-open)
        return {"statut": "ok", "details": None, "message": f"Erreur X3: {str(e)}"}


def verifier_das_x3_batch(das_articles: List[tuple]) -> Dict[str, Dict]:
    """
    Vérifier plusieurs DA/articles en batch.

    Args:
        das_articles: Liste de tuples (numero_da, code_article)

    Returns:
        Dict avec clé "numero_da|code_article" et valeur le résultat de vérification
    """
    resultats = {}

    # Grouper par DA pour optimiser les requêtes
    das_uniques = set(da for da, _ in das_articles)

    for numero_da in das_uniques:
        try:
            # Récupérer toutes les lignes de cette DA
            query = """
                SELECT
                    PR.PSHNUM_0 AS numero_da,
                    PRD.ITMREF_0 AS article,
                    PRD.LINAPPFLG_0 AS signee,
                    PRD.LINCLEFLG_0 AS ligne_solde,
                    PR.CLEFLG_0 AS da_solde
                FROM BASE1.PREQUIS PR
                INNER JOIN BASE1.PREQUISD PRD ON PR.PSHNUM_0 = PRD.PSHNUM_0
                WHERE PR.PSHNUM_0 = :numero_da
            """
            rows = execute_x3_query(query, {"numero_da": numero_da})

            if not rows:
                # DA non trouvée - marquer tous les articles de cette DA comme OK
                for da, art in das_articles:
                    if da == numero_da:
                        resultats[f"{da}|{art}"] = {
                            "statut": "ok",
                            "details": None,
                            "message": "DA non trouvée dans X3"
                        }
                continue

            # Créer un dict par article
            articles_x3 = {row["article"]: row for row in rows}

            # Vérifier chaque article demandé pour cette DA
            for da, art in das_articles:
                if da != numero_da:
                    continue

                key = f"{da}|{art}"

                if art in articles_x3:
                    row = articles_x3[art]

                    # DA soldée
                    if row["da_solde"] == X3_SOLDE_OUI or row["ligne_solde"] == X3_SOLDE_OUI:
                        resultats[key] = {"statut": "solde", "details": row, "message": "Soldée"}
                    # Non signé
                    elif row["signee"] == X3_SIGNE_NON:
                        resultats[key] = {"statut": "non_signe", "details": row, "message": "Non signé"}
                    # OK
                    else:
                        resultats[key] = {"statut": "ok", "details": row, "message": "OK"}
                else:
                    # Article non trouvé dans cette DA
                    resultats[key] = {"statut": "ok", "details": None, "message": "Article non trouvé"}

        except Exception as e:
            logging.error(f"Erreur batch X3 pour DA {numero_da}: {e}")
            # Marquer tous les articles de cette DA comme OK (fail-open)
            for da, art in das_articles:
                if da == numero_da:
                    resultats[f"{da}|{art}"] = {
                        "statut": "ok",
                        "details": None,
                        "message": f"Erreur X3: {str(e)}"
                    }

    return resultats


def marquer_lignes_soldees_mysql(lignes_cotation_ids: List[int], motif: str = "solde"):
    """Marquer des lignes de cotation comme soldées dans MySQL"""
    if not lignes_cotation_ids:
        return

    placeholders = ",".join(["%s"] * len(lignes_cotation_ids))
    execute_update(
        f"""
        UPDATE lignes_cotation
        SET x3_solde = TRUE,
            x3_date_verification = NOW(),
            x3_motif_exclusion = %s
        WHERE id IN ({placeholders})
        """,
        (motif,) + tuple(lignes_cotation_ids)
    )
    logging.info(f"Marqué {len(lignes_cotation_ids)} lignes comme soldées (motif: {motif})")


def log_verification_x3(numero_da: str, code_article: str, details: Dict, action: str):
    """Logger une vérification X3 pour traçabilité"""
    try:
        execute_insert(
            """
            INSERT INTO logs_verification_x3 (
                numero_da, code_article,
                x3_linappflg, x3_lincleflg, x3_cleflg,
                action_prise
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                numero_da,
                code_article,
                details.get("signee") if details else None,
                details.get("ligne_solde") if details else None,
                details.get("da_solde") if details else None,
                action
            )
        )
    except Exception as e:
        logging.warning(f"Erreur log vérification X3: {e}")


def get_tarifs_articles_x3(codes_articles: List[str]) -> Dict[str, float]:
    """
    Récupérer les tarifs des articles depuis Sage X3.

    Returns:
        Dict avec code_article comme clé et tarif (PRI_0) comme valeur
    """
    if not codes_articles:
        return {}

    tarifs = {}

    try:
        # Requête pour récupérer les tarifs
        # On utilise IN pour récupérer plusieurs articles en une requête
        placeholders = ", ".join([f":art_{i}" for i in range(len(codes_articles))])
        params = {f"art_{i}": code for i, code in enumerate(codes_articles)}

        query = f"""
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
                WHERE PPRICLIST.PLICRI1_0 IN ({placeholders})
            )
            SELECT code_article, tarif
            FROM CTE
            WHERE rang = 1;
        """

        rows = execute_x3_query(query, params)

        if rows:
            for row in rows:
                tarifs[row["code_article"]] = float(row["tarif"]) if row["tarif"] else 0.0

        logging.info(f"Récupéré {len(tarifs)} tarifs depuis X3")

    except Exception as e:
        logging.error(f"Erreur récupération tarifs X3: {e}")

    return tarifs


def verifier_prix_vs_tarif_x3(offres: List[dict]) -> tuple[List[dict], List[str]]:
    """
    Vérifier que le prix fournisseur est <= tarif X3 pour chaque article.

    Returns:
        (offres_valides, articles_prix_superieur)
    """
    if not offres:
        return [], []

    # Extraire les codes articles uniques
    codes_articles = list(set(row["code_article"] for row in offres))

    # Récupérer les tarifs X3
    tarifs_x3 = get_tarifs_articles_x3(codes_articles)

    offres_valides = []
    articles_prix_superieur = []

    for row in offres:
        code_article = row["code_article"]
        prix_fournisseur = float(row["prix_unitaire_ht"])

        # Récupérer le tarif X3 (0 si non trouvé = pas de limite)
        tarif_x3 = tarifs_x3.get(code_article, 0.0)

        if tarif_x3 > 0 and prix_fournisseur > tarif_x3:
            # Prix fournisseur supérieur au tarif X3 → exclure
            articles_prix_superieur.append(
                f"{row['numero_da']}/{code_article} (prix={prix_fournisseur:.2f} > tarif={tarif_x3:.2f})"
            )
            logging.debug(f"Article {code_article} exclu: prix {prix_fournisseur} > tarif X3 {tarif_x3}")
        else:
            # Prix OK ou pas de tarif X3 → garder
            offres_valides.append(row)

    if articles_prix_superieur:
        logging.info(f"Exclu {len(articles_prix_superieur)} articles avec prix > tarif X3")

    return offres_valides, articles_prix_superieur


# ──────────────────────────────────────────────────────────
# Validation des marques dans Sage X3
# ──────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────
# Fonctions utilitaires
# ──────────────────────────────────────────────────────────


def get_offres_eligibles(config: AutoBCConfig) -> List[dict]:
    """
    Récupérer toutes les offres éligibles pour Auto BC.
    Critères :
    - Famille = config.code_famille
    - Prix < prix_base (tarif référence)
    - Marque = marque_souhaitee
    - Réponse dans les dernières X heures
    - Pas déjà commandé
    """

    # Recuperer les DA non soldees dans X3

    

    query = """
        SELECT
            -- Article
            ar.code_article,
            ar.designation,
            ar.prix_base AS tarif_reference,
            ar.code_famille,

            -- Demande
            lc.id AS ligne_cotation_id,
            lc.quantite_demandee,
            lc.marque_souhaitee,
            lc.numero_da,
            dc.numero_rfq,

            -- Réponse fournisseur
            rd.id AS detail_id,
            rd.prix_unitaire_ht,
            rd.quantite_disponible,
            rd.marque_proposee,
            rd.date_livraison AS delai_livraison,
            rfe.id AS reponse_entete_id,
            rfe.date_reponse,

            -- Fournisseur
            f.code_fournisseur,
            f.nom_fournisseur,
            f.email AS email_fournisseur,
            f.telephone AS telephone_fournisseur

        FROM articles_ref ar

        -- Jointure vers lignes de cotation
        INNER JOIN lignes_cotation lc
            ON lc.code_article = ar.code_article
            AND (lc.actif = TRUE OR lc.actif IS NULL)

        -- Jointure vers réponses détail
        INNER JOIN reponses_fournisseurs_detail rd
            ON rd.ligne_cotation_id = lc.id

        -- Jointure vers réponses entête
        INNER JOIN reponses_fournisseurs_entete rfe
            ON rfe.id = rd.reponse_entete_id

        -- Jointure vers demande de cotation (pour avoir le fournisseur)
        INNER JOIN demandes_cotation dc
            ON dc.uuid = rfe.rfq_uuid

        -- Jointure vers fournisseur
        INNER JOIN fournisseurs f
            ON f.code_fournisseur = dc.code_fournisseur
            AND f.statut = 'actif'
            AND f.blacklist = 0

        WHERE
            -- Exclure les lignes déjà marquées comme soldées dans X3
            (lc.x3_solde = FALSE OR lc.x3_solde IS NULL)

            -- Pas déjà commandé
            # AND NOT EXISTS (
            #     SELECT 1 FROM lignes_bon_commande lbc
            #     WHERE lbc.ligne_source_id = rd.id
            # )
            AND rd.prix_unitaire_ht > 0
            AND rd.quantite_disponible > 0
            -- AND rd.marque_proposee is not NULL
        ORDER BY
            ar.code_article,
            lc.numero_da
    """

    results = execute_query(query)
    return results or []


# ──────────────────────────────────────────────────────────
# Endpoint : Preview (dry-run)
# ──────────────────────────────────────────────────────────

@router.get("/data", response_model=list[dict], summary="Prévisualisation des BC (dry-run)", tags=["Auto BC"])
async def preview_auto_bc(
    code_famille: str = Query(default="46", description="Code famille à traiter"),
    periode_heures: int = Query(default=24, description="Période de collecte (heures)")
):
    """
    Prévisualisation des BC qui seraient créés (sans les créer réellement).
    Permet de vérifier avant l'exécution automatique.
    Inclut une analyse détaillée pour comprendre les exclusions.
    """

    config = AutoBCConfig(
        code_famille=code_famille,
        periode_heures=periode_heures,
        dry_run=True
    )

    # ══════════════════════════════════════════════════════════
    # INITIALISER L'ANALYSE
    # ══════════════════════════════════════════════════════════
    analyse = AnalyseAutoBC()

    # Récupérer les offres éligibles
    offres_raw = get_offres_eligibles(config)

    if not offres_raw:
        analyse.resume = "Aucune réponse fournisseur trouvée pour les critères de recherche."
        return AutoBCPreviewResponse(
            config=config,
            date_preview=datetime.now(),
            nb_articles_eligibles=0,
            nb_articles_avec_offre_complete=0,
            nb_articles_avec_offre_partielle=0,
            nb_articles_sans_offre=0,
            bcs_preview=[],
            nb_bc_a_creer=0,
            articles_sans_offre=[],
            economie_totale_estimee=0.0,
            analyse=analyse
        )

    # ══════════════════════════════════════════════════════════
    # 1. COLLECTER TOUTES LES RÉPONSES CONSULTÉES
    # ══════════════════════════════════════════════════════════
    analyse.nb_reponses_consultees = len(offres_raw)
    for row in offres_raw:
        analyse.reponses_consultees.append(AnalyseReponseConsultee(
            detail_id=row.get("detail_id") or row.get("id") or 0,
            numero_da=row["numero_da"],
            code_article=row["code_article"],
            designation_article=row.get("designation"),
            code_fournisseur=row["code_fournisseur"],
            nom_fournisseur=row.get("nom_fournisseur"),
            prix_unitaire_ht=float(row["prix_unitaire_ht"]) if row.get("prix_unitaire_ht") else 0,
            quantite_disponible=float(row["quantite_disponible"]) if row.get("quantite_disponible") else 0,
            marque_proposee=row.get("marque_proposee"),
            date_reponse=row["date_reponse"],
            incluse=True,  # Par défaut incluse, sera mis à jour si exclue
            raison_exclusion=None
        ))

    # ══════════════════════════════════════════════════════════
    # 2. VÉRIFICATION STATUT DA DANS SAGE X3
    # ══════════════════════════════════════════════════════════
    logging.info("[Preview] Vérification des statuts DA dans Sage X3...")

    # Extraire les paires (numero_da, code_article) uniques
    das_articles = list(set(
        (row["numero_da"], row["code_article"])
        for row in offres_raw
    ))

    # Vérifier en batch dans X3
    statuts_x3 = verifier_das_x3_batch(das_articles)

    # Filtrer les offres selon le statut X3
    offres_filtrees = []
    lignes_a_marquer_solde = []
    das_soldees_set = set()  # Pour compter les DA distinctes soldées
    das_non_signees_set = set()  # Pour compter les DA distinctes non signées

    for row in offres_raw:
        key = f"{row['numero_da']}|{row['code_article']}"
        statut_x3 = statuts_x3.get(key, {"statut": "ok"})
        details = statut_x3.get("details", {}) or {}

        # Enregistrer le statut DA dans l'analyse
        analyse.statuts_da.append(AnalyseStatutDA(
            numero_da=row["numero_da"],
            code_article=row["code_article"],
            statut_x3=statut_x3["statut"],
            x3_signee=details.get("signee") if details else None,
            x3_ligne_solde=details.get("ligne_solde") if details else None,
            x3_da_solde=details.get("da_solde") if details else None,
            message=statut_x3.get("message", "")
        ))

        if statut_x3["statut"] == "solde":
            # DA soldée → marquer dans MySQL et exclure
            analyse.nb_da_soldees += 1
            das_soldees_set.add(row["numero_da"])  # Ajouter au set pour compter les distinctes
            lignes_a_marquer_solde.append(row["ligne_cotation_id"])
            log_verification_x3(row["numero_da"], row["code_article"], details, "solde")

            # Marquer comme exclue dans l'analyse
            for rep in analyse.reponses_consultees:
                if rep.numero_da == row["numero_da"] and rep.code_article == row["code_article"]:
                    rep.incluse = False
                    rep.raison_exclusion = "DA soldée dans Sage X3"

        elif statut_x3["statut"] == "non_signe":
            # Non signé → exclure sans marquer
            analyse.nb_da_non_signees += 1
            das_non_signees_set.add(row["numero_da"])  # Ajouter au set pour compter les distinctes
            log_verification_x3(row["numero_da"], row["code_article"], details, "ignore_non_signe")

            # Marquer comme exclue dans l'analyse
            for rep in analyse.reponses_consultees:
                if rep.numero_da == row["numero_da"] and rep.code_article == row["code_article"]:
                    rep.incluse = False
                    rep.raison_exclusion = "DA non signée dans Sage X3"

        else:
            # OK → garder l'offre
            analyse.nb_da_ok += 1
            offres_filtrees.append(row)

    # Mettre à jour les compteurs distincts
    analyse.nb_da_soldees_distinct = len(das_soldees_set)
    analyse.nb_da_non_signees_distinct = len(das_non_signees_set)

    # Marquer les lignes soldées dans MySQL
    if lignes_a_marquer_solde:
        marquer_lignes_soldees_mysql(lignes_a_marquer_solde, "solde")
        logging.info(f"[Preview] Marqué {len(lignes_a_marquer_solde)} lignes comme soldées")

    # Remplacer offres_raw par les offres filtrées
    offres_raw = offres_filtrees
    logging.info(f"[Preview] Après filtrage statut X3: {len(offres_raw)} offres restantes")
    return offres_raw
    # return AutoBCPreviewResponse(
    #     config=config,
    #     date_preview=datetime.now(),
    #     nb_articles_eligibles=len(set(f"{row['code_article']}_{row['numero_da']}" for row in offres_raw)),
    #     nb_articles_avec_offre_complete=sum(1 for row in offres_raw if float(row["quantite_disponible"]) >= float(row["quantite_demandee"])),
    #     nb_articles_avec_offre_partielle=sum(1 for row in offres_raw if float(row["quantite_disponible"]) < float(row["quantite_demandee"])),
    #     nb_articles_sans_offre=0,  # À calculer plus tard si nécessaire 
    #      bcs_preview=[],  # À remplir plus tard si nécessaire
    #     nb_bc_a_creer=0,  # À calculer plus tard si nécessaire
    #     articles_sans_offre=[],  # À remplir plus tard si nécessaire
    #     economie_totale_estimee=0.0,  # À calculer plus tard si nécessaire
    #     analyse=analyse
    # )