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
# Validation des marques dans Sage X3
# ──────────────────────────────────────────────────────────

def normaliser_marque(marque: str) -> str:
    """
    Normaliser une marque pour comparaison:
    - Supprimer tous les espaces
    - Convertir en minuscules
    """
    if not marque:
        return ""
    return marque.replace(" ", "").lower().strip()


def verifier_marque_xmarqa(code_article: str, marque: str) -> bool:
    """
    Vérifier si une marque existe dans la table XMARQA de Sage X3.
    Table: BASE1.XMARQA (Marques autorisées par article)

    Comparaison normalisée: sans espaces et en minuscules.

    Returns:
        True si la marque existe pour cet article
    """
    if not marque or not code_article:
        return False

    marque_normalisee = normaliser_marque(marque)

    try:
        # Récupérer toutes les marques de l'article
        query = """
            SELECT XMARQ_0 AS marque_article
            FROM BASE1.XMARQA
            WHERE ITMREF_0 = :code_article
              AND XMARQ_0 IS NOT NULL
        """
        rows = execute_x3_query(query, {"code_article": code_article})

        if not rows:
            return False

        # Comparer avec normalisation
        for row in rows:
            marque_x3 = normaliser_marque(row.get("marque_article", ""))
            if marque_x3 == marque_normalisee:
                return True

        return False
    except Exception as e:
        logging.error(f"Erreur vérification marque XMARQA pour {code_article}/{marque}: {e}")
        return False


def verifier_marque_historique(code_article: str, marque: str) -> bool:
    """
    Vérifier si une marque a été utilisée dans l'historique des achats (PORDERQ).
    Table: BASE1.PORDERQ (Lignes de commandes d'achat)

    Comparaison normalisée: sans espaces et en minuscules.

    Returns:
        True si la marque a déjà été achetée pour cet article
    """
    if not marque or not code_article:
        return False

    marque_normalisee = normaliser_marque(marque)

    try:
        # Récupérer toutes les marques de l'historique pour cet article
        query = """
            SELECT DISTINCT XMARQ_0 AS marque_article
            FROM BASE1.PORDERQ
            WHERE ITMREF_0 = :code_article
              AND XMARQ_0 IS NOT NULL
        """
        rows = execute_x3_query(query, {"code_article": code_article})

        if not rows:
            return False

        # Comparer avec normalisation
        for row in rows:
            marque_hist = normaliser_marque(row.get("marque_article", ""))
            if marque_hist == marque_normalisee:
                return True

        return False
    except Exception as e:
        logging.error(f"Erreur vérification marque historique pour {code_article}/{marque}: {e}")
        return False


def get_marque_defaut_x3(code_article: str) -> Optional[str]:
    """
    Récupérer une marque par défaut depuis XMARQA pour un article.
    Utilisé quand la marque proposée est null/vide.

    Returns:
        La première marque trouvée ou None
    """
    if not code_article:
        return None

    try:
        query = """
            SELECT TOP 1 XMARQ_0 AS marque_article
            FROM BASE1.XMARQA
            WHERE ITMREF_0 = :code_article
              AND XMARQ_0 IS NOT NULL
              AND XMARQ_0 != ''
        """
        rows = execute_x3_query(query, {"code_article": code_article})
        if rows and rows[0].get("marque_article"):
            return rows[0]["marque_article"]
        return None
    except Exception as e:
        logging.error(f"Erreur récupération marque défaut pour {code_article}: {e}")
        return None


def get_marques_defaut_batch(codes_articles: List[str]) -> Dict[str, str]:
    """
    Récupérer les marques par défaut pour plusieurs articles en batch.

    Returns:
        Dict avec code_article comme clé et marque comme valeur
    """
    if not codes_articles:
        return {}

    marques = {}

    try:
        # Construire la requête avec IN
        placeholders = ", ".join([f":art_{i}" for i in range(len(codes_articles))])
        params = {f"art_{i}": code for i, code in enumerate(codes_articles)}

        query = f"""
            SELECT ITMREF_0 AS code_article, XMARQ_0 AS marque_article
            FROM BASE1.XMARQA
            WHERE ITMREF_0 IN ({placeholders})
              AND XMARQ_0 IS NOT NULL
              AND XMARQ_0 != ''
        """

        rows = execute_x3_query(query, params)

        if rows:
            for row in rows:
                code = row["code_article"]
                # Prendre la première marque trouvée pour chaque article
                if code not in marques:
                    marques[code] = row["marque_article"]

        logging.info(f"Récupéré {len(marques)} marques par défaut depuis X3")

    except Exception as e:
        logging.error(f"Erreur récupération marques défaut batch: {e}")

    return marques


