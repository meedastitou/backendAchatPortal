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
from app.database import execute_query, execute_insert
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
            "TEL_Fournisseu": tel_fournisseur or "",
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
            

            -- Pas déjà commandé
            NOT EXISTS (
                SELECT 1 FROM lignes_bon_commande lbc
                WHERE lbc.ligne_source_id = rd.id
            )
            and rd.prix_unitaire_ht > 0
            and rd.quantite_disponible > 0
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
            delai_livraison=row["delai_livraison"],
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
        print(offres_raw)
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
