"""
════════════════════════════════════════════════════════════
ROUTER - Auto BC (Génération automatique de bons de commande)
════════════════════════════════════════════════════════════
Génération automatique de BC pour la famille mécanique (46)
basée sur scoring prix + délai avec priorité quantité complète
"""

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
    LogAutoBCListResponse
)


router = APIRouter(prefix="/auto-bc", tags=["Auto BC"])


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
            SELECT
                ITMMASTER.ITMREF_0 AS code_article,
                PPRICLIST.PRI_0 AS tarif
            FROM BASE1.PPRICLIST PPRICLIST
            INNER JOIN BASE1.ITMMASTER ITMMASTER
                ON PPRICLIST.PLICRI1_0 = ITMMASTER.ITMREF_0
            WHERE ITMMASTER.ITMREF_0 IN ({placeholders})
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
# Fonctions utilitaires
# ──────────────────────────────────────────────────────────

def calculer_score(prix: float, prix_base: float, delai: Optional[int], config: AutoBCConfig) -> float:
    """
    Calculer le score d'une offre.
    Score = (poids_prix * score_prix) + (poids_delai * score_delai)
    """
    # Score prix : plus le prix est bas par rapport au prix_base, plus le score est élevé
    if prix_base > 0:
        score_prix = max(0, 1 - (prix / prix_base))
    else:
        score_prix = 0

    # Score délai : plus le délai est court, plus le score est élevé
    if delai is not None and delai > 0:
        score_delai = max(0, 1 - (delai / config.delai_max_jours))
    else:
        # Si pas de délai spécifié, on considère un score moyen
        score_delai = 0.5

    # Score total
    score = (config.poids_prix * score_prix) + (config.poids_delai * score_delai)

    return round(score, 2)


def calculer_economie(prix: float, prix_base: float) -> float:
    """Calculer le pourcentage d'économie par rapport au prix de base"""
    if prix_base > 0:
        return round((prix_base - prix) / prix_base * 100, 2)
    return 0.0