def verifier_marques_batch(offres: List[dict]) -> Dict[str, Dict]:
    """
    Vérifier les marques pour plusieurs offres en batch.

    Règles:
    1. Si marque_proposee est null/vide → récupérer marque depuis XMARQA
    2. Sinon, vérifier que la marque existe dans XMARQA
    3. Sinon, vérifier dans l'historique PORDERQ
    4. Si n'existe nulle part → exclure

    Returns:
        Dict avec clé "detail_id" et valeur:
        {
            "valide": bool,
            "marque_finale": str (marque à utiliser),
            "source": "proposee" | "xmarqa" | "historique" | None,
            "message": str
        }
    """
    resultats = {}

    if not offres:
        return resultats

    # Séparer les offres avec et sans marque proposée
    offres_sans_marque = []
    offres_avec_marque = []

    for offre in offres:
        detail_id = offre.get("detail_id") or offre.get("id")
        marque_proposee = offre.get("marque_proposee")
        code_article = offre.get("code_article")

        if not marque_proposee or marque_proposee.strip() == "":
            offres_sans_marque.append(offre)
        else:
            offres_avec_marque.append(offre)

    # 1. Traiter les offres SANS marque proposée → récupérer marque par défaut
    if offres_sans_marque:
        codes_uniques = list(set(o["code_article"] for o in offres_sans_marque))
        marques_defaut = get_marques_defaut_batch(codes_uniques)

        for offre in offres_sans_marque:
            detail_id = offre.get("detail_id") or offre.get("id")
            code_article = offre["code_article"]

            marque_defaut = marques_defaut.get(code_article)

            if marque_defaut:
                resultats[detail_id] = {
                    "valide": True,
                    "marque_finale": marque_defaut,
                    "source": "xmarqa",
                    "message": f"Marque par défaut depuis XMARQA: {marque_defaut}"
                }
            else:
                resultats[detail_id] = {
                    "valide": False,
                    "marque_finale": None,
                    "source": None,
                    "message": "Aucune marque proposée et aucune marque par défaut trouvée dans X3"
                }

    # 2. Traiter les offres AVEC marque proposée
    if offres_avec_marque:
        # Vérifier d'abord dans XMARQA (batch)
        marques_a_verifier = {}
        for offre in offres_avec_marque:
            detail_id = offre.get("detail_id") or offre.get("id")
            code_article = offre["code_article"]
            marque = offre["marque_proposee"]
            marques_a_verifier[detail_id] = {"code_article": code_article, "marque": marque}

        # Vérifier chaque marque (pour l'instant, on fait une boucle - on peut optimiser plus tard)
        for detail_id, info in marques_a_verifier.items():
            code_article = info["code_article"]
            marque = info["marque"]

            # Vérifier dans XMARQA
            if verifier_marque_xmarqa(code_article, marque):
                resultats[detail_id] = {
                    "valide": True,
                    "marque_finale": marque,
                    "source": "xmarqa",
                    "message": f"Marque validée dans XMARQA"
                }
            # Sinon, vérifier dans l'historique
            elif verifier_marque_historique(code_article, marque):
                resultats[detail_id] = {
                    "valide": True,
                    "marque_finale": marque,
                    "source": "historique",
                    "message": f"Marque trouvée dans historique achats"
                }
            else:
                # Marque n'existe nulle part → exclure
                resultats[detail_id] = {
                    "valide": False,
                    "marque_finale": marque,
                    "source": None,
                    "message": f"Marque '{marque}' non trouvée dans XMARQA ni historique"
                }

    return resultats


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
            -- AND rd.marque_proposee is not NULL
        ORDER BY
            ar.code_article,
            lc.numero_da
    """

    results = execute_query(query)
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

    # ══════════════════════════════════════════════════════════
    # 3. VÉRIFICATION PRIX VS TARIF X3
    # ══════════════════════════════════════════════════════════
    if offres_raw:
        logging.info("[Preview] Vérification prix vs tarif X3...")

        # Récupérer les tarifs X3
        codes_articles = list(set(row["code_article"] for row in offres_raw))
        tarifs_x3 = get_tarifs_articles_x3(codes_articles)

        offres_apres_prix = []
        for row in offres_raw:
            code_article = row["code_article"]
            prix = float(row["prix_unitaire_ht"])
            tarif = tarifs_x3.get(code_article, 0.0)

            if tarif > 0 and prix > tarif:
                # Prix > tarif → exclure et enregistrer
                ecart = prix - tarif
                ecart_pourcent = (ecart / tarif) * 100

                analyse.nb_prix_superieur += 1
                analyse.montant_ecart_total += ecart
                analyse.offres_prix_superieur.append(AnalysePrixSuperieur(
                    numero_da=row["numero_da"],
                    code_article=code_article,
                    designation_article=row.get("designation"),
                    code_fournisseur=row["code_fournisseur"],
                    nom_fournisseur=row.get("nom_fournisseur"),
                    prix_propose=prix,
                    tarif_x3=tarif,
                    ecart_montant=round(ecart, 2),
                    ecart_pourcent=round(ecart_pourcent, 2)
                ))

                # Marquer comme exclue
                for rep in analyse.reponses_consultees:
                    if rep.numero_da == row["numero_da"] and rep.code_article == code_article and rep.code_fournisseur == row["code_fournisseur"]:
                        rep.incluse = False
                        rep.raison_exclusion = f"Prix ({prix:.2f}) > Tarif X3 ({tarif:.2f})"
            else:
                offres_apres_prix.append(row)

        offres_raw = offres_apres_prix
        logging.info(f"[Preview] Après filtrage prix: {len(offres_raw)} offres restantes")

    # ══════════════════════════════════════════════════════════
    # 4. VALIDATION DES MARQUES DANS SAGE X3
    # ══════════════════════════════════════════════════════════
    if offres_raw:
        logging.info("[Preview] Validation des marques dans Sage X3...")

        # Vérifier les marques en batch
        resultats_marques = verifier_marques_batch(offres_raw)

        offres_apres_marque = []
        for row in offres_raw:
            detail_id = row.get("detail_id") or row.get("id")
            resultat_marque = resultats_marques.get(detail_id)

            if not resultat_marque:
                # Pas de résultat = garder l'offre (fail-open)
                offres_apres_marque.append(row)
                continue

            if resultat_marque["valide"]:
                # Marque validée → garder l'offre
                # Si la marque est différente (récupérée depuis XMARQA), mettre à jour
                if resultat_marque["source"] == "xmarqa" and not row.get("marque_proposee"):
                    # Marque était vide, on l'a récupérée depuis XMARQA
                    marque_finale = resultat_marque["marque_finale"]
                    row["marque_proposee"] = marque_finale
                    row["marque_source"] = "xmarqa"
                    analyse.nb_marque_depuis_xmarqa += 1

                    # Mettre à jour reponses_consultees avec la marque finale
                    for rep in analyse.reponses_consultees:
                        if (rep.numero_da == row["numero_da"] and
                            rep.code_article == row["code_article"] and
                            rep.code_fournisseur == row["code_fournisseur"]):
                            rep.marque_proposee = marque_finale

                    # Ajouter à offres_marque_probleme pour traçabilité (avec marque_finale)
                    analyse.offres_marque_probleme.append(AnalyseMarqueProbleme(
                        numero_da=row["numero_da"],
                        code_article=row["code_article"],
                        designation_article=row.get("designation"),
                        code_fournisseur=row["code_fournisseur"],
                        nom_fournisseur=row.get("nom_fournisseur"),
                        marque_souhaitee=row.get("marque_souhaitee"),
                        marque_proposee=None,  # Était vide
                        type_probleme="recuperee_x3",  # Nouveau type: récupérée avec succès
                        valide_xmarqa=True,
                        valide_historique=False,
                        marque_finale=marque_finale,
                        message=f"Marque récupérée depuis XMARQA: {marque_finale}"
                    ))

                offres_apres_marque.append(row)
            else:
                # Marque non validée → exclure et enregistrer
                analyse.nb_marque_non_validee += 1

                type_probleme = "non_validee"
                if not row.get("marque_proposee"):
                    type_probleme = "manquante"
                    analyse.nb_marque_manquante += 1

                analyse.offres_marque_probleme.append(AnalyseMarqueProbleme(
                    numero_da=row["numero_da"],
                    code_article=row["code_article"],
                    designation_article=row.get("designation"),
                    code_fournisseur=row["code_fournisseur"],
                    nom_fournisseur=row.get("nom_fournisseur"),
                    marque_souhaitee=row.get("marque_souhaitee"),
                    marque_proposee=row.get("marque_proposee"),
                    type_probleme=type_probleme,
                    valide_xmarqa=False,
                    valide_historique=False,
                    marque_finale=resultat_marque.get("marque_finale"),
                    message=resultat_marque.get("message")
                ))

                # Marquer comme exclue dans l'analyse
                for rep in analyse.reponses_consultees:
                    if (rep.numero_da == row["numero_da"] and
                        rep.code_article == row["code_article"] and
                        rep.code_fournisseur == row["code_fournisseur"]):
                        rep.incluse = False
                        rep.raison_exclusion = resultat_marque.get("message", "Marque non validée")

        offres_raw = offres_apres_marque
        logging.info(f"[Preview] Après filtrage marques: {len(offres_raw)} offres restantes")

    # ══════════════════════════════════════════════════════════

    if not offres_raw:
        # Construire le résumé
        analyse.resume = f"Sur {analyse.nb_reponses_consultees} réponses consultées: "
        analyse.resume += f"{analyse.nb_da_soldees} DA soldées, "
        analyse.resume += f"{analyse.nb_da_non_signees} DA non signées, "
        analyse.resume += f"{analyse.nb_prix_superieur} offres prix > tarif X3, "
        analyse.resume += f"{analyse.nb_marque_non_validee} marques non validées."

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

    # Construire le résumé de l'analyse
    analyse.resume = f"Sur {analyse.nb_reponses_consultees} réponses consultées: "
    analyse.resume += f"{analyse.nb_da_ok} DA OK, "
    analyse.resume += f"{analyse.nb_da_soldees} DA soldées, "
    analyse.resume += f"{analyse.nb_da_non_signees} DA non signées, "
    analyse.resume += f"{analyse.nb_prix_superieur} prix > tarif, "
    analyse.resume += f"{analyse.nb_marque_non_validee} marques non validées"
    if analyse.nb_marque_depuis_xmarqa > 0:
        analyse.resume += f" ({analyse.nb_marque_depuis_xmarqa} marques récupérées depuis XMARQA)"
    analyse.resume += f". Résultat: {len(bcs_preview)} BC à créer avec {len(articles)} articles."

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
        economie_totale_estimee=round(economie_totale, 2),
        analyse=analyse
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
    Inclut une analyse détaillée pour comprendre les exclusions.
    """
    start_time = time.time()

    # Config par défaut si non fournie
    config = request.config if request and request.config else AutoBCConfig()
    execute_par = request.execute_par if request else current_user.get("username", "SYSTEM")

    # ══════════════════════════════════════════════════════════
    # INITIALISER L'ANALYSE
    # ══════════════════════════════════════════════════════════
    analyse = AnalyseAutoBC()

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
            analyse.resume = "Aucune réponse fournisseur trouvée."
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
                log_id=log_id,
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
                incluse=True,
                raison_exclusion=None
            ))

        # ══════════════════════════════════════════════════════════
        # 2. VÉRIFICATION STATUT DA DANS SAGE X3
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
                das_soldees_set.add(row["numero_da"])
                lignes_a_marquer_solde.append(row["ligne_cotation_id"])
                articles_soldes.append(f"{row['numero_da']}/{row['code_article']}")
                log_verification_x3(row["numero_da"], row["code_article"], details, "solde")

                # Marquer comme exclue
                for rep in analyse.reponses_consultees:
                    if rep.numero_da == row["numero_da"] and rep.code_article == row["code_article"]:
                        rep.incluse = False
                        rep.raison_exclusion = "DA soldée dans Sage X3"

            elif statut_x3["statut"] == "non_signe":
                # Non signé → exclure sans marquer (peut-être signé demain)
                analyse.nb_da_non_signees += 1
                das_non_signees_set.add(row["numero_da"])
                articles_non_signes.append(f"{row['numero_da']}/{row['code_article']}")
                log_verification_x3(row["numero_da"], row["code_article"], details, "ignore_non_signe")

                # Marquer comme exclue
                for rep in analyse.reponses_consultees:
                    if rep.numero_da == row["numero_da"] and rep.code_article == row["code_article"]:
                        rep.incluse = False
                        rep.raison_exclusion = "DA non signée dans Sage X3"

            else:
                # OK → garder l'offre
                analyse.nb_da_ok += 1
                offres_filtrees.append(row)
                log_verification_x3(row["numero_da"], row["code_article"], details, "ok")

        # Mettre à jour les compteurs distincts
        analyse.nb_da_soldees_distinct = len(das_soldees_set)
        analyse.nb_da_non_signees_distinct = len(das_non_signees_set)

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
        # 3. VÉRIFICATION PRIX VS TARIF X3
        # ══════════════════════════════════════════════════════════
        if offres_raw:
            logging.info("Vérification prix vs tarif X3...")

            # Récupérer les tarifs X3
            codes_articles = list(set(row["code_article"] for row in offres_raw))
            tarifs_x3 = get_tarifs_articles_x3(codes_articles)

            offres_apres_prix = []
            for row in offres_raw:
                code_article = row["code_article"]
                prix = float(row["prix_unitaire_ht"])
                tarif = tarifs_x3.get(code_article, 0.0)

                if tarif > 0 and prix > tarif:
                    # Prix > tarif → exclure et enregistrer
                    ecart = prix - tarif
                    ecart_pourcent = (ecart / tarif) * 100

                    analyse.nb_prix_superieur += 1
                    analyse.montant_ecart_total += ecart
                    analyse.offres_prix_superieur.append(AnalysePrixSuperieur(
                        numero_da=row["numero_da"],
                        code_article=code_article,
                        designation_article=row.get("designation"),
                        code_fournisseur=row["code_fournisseur"],
                        nom_fournisseur=row.get("nom_fournisseur"),
                        prix_propose=prix,
                        tarif_x3=tarif,
                        ecart_montant=round(ecart, 2),
                        ecart_pourcent=round(ecart_pourcent, 2)
                    ))

                    # Marquer comme exclue
                    for rep in analyse.reponses_consultees:
                        if rep.numero_da == row["numero_da"] and rep.code_article == code_article and rep.code_fournisseur == row["code_fournisseur"]:
                            rep.incluse = False
                            rep.raison_exclusion = f"Prix ({prix:.2f}) > Tarif X3 ({tarif:.2f})"
                else:
                    offres_apres_prix.append(row)

            offres_raw = offres_apres_prix
            logging.info(f"Après filtrage prix: {len(offres_raw)} offres restantes")

        # ══════════════════════════════════════════════════════════

        if not offres_raw:
            # Construire le résumé
            analyse.resume = f"Sur {analyse.nb_reponses_consultees} réponses: "
            analyse.resume += f"{analyse.nb_da_soldees} DA soldées, "
            analyse.resume += f"{analyse.nb_da_non_signees} DA non signées, "
            analyse.resume += f"{analyse.nb_prix_superieur} prix > tarif X3."

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
                message="Aucune offre éligible après filtrage",
                date_execution=datetime.now(),
                duree_execution_ms=duree_ms,
                config=config,
                execute_par=execute_par,
                nb_articles_eligibles=0,
                nb_articles_traites=0,
                nb_bc_crees=0,
                bcs_crees=[],
                economie_totale=0.0,
                log_id=log_id,
                analyse=analyse
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

        # Construire le résumé de l'analyse
        analyse.resume = f"Sur {analyse.nb_reponses_consultees} réponses consultées: "
        analyse.resume += f"{analyse.nb_da_ok} DA OK, "
        analyse.resume += f"{analyse.nb_da_soldees} DA soldées (exclues), "
        analyse.resume += f"{analyse.nb_da_non_signees} DA non signées (exclues), "
        analyse.resume += f"{analyse.nb_prix_superieur} offres prix > tarif X3 (exclues). "
        analyse.resume += f"Résultat: {len(bcs_crees)} BC créé(s) avec {len(articles)} articles."

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
            log_id=log_id,
            analyse=analyse
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

        analyse.resume = f"Erreur lors de l'exécution: {str(e)}"

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
            log_id=log_id,
            analyse=analyse
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