async def envoyer_rpa_fournisseur(
    code_fournisseur: str,
    nom_fournisseur: str,
    email_fournisseur: str,
    tel_fournisseur: str,
    lignes_bc: List[dict],
    email_acheteur: str,
    acheteur: str,
    numero_bc: str
) -> tuple[bool, str]:
    """
    Envoyer les données d'un seul fournisseur au service RPA.
    Retourne (success: bool, message: str)
    """
    donnees_rpa = []

    for ligne in lignes_bc:
        offre = ligne["offre"]
        donnees_rpa.append({
            "Numero_DA": offre.numero_da,
            "Acheteur": acheteur,
            "Code_Fournisseur": code_fournisseur,
            "Email_Fournisseur": email_fournisseur or "",
            "TEL_Fournisseur": tel_fournisseur or "",
            "Code_Article": offre.code_article,
            "Montant": float(offre.prix_unitaire_ht),
            "Marque": offre.marque_proposee or "",
            "Affaire": ""
        })

    rpa_payload = {
        "donnees": donnees_rpa,
        "email_expediteur": email_acheteur,
        "headless": True
    }
    print(rpa_payload)
    logging.info(f"Envoi RPA pour fournisseur {code_fournisseur} (BC: {numero_bc}): {len(donnees_rpa)} ligne(s)")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                RPA_API_URL,
                json=rpa_payload,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 200:
                logging.info(f"RPA OK pour fournisseur {code_fournisseur} (BC: {numero_bc})")
                return True, f"RPA succes pour {code_fournisseur}"
            else:
                msg = f"RPA erreur {response.status_code} pour {code_fournisseur}: {response.text}"
                logging.error(msg)
                return False, msg

    except httpx.TimeoutException:
        msg = f"RPA timeout pour fournisseur {code_fournisseur}"
        logging.error(msg)
        return False, msg
    except Exception as e:
        msg = f"RPA exception pour {code_fournisseur}: {str(e)}"
        logging.error(msg)
        return False, msg


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
            AND NOT EXISTS (
                SELECT 1 FROM lignes_bon_commande lbc
                WHERE lbc.ligne_source_id = rd.id
            )
            AND rd.prix_unitaire_ht > 0
            AND rd.quantite_disponible > 0
            AND rd.marque_proposee is not NULL
        ORDER BY
            ar.code_article,
            lc.numero_da
    """

    results = execute_query(query)
    print(results)
    return results or []


def grouper_offres_par_article(offres_raw: List[dict], config: AutoBCConfig) -> Dict[str, ArticleAvecOffres]:
    """
    Grouper les offres par article et calculer les scores.
    Séparer en offres complètes vs partielles.
    """
    articles_dict: Dict[str, ArticleAvecOffres] = {}

    for row in offres_raw:
        # Clé unique pour l'article (code_article + numero_da)
        key = f"{row['code_article']}_{row['numero_da']}"

        # Créer l'article si pas encore présent
        if key not in articles_dict:
            articles_dict[key] = ArticleAvecOffres(
                code_article=row["code_article"],
                designation_article=row["designation"],
                numero_da=row["numero_da"],
                quantite_demandee=float(row["quantite_demandee"]),
                tarif_reference=float(row["tarif_reference"]),
                marque_souhaitee=row["marque_souhaitee"],
                offres_completes=[],
                offres_partielles=[]
            )

        article = articles_dict[key]
        quantite_demandee = article.quantite_demandee
        quantite_disponible = float(row["quantite_disponible"]) if row["quantite_disponible"] else 0

        # Déterminer si livraison complète ou partielle
        type_livraison = TypeLivraison.COMPLET if quantite_disponible >= quantite_demandee else TypeLivraison.PARTIEL
        delai = 1
        if row["delai_livraison"] is not None:
            delai = (datetime.now() - row["delai_livraison"]).days  # Ajouter .days
        # Calculer le score
        score = calculer_score(
            prix=float(row["prix_unitaire_ht"]),
            prix_base=float(row["tarif_reference"]),
            delai=delai,
            config=config
        )
    
        # Créer l'offre éligible
        offre = OffreEligible(
            detail_id=row["detail_id"],
            ligne_cotation_id=row["ligne_cotation_id"],
            reponse_entete_id=row["reponse_entete_id"],
            code_article=row["code_article"],
            designation_article=row["designation"],
            numero_da=row["numero_da"],
            numero_rfq=row["numero_rfq"],
            quantite_demandee=quantite_demandee,
            marque_souhaitee=row["marque_souhaitee"],
            tarif_reference=float(row["tarif_reference"]),
            code_fournisseur=row["code_fournisseur"],
            nom_fournisseur=row["nom_fournisseur"],
            email_fournisseur=row.get("email_fournisseur"),
            telephone_fournisseur=row.get("telephone_fournisseur"),
            prix_unitaire_ht=float(row["prix_unitaire_ht"]),
            quantite_disponible=quantite_disponible,
            marque_proposee=row["marque_proposee"],
            # delai_livraison=row["delai_livraison"],
            date_reponse=row["date_reponse"],
            type_livraison=type_livraison,
            score=score,
            economie_pourcent=calculer_economie(float(row["prix_unitaire_ht"]), float(row["tarif_reference"]))
        )

        # Ajouter à la bonne liste
        if type_livraison == TypeLivraison.COMPLET:
            article.offres_completes.append(offre)
        else:
            article.offres_partielles.append(offre)

    # Trier les offres par score décroissant et sélectionner la meilleure
    for article in articles_dict.values():
        # Trier les offres complètes par score
        article.offres_completes.sort(key=lambda x: x.score, reverse=True)
        # Trier les offres partielles par score
        article.offres_partielles.sort(key=lambda x: x.score, reverse=True)

        # Sélectionner la meilleure offre : priorité aux complètes
        if article.offres_completes:
            article.offre_selectionnee = article.offres_completes[0]
        elif article.offres_partielles:
            article.offre_selectionnee = article.offres_partielles[0]

    return articles_dict


def grouper_par_fournisseur(articles: Dict[str, ArticleAvecOffres]) -> Dict[str, List[ArticleAvecOffres]]:
    """Grouper les articles sélectionnés par fournisseur pour créer les BC"""
    fournisseurs_dict: Dict[str, List[ArticleAvecOffres]] = {}

    for article in articles.values():
        if article.offre_selectionnee:
            code_fournisseur = article.offre_selectionnee.code_fournisseur
            if code_fournisseur not in fournisseurs_dict:
                fournisseurs_dict[code_fournisseur] = []
            fournisseurs_dict[code_fournisseur].append(article)

    return fournisseurs_dict


# ──────────────────────────────────────────────────────────
# Endpoint : Preview (dry-run)
# ──────────────────────────────────────────────────────────

@router.get("/preview", response_model=AutoBCPreviewResponse)
async def preview_auto_bc(
    code_famille: str = Query(default="46", description="Code famille à traiter"),
    periode_heures: int = Query(default=24, description="Période de collecte (heures)"),
    current_user: dict = Depends(get_current_user)
):
    """
    Prévisualisation des BC qui seraient créés (sans les créer réellement).
    Permet de vérifier avant l'exécution automatique.
    """

    config = AutoBCConfig(
        code_famille=code_famille,
        periode_heures=periode_heures,
        dry_run=True
    )

    # Récupérer les offres éligibles
    offres_raw = get_offres_eligibles(config)

    if not offres_raw:
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
            economie_totale_estimee=0.0
        )

    # ══════════════════════════════════════════════════════════
    # VÉRIFICATION STATUT DA DANS SAGE X3 (aussi en preview)
    # ══════════════════════════════════════════════════════════
    logging.info("[Preview] Vérification des statuts DA dans Sage X3...")

    # Extraire les paires (numero_da, code_article) uniques
    das_articles = list(set(
        (row["numero_da"], row["code_article"])
        for row in offres_raw
    ))

    # Vérifier en batch dans X3
    statuts_x3 = verifier_das_x3_batch(das_articles)
    print(f"Statuts X3: {statuts_x3}")
    # Filtrer les offres selon le statut X3
    offres_filtrees = []
    lignes_a_marquer_solde = []

    for row in offres_raw:
        key = f"{row['numero_da']}|{row['code_article']}"
        statut_x3 = statuts_x3.get(key, {"statut": "ok"})

        if statut_x3["statut"] == "solde":
            # DA soldée → marquer dans MySQL et exclure
            lignes_a_marquer_solde.append(row["ligne_cotation_id"])
            log_verification_x3(row["numero_da"], row["code_article"], statut_x3.get("details"), "solde")

        elif statut_x3["statut"] == "non_signe":
            # Non signé → exclure sans marquer
            log_verification_x3(row["numero_da"], row["code_article"], statut_x3.get("details"), "ignore_non_signe")

        else:
            # OK → garder l'offre
            offres_filtrees.append(row)

    # Marquer les lignes soldées dans MySQL
    if lignes_a_marquer_solde:
        marquer_lignes_soldees_mysql(lignes_a_marquer_solde, "solde")
        logging.info(f"[Preview] Marqué {len(lignes_a_marquer_solde)} lignes comme soldées")

    # Remplacer offres_raw par les offres filtrées
    offres_raw = offres_filtrees
    logging.info(f"[Preview] Après filtrage statut X3: {len(offres_raw)} offres restantes")

    # ══════════════════════════════════════════════════════════
    # VÉRIFICATION PRIX VS TARIF X3
    # ══════════════════════════════════════════════════════════
    if offres_raw:
        logging.info("[Preview] Vérification prix vs tarif X3...")
        offres_raw, articles_prix_sup = verifier_prix_vs_tarif_x3(offres_raw)
        if articles_prix_sup:
            logging.info(f"[Preview] Exclu {len(articles_prix_sup)} articles (prix > tarif X3)")
        logging.info(f"[Preview] Après filtrage prix: {len(offres_raw)} offres restantes")

    # ══════════════════════════════════════════════════════════

    if not offres_raw:
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
            economie_totale_estimee=0.0
        )

    # Grouper par article
    articles = grouper_offres_par_article(offres_raw, config)

    # Statistiques
    nb_complets = sum(1 for a in articles.values() if a.offres_completes)
    nb_partiels = sum(1 for a in articles.values() if not a.offres_completes and a.offres_partielles)
    nb_sans_offre = sum(1 for a in articles.values() if not a.offre_selectionnee)

    # Grouper par fournisseur pour créer les BC preview
    fournisseurs = grouper_par_fournisseur(articles)

    # Construire les BC preview
    bcs_preview = []
    economie_totale = 0.0

    for code_fournisseur, articles_list in fournisseurs.items():
        lignes = []
        montant_ht = 0.0
        das_incluses = set()

        for article in articles_list:
            offre = article.offre_selectionnee
            if offre:
                # Quantité à commander
                qte = min(offre.quantite_disponible, article.quantite_demandee)
                montant_ligne = qte * offre.prix_unitaire_ht

                lignes.append(BCPreviewLigne(
                    code_article=article.code_article,
                    designation_article=article.designation_article,
                    numero_da=article.numero_da,
                    quantite_commandee=qte,
                    prix_unitaire_ht=offre.prix_unitaire_ht,
                    montant_ligne_ht=round(montant_ligne, 2),
                    type_livraison=offre.type_livraison,
                    score=offre.score,
                    economie_pourcent=offre.economie_pourcent,
                    delai_livraison=offre.delai_livraison
                ))

                montant_ht += montant_ligne
                das_incluses.add(article.numero_da)

                # Économie
                economie_ligne = (article.tarif_reference - offre.prix_unitaire_ht) * qte
                economie_totale += economie_ligne

        if lignes:
            nom_fournisseur = articles_list[0].offre_selectionnee.nom_fournisseur if articles_list else ""
            montant_tva = montant_ht * 0.20
            montant_ttc = montant_ht + montant_tva

            bcs_preview.append(BCPreview(
                code_fournisseur=code_fournisseur,
                nom_fournisseur=nom_fournisseur,
                lignes=lignes,
                nb_lignes=len(lignes),
                montant_total_ht=round(montant_ht, 2),
                montant_tva=round(montant_tva, 2),
                montant_total_ttc=round(montant_ttc, 2),
                das_incluses=list(das_incluses)
            ))

    return AutoBCPreviewResponse(
        config=config,
        date_preview=datetime.now(),
        nb_articles_eligibles=len(articles),
        nb_articles_avec_offre_complete=nb_complets,
        nb_articles_avec_offre_partielle=nb_partiels,
        nb_articles_sans_offre=nb_sans_offre,
        bcs_preview=bcs_preview,
        nb_bc_a_creer=len(bcs_preview),
        articles_sans_offre=[a.code_article for a in articles.values() if not a.offre_selectionnee],
        economie_totale_estimee=round(economie_totale, 2)
    )


# ──────────────────────────────────────────────────────────
# Endpoint : Exécution
# ──────────────────────────────────────────────────────────

@router.post("/executer", response_model=AutoBCExecuteResponse)
async def executer_auto_bc(
    request: AutoBCExecuteRequest = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Exécuter la génération automatique des BC.
    Crée réellement les bons de commande dans la base.
    """
    start_time = time.time()

    # Config par défaut si non fournie
    config = request.config if request and request.config else AutoBCConfig()
    execute_par = request.execute_par if request else current_user.get("username", "SYSTEM")

    bcs_crees = []
    articles_partiels = []
    articles_sans_offre = []
    erreurs = []
    economie_totale = 0.0

    try:
        # Récupérer les offres éligibles
        offres_raw = get_offres_eligibles(config)
        print(f"Offres brutes récupérées: {len(offres_raw) if offres_raw else 0}")

        if not offres_raw:
            # Pas d'offres éligibles
            duree_ms = int((time.time() - start_time) * 1000)
            log_id = execute_insert("""
                INSERT INTO logs_auto_bc (
                    date_execution, code_famille, periode_heures,
                    nb_articles_eligibles, nb_articles_traites, nb_bc_crees,
                    statut, execute_par, duree_execution_ms
                ) VALUES (NOW(), %s, %s, 0, 0, 0, 'succes', %s, %s)
            """, (config.code_famille, config.periode_heures, execute_par, duree_ms))

            return AutoBCExecuteResponse(
                success=True,
                statut=StatutExecution.SUCCES,
                message="Aucune offre éligible trouvée",
                date_execution=datetime.now(),
                duree_execution_ms=duree_ms,
                config=config,
                execute_par=execute_par,
                nb_articles_eligibles=0,
                nb_articles_traites=0,
                nb_bc_crees=0,
                bcs_crees=[],
                economie_totale=0.0,
                log_id=log_id
            )

        # ══════════════════════════════════════════════════════════
        # VÉRIFICATION STATUT DA DANS SAGE X3
        # ══════════════════════════════════════════════════════════
        logging.info("Vérification des statuts DA dans Sage X3...")

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
        articles_non_signes = []
        articles_soldes = []

        for row in offres_raw:
            key = f"{row['numero_da']}|{row['code_article']}"
            statut_x3 = statuts_x3.get(key, {"statut": "ok"})

            if statut_x3["statut"] == "solde":
                # DA soldée → marquer dans MySQL et exclure
                lignes_a_marquer_solde.append(row["ligne_cotation_id"])
                articles_soldes.append(f"{row['numero_da']}/{row['code_article']}")
                log_verification_x3(row["numero_da"], row["code_article"], statut_x3.get("details"), "solde")

            elif statut_x3["statut"] == "non_signe":
                # Non signé → exclure sans marquer (peut-être signé demain)
                articles_non_signes.append(f"{row['numero_da']}/{row['code_article']}")
                log_verification_x3(row["numero_da"], row["code_article"], statut_x3.get("details"), "ignore_non_signe")

            else:
                # OK → garder l'offre
                offres_filtrees.append(row)
                log_verification_x3(row["numero_da"], row["code_article"], statut_x3.get("details"), "ok")

        # Marquer les lignes soldées dans MySQL (pour ne plus les récupérer)
        if lignes_a_marquer_solde:
            marquer_lignes_soldees_mysql(lignes_a_marquer_solde, "solde")
            logging.info(f"Marqué {len(lignes_a_marquer_solde)} lignes comme soldées")

        if articles_non_signes:
            logging.info(f"Ignoré {len(articles_non_signes)} articles non signés: {articles_non_signes[:5]}...")

        if articles_soldes:
            logging.info(f"Exclu {len(articles_soldes)} articles soldés: {articles_soldes[:5]}...")

        # Remplacer offres_raw par les offres filtrées
        offres_raw = offres_filtrees
        logging.info(f"Après filtrage statut X3: {len(offres_raw)} offres restantes")

        # ══════════════════════════════════════════════════════════
        # VÉRIFICATION PRIX VS TARIF X3
        # ══════════════════════════════════════════════════════════
        if offres_raw:
            logging.info("Vérification prix vs tarif X3...")
            offres_raw, articles_prix_sup = verifier_prix_vs_tarif_x3(offres_raw)
            if articles_prix_sup:
                logging.info(f"Exclu {len(articles_prix_sup)} articles (prix > tarif X3): {articles_prix_sup[:5]}...")
            logging.info(f"Après filtrage prix: {len(offres_raw)} offres restantes")

        # ══════════════════════════════════════════════════════════

        if not offres_raw:
            # Pas d'offres éligibles
            duree_ms = int((time.time() - start_time) * 1000)

            # Log l'exécution
            log_id = execute_insert("""
                INSERT INTO logs_auto_bc (
                    date_execution, code_famille, periode_heures,
                    nb_articles_eligibles, nb_articles_traites, nb_bc_crees,
                    statut, execute_par, duree_execution_ms
                ) VALUES (NOW(), %s, %s, 0, 0, 0, 'succes', %s, %s)
            """, (config.code_famille, config.periode_heures, execute_par, duree_ms))

            return AutoBCExecuteResponse(
                success=True,
                statut=StatutExecution.SUCCES,
                message="Aucune offre éligible trouvée",
                date_execution=datetime.now(),
                duree_execution_ms=duree_ms,
                config=config,
                execute_par=execute_par,
                nb_articles_eligibles=0,
                nb_articles_traites=0,
                nb_bc_crees=0,
                bcs_crees=[],
                economie_totale=0.0,
                log_id=log_id
            )

        # Grouper par article
        articles = grouper_offres_par_article(offres_raw, config)

        # Collecter les articles partiels et sans offre
        for article in articles.values():
            if article.offre_selectionnee:
                if article.offre_selectionnee.type_livraison == TypeLivraison.PARTIEL:
                    articles_partiels.append(article.code_article)
            else:
                articles_sans_offre.append(article.code_article)

        # Grouper par fournisseur
        fournisseurs = grouper_par_fournisseur(articles)

        # Créer les BC
        year = datetime.now().year
        print("ss")

        for code_fournisseur, articles_list in fournisseurs.items():
            try:
                # Générer le numéro de BC
                last_bc = execute_query(
                    "SELECT numero_bc FROM bons_commande WHERE numero_bc LIKE %s ORDER BY id DESC LIMIT 1",
                    (f"BC-{year}-%",),
                    fetch_one=True
                )
                if last_bc:
                    last_num = int(last_bc["numero_bc"].split("-")[-1])
                    new_num = last_num + 1
                else:
                    new_num = 1

                numero_bc = f"BC-{year}-{new_num:04d}"

                # Calculer les totaux
                montant_total_ht = 0.0
                das_incluses = set()
                lignes_bc = []

                for article in articles_list:
                    offre = article.offre_selectionnee
                    if offre:
                        qte = min(offre.quantite_disponible, article.quantite_demandee)
                        montant_ligne_ht = qte * offre.prix_unitaire_ht
                        montant_total_ht += montant_ligne_ht
                        das_incluses.add(article.numero_da)

                        lignes_bc.append({
                            "offre": offre,
                            "quantite": qte,
                            "montant_ligne_ht": montant_ligne_ht
                        })

                        # Économie
                        economie_ligne = (article.tarif_reference - offre.prix_unitaire_ht) * qte
                        economie_totale += economie_ligne

                montant_tva = montant_total_ht * 0.20
                montant_total_ttc = montant_total_ht + montant_tva

                # Créer le BC
                execute_query("""
                    INSERT INTO bons_commande (
                        numero_bc, code_fournisseur,
                        date_creation, montant_total_ht, montant_tva, montant_total_ttc,
                        devise, statut, creee_par
                    ) VALUES (%s, %s, NOW(), %s, %s, %s, 'MAD', 'auto_genere', %s)
                """, (
                    numero_bc,
                    code_fournisseur,
                    round(montant_total_ht, 2),
                    round(montant_tva, 2),
                    round(montant_total_ttc, 2),
                    execute_par
                ))

                # Créer les lignes
                for ligne_data in lignes_bc:
                    offre = ligne_data["offre"]
                    qte = ligne_data["quantite"]
                    montant_ligne_ht = ligne_data["montant_ligne_ht"]
                    montant_ligne_ttc = montant_ligne_ht * 1.20

                    execute_query("""
                        INSERT INTO lignes_bon_commande (
                            numero_bc, ligne_source_id, reponse_id,
                            numero_da, numero_rfq,
                            code_article, designation, quantite, unite,
                            prix_unitaire_ht, montant_ligne_ht, tva_pourcent, montant_ligne_ttc,
                            date_livraison_prevue, commentaire
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        numero_bc,
                        offre.detail_id,
                        offre.reponse_entete_id,
                        offre.numero_da,
                        offre.numero_rfq,
                        offre.code_article,
                        offre.designation_article,
                        qte,
                        None,  # unite
                        offre.prix_unitaire_ht,
                        round(montant_ligne_ht, 2),
                        20.0,
                        round(montant_ligne_ttc, 2),
                        None,  # date_livraison_prevue
                        f"Auto BC - Score: {offre.score}"
                    ))

                # Récupérer les infos fournisseur pour le RPA
                nom_fournisseur = articles_list[0].offre_selectionnee.nom_fournisseur if articles_list else ""
                email_fournisseur = articles_list[0].offre_selectionnee.email_fournisseur if articles_list else ""
                tel_fournisseur = articles_list[0].offre_selectionnee.telephone_fournisseur if articles_list else ""

                # Appeler le service RPA pour ce fournisseur (envoi séparé par fournisseur)
                rpa_success, rpa_message = await envoyer_rpa_fournisseur(
                    code_fournisseur=code_fournisseur,
                    nom_fournisseur=nom_fournisseur,
                    email_fournisseur=email_fournisseur or "",
                    tel_fournisseur=tel_fournisseur or "",
                    lignes_bc=lignes_bc,
                    email_acheteur=current_user.get("email", ""),
                    acheteur=execute_par,
                    numero_bc=numero_bc
                )

                if not rpa_success:
                    erreurs.append(f"RPA {code_fournisseur}: {rpa_message}")

                # Ajouter au résultat
                bcs_crees.append(BCCree(
                    numero_bc=numero_bc,
                    code_fournisseur=code_fournisseur,
                    nom_fournisseur=nom_fournisseur,
                    nb_lignes=len(lignes_bc),
                    montant_total_ht=round(montant_total_ht, 2),
                    montant_total_ttc=round(montant_total_ttc, 2),
                    das_incluses=list(das_incluses)
                ))

            except Exception as e:
                erreurs.append(f"Erreur création BC pour {code_fournisseur}: {str(e)}")

        # Calculer la durée
        duree_ms = int((time.time() - start_time) * 1000)

        # Déterminer le statut
        if erreurs:
            statut = StatutExecution.PARTIEL if bcs_crees else StatutExecution.ECHEC
        else:
            statut = StatutExecution.SUCCES

        # Log l'exécution
        log_id = execute_insert("""
            INSERT INTO logs_auto_bc (
                date_execution, code_famille, periode_heures,
                nb_articles_eligibles, nb_articles_traites, nb_bc_crees,
                numeros_bc_crees, articles_sans_offre, articles_partiels,
                statut, message_erreur, execute_par, duree_execution_ms
            ) VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            config.code_famille,
            config.periode_heures,
            len(articles),
            sum(bc.nb_lignes for bc in bcs_crees),
            len(bcs_crees),
            json.dumps([bc.numero_bc for bc in bcs_crees]),
            json.dumps(articles_sans_offre) if articles_sans_offre else None,
            json.dumps(articles_partiels) if articles_partiels else None,
            statut.value,
            "; ".join(erreurs) if erreurs else None,
            execute_par,
            duree_ms
        ))

        return AutoBCExecuteResponse(
            success=statut != StatutExecution.ECHEC,
            statut=statut,
            message=f"{len(bcs_crees)} BC créé(s) avec succès" if bcs_crees else "Aucun BC créé",
            date_execution=datetime.now(),
            duree_execution_ms=duree_ms,
            config=config,
            execute_par=execute_par,
            nb_articles_eligibles=len(articles),
            nb_articles_traites=sum(bc.nb_lignes for bc in bcs_crees),
            nb_bc_crees=len(bcs_crees),
            bcs_crees=bcs_crees,
            economie_totale=round(economie_totale, 2),
            articles_sans_offre=articles_sans_offre,
            articles_partiels=articles_partiels,
            erreurs=erreurs,
            log_id=log_id
        )

    except Exception as e:
        duree_ms = int((time.time() - start_time) * 1000)

        # Log l'erreur
        log_id = execute_insert("""
            INSERT INTO logs_auto_bc (
                date_execution, code_famille, periode_heures,
                nb_articles_eligibles, nb_articles_traites, nb_bc_crees,
                statut, message_erreur, execute_par, duree_execution_ms
            ) VALUES (NOW(), %s, %s, 0, 0, 0, 'echec', %s, %s, %s)
        """, (config.code_famille, config.periode_heures, str(e), execute_par, duree_ms))

        return AutoBCExecuteResponse(
            success=False,
            statut=StatutExecution.ECHEC,
            message=f"Erreur lors de l'exécution: {str(e)}",
            date_execution=datetime.now(),
            duree_execution_ms=duree_ms,
            config=config,
            execute_par=execute_par,
            nb_articles_eligibles=0,
            nb_articles_traites=0,
            nb_bc_crees=0,
            bcs_crees=[],
            economie_totale=0.0,
            erreurs=[str(e)],
            log_id=log_id
        )