# ──────────────────────────────────────────────────────────
# Endpoint : BC créés dans Sage X3 via RPA
# ──────────────────────────────────────────────────────────

@router.get("/bc-x3-rpa", response_model=BCX3ListResponse)
async def get_bc_x3_rpa(
    date_debut: Optional[str] = Query(default=None, description="Date début (YYYYMMDD)"),
    current_user: dict = Depends(get_current_user)
):
    """
    Récupérer les bons de commande créés dans Sage X3 via RPA.
    Par défaut, récupère les BC créés depuis le 1er du mois courant.
    """

    # Date par défaut: 1er du mois courant
    if not date_debut:
        now = datetime.now()
        date_debut = f"{now.year}{now.month:02d}01"

    try:
        query = """
            SELECT
                po.POHNUM_0     AS numero_commande,
                po.BPSNUM_0     AS code_fournisseur,
                po.BPRNAM_0     AS nom_fournisseur,
                prd.PSHNUM_0    AS numero_da,
                prd.ITMREF_0    AS code_article,
                prd.ITMDES_0    AS designation_article,
                prd.LINAMT_0    AS montant_ligne_ht,
                prd.LINATIAMT_0 AS montant_ligne_ttc,
                po.TOTLINATI_0  AS total_lignes_ttc,
                po.TOTORD_0     AS total_commande_ht,
                po.UPDUSR_0     AS utilisateur_modif
            FROM BASE1.PORDER po
            LEFT JOIN BASE1.PORDERQ poq
                ON po.POHNUM_0 = poq.POHNUM_0
            LEFT JOIN BASE1.PREQUISD prd
                ON poq.PSHNUM_0 = prd.PSHNUM_0
            WHERE po.CREUSR_0 = 'RPA'
              AND po.CREDAT_0 > :date_debut
            ORDER BY po.POHNUM_0 DESC, prd.ITMREF_0
        """

        rows = execute_x3_query(query, {"date_debut": date_debut})

        if not rows:
            return BCX3ListResponse(bcs=[], total=0)

        # Grouper par numéro de commande
        bcs_dict: Dict[str, BCX3Response] = {}

        for row in rows:
            numero_cmd = row["numero_commande"]

            if numero_cmd not in bcs_dict:
                bcs_dict[numero_cmd] = BCX3Response(
                    numero_commande=numero_cmd,
                    code_fournisseur=row["code_fournisseur"] or "",
                    nom_fournisseur=row.get("nom_fournisseur"),
                    total_lignes_ttc=float(row["total_lignes_ttc"]) if row.get("total_lignes_ttc") else None,
                    total_commande_ht=float(row["total_commande_ht"]) if row.get("total_commande_ht") else None,
                    utilisateur_modif=row.get("utilisateur_modif"),
                    lignes=[],
                    nb_lignes=0
                )

            # Ajouter la ligne si elle existe
            if row.get("code_article"):
                bcs_dict[numero_cmd].lignes.append(LigneBCX3(
                    numero_commande=numero_cmd,
                    code_fournisseur=row["code_fournisseur"] or "",
                    nom_fournisseur=row.get("nom_fournisseur"),
                    numero_da=row.get("numero_da"),
                    code_article=row.get("code_article"),
                    designation_article=row.get("designation_article"),
                    montant_ligne_ht=float(row["montant_ligne_ht"]) if row.get("montant_ligne_ht") else None,
                    montant_ligne_ttc=float(row["montant_ligne_ttc"]) if row.get("montant_ligne_ttc") else None
                ))
                bcs_dict[numero_cmd].nb_lignes = len(bcs_dict[numero_cmd].lignes)

        bcs_list = list(bcs_dict.values())

        return BCX3ListResponse(
            bcs=bcs_list,
            total=len(bcs_list)
        )

    except Exception as e:
        logging.error(f"Erreur récupération BC X3 RPA: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des BC X3: {str(e)}"
        )