# ──────────────────────────────────────────────────────────
# Endpoint : Historique
# ──────────────────────────────────────────────────────────

@router.get("/historique", response_model=LogAutoBCListResponse)
async def get_historique_auto_bc(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    code_famille: Optional[str] = None,
    statut: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Historique des exécutions Auto BC"""

    conditions = ["1=1"]
    params = []

    if code_famille:
        conditions.append("code_famille = %s")
        params.append(code_famille)

    if statut:
        conditions.append("statut = %s")
        params.append(statut)

    where_clause = " AND ".join(conditions)

    # Count
    count_result = execute_query(
        f"SELECT COUNT(*) as total FROM logs_auto_bc WHERE {where_clause}",
        tuple(params),
        fetch_one=True
    )
    total = count_result["total"] if count_result else 0

    # Get logs
    offset = (page - 1) * limit
    query = f"""
        SELECT *
        FROM logs_auto_bc
        WHERE {where_clause}
        ORDER BY date_execution DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    logs_raw = execute_query(query, tuple(params))

    # Construire la réponse
    logs = []
    for log in logs_raw or []:
        numeros_bc = []
        if log.get("numeros_bc_crees"):
            try:
                numeros_bc = json.loads(log["numeros_bc_crees"])
            except:
                pass

        logs.append(LogAutoBC(
            id=log["id"],
            date_execution=log["date_execution"],
            code_famille=log["code_famille"],
            periode_heures=log["periode_heures"],
            nb_articles_eligibles=log["nb_articles_eligibles"],
            nb_articles_traites=log["nb_articles_traites"],
            nb_bc_crees=log["nb_bc_crees"],
            numeros_bc_crees=numeros_bc,
            statut=StatutExecution(log["statut"]),
            message_erreur=log.get("message_erreur"),
            execute_par=log["execute_par"],
            duree_execution_ms=log.get("duree_execution_ms"),
            details=[]
        ))

    return LogAutoBCListResponse(
        logs=logs,
        total=total,
        page=page,
        limit=limit
    )


# ──────────────────────────────────────────────────────────
# Endpoint : Détail d'un log
# ──────────────────────────────────────────────────────────

@router.get("/historique/{log_id}", response_model=LogAutoBC)
async def get_detail_log_auto_bc(
    log_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Détail d'une exécution Auto BC avec les articles traités"""

    # Récupérer le log principal
    log = execute_query(
        "SELECT * FROM logs_auto_bc WHERE id = %s",
        (log_id,),
        fetch_one=True
    )

    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Log non trouvé"
        )

    # Récupérer les détails
    details_raw = execute_query(
        "SELECT * FROM logs_auto_bc_details WHERE log_id = %s ORDER BY id",
        (log_id,)
    )

    details = []
    for d in details_raw or []:
        details.append(LogAutoBCDetail(
            code_article=d["code_article"],
            designation_article=d.get("designation_article"),
            quantite_demandee=float(d["quantite_demandee"]) if d.get("quantite_demandee") else 0,
            code_fournisseur=d["code_fournisseur"],
            nom_fournisseur=d.get("nom_fournisseur"),
            prix_unitaire=float(d["prix_unitaire"]) if d.get("prix_unitaire") else 0,
            quantite_commandee=float(d["quantite_commandee"]) if d.get("quantite_commandee") else 0,
            delai_livraison=d.get("delai_livraison"),
            score=float(d["score"]) if d.get("score") else 0,
            type_livraison=TypeLivraison(d["type_livraison"]),
            numero_bc=d.get("numero_bc")
        ))

    numeros_bc = []
    if log.get("numeros_bc_crees"):
        try:
            numeros_bc = json.loads(log["numeros_bc_crees"])
        except:
            pass

    return LogAutoBC(
        id=log["id"],
        date_execution=log["date_execution"],
        code_famille=log["code_famille"],
        periode_heures=log["periode_heures"],
        nb_articles_eligibles=log["nb_articles_eligibles"],
        nb_articles_traites=log["nb_articles_traites"],
        nb_bc_crees=log["nb_bc_crees"],
        numeros_bc_crees=numeros_bc,
        statut=StatutExecution(log["statut"]),
        message_erreur=log.get("message_erreur"),
        execute_par=log["execute_par"],
        duree_execution_ms=log.get("duree_execution_ms"),
        details=details
    )
