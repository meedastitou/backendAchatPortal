"""
════════════════════════════════════════════════════════════
ROUTER - Réponses Fournisseurs
════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import FileResponse
from typing import Optional
import uuid as uuid_lib
import logging
import os

from app.auth.dependencies import get_current_user, get_user_famille_filter
from app.database import execute_query, execute_update, execute_insert
from app.schemas.reponse import (
    ReponseEnteteResponse,
    ReponseDetailResponse,
    ReponseComplete,
    ReponseListResponse,
    ComparaisonArticle,
    ComparaisonResponse,
    RejetResponse,
    ReponseAcheteurRequest,
    ReponseAcheteurResponse,
    ReponseAcheteurComplete,
    ReponseAcheteurListResponse,
    LigneReponseAcheteurDetail,
    # Saisie Devis RFQ
    LigneDevisRFQ,
    SaisieDevisRFQRequest,
    RFQPourSaisie,
    RFQPourSaisieListResponse,
    LigneCotationPourSaisie,
    RFQDetailPourSaisie
)
from datetime import datetime


router = APIRouter(prefix="/reponses", tags=["Réponses Fournisseurs"])


# ──────────────────────────────────────────────────────────
# Liste des réponses
# ──────────────────────────────────────────────────────────

@router.get("", response_model=ReponseListResponse)
async def list_reponses(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    code_fournisseur: Optional[str] = None,
    search_rfq: Optional[str] = None,
    search_fournisseur: Optional[str] = None,
    search_da: Optional[str] = None,
    date_debut: Optional[datetime] = None,
    date_fin: Optional[datetime] = None,
    current_user: dict = Depends(get_current_user)
):
    """Lister toutes les réponses fournisseurs"""

    conditions = ["1=1"]
    params = []
    need_lc_join = False

    if code_fournisseur:
        conditions.append("dc.code_fournisseur = %s")
        params.append(code_fournisseur)

    if search_rfq:
        conditions.append("dc.numero_rfq LIKE %s")
        params.append(f"%{search_rfq}%")

    if search_fournisseur:
        conditions.append("(dc.code_fournisseur LIKE %s OR f.nom_fournisseur LIKE %s)")
        params.append(f"%{search_fournisseur}%")
        params.append(f"%{search_fournisseur}%")

    if search_da:
        conditions.append("lc.numero_da LIKE %s")
        params.append(f"%{search_da}%")
        need_lc_join = True

    if date_debut:
        conditions.append("re.date_reponse >= %s")
        params.append(date_debut)

    if date_fin:
        conditions.append("re.date_reponse <= %s")
        params.append(date_fin)

    where_clause = " AND ".join(conditions)

    # Jointure optionnelle avec lignes_cotation si recherche par DA
    lc_join = """
        JOIN reponses_fournisseurs_detail rd ON re.id = rd.reponse_entete_id
        JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
    """ if need_lc_join else ""

    # Count (avec DISTINCT si jointure LC pour éviter les doublons)
    count_query = f"""
        SELECT COUNT(DISTINCT re.id) as total
        FROM reponses_fournisseurs_entete re
        JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        {lc_join}
        WHERE {where_clause}
    """
    total = execute_query(count_query, tuple(params), fetch_one=True)["total"]

    # Get entetes
    offset = (page - 1) * limit
    query = f"""
        SELECT DISTINCT
            re.*,
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur
        FROM reponses_fournisseurs_entete re
        JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        {lc_join}
        WHERE {where_clause}
        ORDER BY re.date_reponse DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    entetes = execute_query(query, tuple(params))

    # Construire les réponses complètes
    reponses = []
    for entete in entetes:
        details = execute_query(
            """
            SELECT
                rd.*,
                lc.designation_article,
                lc.marque_souhaitee as marque_demandee,
                lc.numero_da,
                lc.quantite_demandee,
                ar.prix_base as tarif_reference
            FROM reponses_fournisseurs_detail rd
            LEFT JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
            LEFT JOIN articles_ref ar ON rd.code_article = ar.code_article
            WHERE rd.reponse_entete_id = %s
            """,
            (entete["id"],)
        )

        reponses.append(ReponseComplete(
            entete=ReponseEnteteResponse(**entete),
            details=[ReponseDetailResponse(**d) for d in details],
            numero_rfq=entete["numero_rfq"],
            code_fournisseur=entete["code_fournisseur"],
            nom_fournisseur=entete["nom_fournisseur"]
        ))

    return ReponseListResponse(
        reponses=reponses,
        total=total,
        page=page,
        limit=limit
    )


# ──────────────────────────────────────────────────────────
# Détail d'une réponse
# ──────────────────────────────────────────────────────────

@router.get("/{reponse_id}", response_model=ReponseComplete)
async def get_reponse(
    reponse_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Obtenir les détails d'une réponse"""

    query = """
        SELECT
            re.*,
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur
        FROM reponses_fournisseurs_entete re
        JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE re.id = %s
    """
    entete = execute_query(query, (reponse_id,), fetch_one=True)

    if not entete:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Réponse non trouvée"
        )

    details = execute_query(
        """
        SELECT
            rd.*,
            lc.designation_article,
            lc.marque_souhaitee as marque_demandee,
            lc.numero_da,
            lc.quantite_demandee,
            ar.prix_base as tarif_reference
        FROM reponses_fournisseurs_detail rd
        LEFT JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        LEFT JOIN articles_ref ar ON rd.code_article = ar.code_article
        WHERE rd.reponse_entete_id = %s
        """,
        (reponse_id,)
    )

    return ReponseComplete(
        entete=ReponseEnteteResponse(**entete),
        details=[ReponseDetailResponse(**d) for d in details],
        numero_rfq=entete["numero_rfq"],
        code_fournisseur=entete["code_fournisseur"],
        nom_fournisseur=entete["nom_fournisseur"]
    )


# ──────────────────────────────────────────────────────────
# Réponse par UUID de RFQ
# ──────────────────────────────────────────────────────────

@router.get("/rfq/{rfq_uuid}", response_model=ReponseComplete)
async def get_reponse_by_rfq(
    rfq_uuid: str,
    current_user: dict = Depends(get_current_user)
):
    """Obtenir la réponse pour une RFQ donnée"""

    query = """
        SELECT
            re.*,
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur
        FROM reponses_fournisseurs_entete re
        JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE re.rfq_uuid = %s
    """
    entete = execute_query(query, (rfq_uuid,), fetch_one=True)

    if not entete:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune réponse trouvée pour cette RFQ"
        )

    details = execute_query(
        """
        SELECT
            rd.*,
            lc.designation_article,
            lc.marque_souhaitee as marque_demandee,
            lc.numero_da,
            lc.quantite_demandee,
            ar.prix_base as tarif_reference
        FROM reponses_fournisseurs_detail rd
        LEFT JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        LEFT JOIN articles_ref ar ON rd.code_article = ar.code_article
        WHERE rd.reponse_entete_id = %s
        """,
        (entete["id"],)
    )

    return ReponseComplete(
        entete=ReponseEnteteResponse(**entete),
        details=[ReponseDetailResponse(**d) for d in details],
        numero_rfq=entete["numero_rfq"],
        code_fournisseur=entete["code_fournisseur"],
        nom_fournisseur=entete["nom_fournisseur"]
    )


# ──────────────────────────────────────────────────────────
# Comparaison des offres pour un article
# ──────────────────────────────────────────────────────────

@router.get("/comparaison/article/{code_article}")
async def compare_offers_for_article(
    code_article: str,
    numero_da: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Comparer les offres reçues pour un article"""

    conditions = ["rd.code_article = %s"]
    params = [code_article]

    if numero_da:
        conditions.append("lc.numero_da = %s")
        params.append(numero_da)

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            rd.*,
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur,
            lc.quantite_demandee,
            lc.designation_article,
            re.devise,
            ar.prix_base as tarif_reference
        FROM reponses_fournisseurs_detail rd
        JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        JOIN demandes_cotation dc ON rd.rfq_uuid = dc.uuid
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        LEFT JOIN articles_ref ar ON rd.code_article = ar.code_article
        WHERE {where_clause}
          AND rd.prix_unitaire_ht IS NOT NULL
        ORDER BY rd.prix_unitaire_ht ASC
    """

    offres = execute_query(query, tuple(params))

    if not offres:
        return {
            "code_article": code_article,
            "offres": [],
            "analyse": None
        }

    # Analyse
    prix_list = [o["prix_unitaire_ht"] for o in offres if o["prix_unitaire_ht"]]

    analyse = {
        "nb_offres": len(offres),
        "prix_min": min(prix_list) if prix_list else None,
        "prix_max": max(prix_list) if prix_list else None,
        "prix_moyen": sum(prix_list) / len(prix_list) if prix_list else None,
        "meilleur_fournisseur": offres[0]["nom_fournisseur"] if offres else None,
        "meilleur_prix": offres[0]["prix_unitaire_ht"] if offres else None
    }

    return {
        "code_article": code_article,
        "designation": offres[0]["designation_article"] if offres else None,
        "offres": offres,
        "analyse": analyse
    }


# ──────────────────────────────────────────────────────────
# Liste des rejets
# ──────────────────────────────────────────────────────────

@router.get("/rejets/list")
async def list_rejets(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user)
):
    """Lister les rejets de cotation"""

    # Count
    total = execute_query(
        "SELECT COUNT(*) as c FROM rejets_fournisseurs",
        fetch_one=True
    )["c"]

    # Get rejets
    offset = (page - 1) * limit
    query = """
        SELECT
            r.*,
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur
        FROM rejets_fournisseurs r
        JOIN demandes_cotation dc ON r.rfq_uuid = dc.uuid
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        ORDER BY r.date_rejet DESC
        LIMIT %s OFFSET %s
    """
    rejets = execute_query(query, (limit, offset))

    return {
        "rejets": rejets,
        "total": total,
        "page": page,
        "limit": limit
    }


# ──────────────────────────────────────────────────────────
# Dashboard Comparaison - Tous les articles avec réponses
# ──────────────────────────────────────────────────────────

@router.get("/comparaison/dashboard")
async def get_comparaison_dashboard(
    current_user: dict = Depends(get_current_user)
):
    """
    Retourne tous les articles ayant des réponses fournisseurs OU acheteur,
    groupés par article avec les DAs associées et les offres.

    IMPORTANT: Si un même fournisseur répond sur le même article plusieurs fois
    (car l'article est dans différentes DAs) avec la même entête de réponse,
    on n'affiche qu'une seule offre pour éviter les doublons.

    FILTRE: Exclut les articles/DA deja selectionnes ou convertis en BC.

    Les offres acheteur sont marquées avec is_acheteur=True.
    """
    join_lignes = False
    join_articles = False
    conditions = ["1=1"]
    params = []
    # Filtrage par famille pour les acheteurs
    familles_filter = get_user_famille_filter(current_user)
    if familles_filter is not None:
        
        join_lignes = True
        join_articles = True
        placeholders = ", ".join(["%s"] * len(familles_filter))
        conditions.append(f"ar.code_famille IN ({placeholders})")
        params.extend(familles_filter)
    where_clause = " AND ".join(conditions)


    # Récupérer tous les articles avec réponses fournisseurs
    # Exclure les articles/DA qui ont deja une selection (peu importe le statut)
    query_fournisseurs = f"""
        SELECT
            rd.code_article,
            rd.reponse_entete_id,
            lc.designation_article,
            lc.numero_da,
            lc.marque_souhaitee,
            lc.quantite_demandee,
            rd.id as detail_id,
            rd.prix_unitaire_ht,
            rd.quantite_disponible,
            rd.date_livraison,
            rd.marque_conforme,
            rd.marque_proposee,
            dc.code_fournisseur,
            f.nom_fournisseur,
            re.devise,
            re.date_reponse,
            re.methodes_paiement,
            ar.prix_base as tarif_reference,
            0 as is_acheteur
        FROM reponses_fournisseurs_detail rd
        JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        JOIN demandes_cotation dc ON rd.rfq_uuid = dc.uuid
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        LEFT JOIN articles_ref ar ON rd.code_article = ar.code_article
        WHERE rd.prix_unitaire_ht IS NOT NULL
          AND (lc.actif = TRUE OR lc.actif IS NULL)
          AND NOT EXISTS (
              SELECT 1 FROM selections_articles sa
              WHERE sa.code_article = rd.code_article
                AND sa.numero_da = lc.numero_da
                AND sa.statut = 'selectionne'
          )
        AND lc.x3_solde is false
        AND {where_clause}
        ORDER BY rd.code_article, rd.prix_unitaire_ht ASC
    """
    print(query_fournisseurs)
    rows_fournisseurs = execute_query(query_fournisseurs, tuple(params))

    # Récupérer les réponses acheteur (saisies manuelles)
    query_acheteur = """
        SELECT
            rd.code_article,
            rd.reponse_entete_id,
            lc.designation_article,
            lc.numero_da,
            lc.marque_souhaitee,
            lc.quantite_demandee,
            rd.id as detail_id,
            rd.prix_unitaire_ht,
            rd.quantite_disponible,
            NULL as date_livraison,
            rd.marque_conforme,
            rd.marque_proposee,
            rd.code_fournisseur,
            rd.nom_fournisseur,
            re.devise,
            re.date_soumission as date_reponse,
            re.conditions_paiement as methodes_paiement,
            ar.prix_base as tarif_reference,
            1 as is_acheteur
        FROM reponses_detail_acheteur rd
        JOIN reponses_entete_acheteur re ON rd.reponse_entete_id = re.id
        JOIN lignes_cotation_acheteur lc ON rd.ligne_cotation_id = lc.id
        LEFT JOIN articles_ref ar ON rd.code_article COLLATE utf8mb4_unicode_ci = ar.code_article COLLATE utf8mb4_unicode_ci
        WHERE rd.prix_unitaire_ht IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM selections_articles sa
              WHERE sa.code_article COLLATE utf8mb4_unicode_ci = rd.code_article COLLATE utf8mb4_unicode_ci
                AND sa.numero_da COLLATE utf8mb4_unicode_ci = lc.numero_da COLLATE utf8mb4_unicode_ci
                AND sa.statut = 'selectionne'
          )
        ORDER BY rd.code_article, rd.prix_unitaire_ht ASC
    """

    rows_acheteur = execute_query(query_acheteur)

    # Combiner les deux sources
    rows = rows_fournisseurs + rows_acheteur

    # Grouper par article
    articles_dict = {}
    for row in rows:
        code = row["code_article"]
        if code not in articles_dict:
            articles_dict[code] = {
                "code_article": code,
                "designation": row["designation_article"],
                "marque_demandee": row["marque_souhaitee"],
                "tarif_reference": row["tarif_reference"],
                "quantite_demandee": 0,  # Sera la somme des quantites demandees par DA
                "das": set(),
                "das_quantites": {},  # Pour stocker quantite par DA: numero_da -> quantite
                "offres": [],
                "offres_keys": {},  # Pour déduplication: (code_fournisseur, reponse_entete_id) -> index
                "analyse": {
                    "nb_offres": 0,
                    "prix_min": None,
                    "prix_max": None,
                    "prix_moyen": None,
                    "meilleur_fournisseur": None,
                    "meilleur_prix": None
                }
            }

        # Ajouter DA et quantite demandee (on garde toutes les DAs même si offre dédupliquée)
        if row["numero_da"]:
            articles_dict[code]["das"].add(row["numero_da"])
            # Stocker quantite par DA si pas deja fait
            if row["numero_da"] not in articles_dict[code]["das_quantites"]:
                qty = float(row["quantite_demandee"]) if row["quantite_demandee"] else 0
                articles_dict[code]["das_quantites"][row["numero_da"]] = qty
                articles_dict[code]["quantite_demandee"] += qty

        # Clé de déduplication: même fournisseur + même entête réponse + source = même offre
        is_acheteur = bool(row.get("is_acheteur", 0))
        offre_key = (row["code_fournisseur"], row["reponse_entete_id"], is_acheteur)

        # Ajouter offre seulement si pas déjà présente, sinon sommer la quantité
        if offre_key not in articles_dict[code]["offres_keys"]:
            articles_dict[code]["offres_keys"][offre_key] = len(articles_dict[code]["offres"])
            articles_dict[code]["offres"].append({
                "detail_id": row["detail_id"],
                "code_fournisseur": row["code_fournisseur"],
                "nom_fournisseur": row["nom_fournisseur"],
                "prix_unitaire_ht": row["prix_unitaire_ht"],
                "quantite_disponible": row["quantite_disponible"] or 0,
                "date_livraison": row["date_livraison"],
                "marque_conforme": row["marque_conforme"],
                "marque_proposee": row["marque_proposee"],
                "devise": row["devise"],
                "date_reponse": row["date_reponse"],
                "methodes_paiement": row["methodes_paiement"],
                "is_acheteur": is_acheteur
            })
        else:
            # Offre déjà présente: sommer la quantité disponible
            offre_index = articles_dict[code]["offres_keys"][offre_key]
            existing_qty = articles_dict[code]["offres"][offre_index]["quantite_disponible"] or 0
            new_qty = row["quantite_disponible"] or 0
            articles_dict[code]["offres"][offre_index]["quantite_disponible"] = existing_qty + new_qty

    # Calculer analyse pour chaque article
    articles = []
    for code, data in articles_dict.items():
        prix_list = [o["prix_unitaire_ht"] for o in data["offres"] if o["prix_unitaire_ht"]]

        if prix_list:
            data["analyse"]["nb_offres"] = len(data["offres"])
            data["analyse"]["prix_min"] = min(prix_list)
            data["analyse"]["prix_max"] = max(prix_list)
            data["analyse"]["prix_moyen"] = sum(prix_list) / len(prix_list)

            # Meilleur offre (prix le plus bas)
            best_offre = data["offres"][0]  # Déjà trié par prix ASC
            data["analyse"]["meilleur_fournisseur"] = best_offre["nom_fournisseur"]
            data["analyse"]["meilleur_prix"] = best_offre["prix_unitaire_ht"]

        # Convertir set en list et supprimer les clés internes (pas besoin dans la réponse)
        data["das"] = list(data["das"])
        del data["offres_keys"]
        del data["das_quantites"]
        articles.append(data)

    # Récupérer les fournisseurs en attente pour les articles ayant des offres
    # (fournisseurs qui ont reçu une RFQ mais n'ont pas encore répondu)
    if articles_dict:
        codes_articles = list(articles_dict.keys())
        placeholders = ",".join(["%s"] * len(codes_articles))

        query_en_attente = f"""
            SELECT DISTINCT
                lc.code_article,
                dc.code_fournisseur,
                f.nom_fournisseur,
                dc.date_envoi,
                dc.statut as statut_rfq
            FROM lignes_cotation lc
            JOIN demandes_cotation dc ON lc.rfq_uuid = dc.uuid
            JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
            LEFT JOIN reponses_fournisseurs_entete re ON dc.uuid = re.rfq_uuid
            LEFT JOIN rejets_fournisseurs rj ON dc.uuid = rj.rfq_uuid
            WHERE lc.code_article IN ({placeholders})
              AND re.id IS NULL
              AND rj.id IS NULL
              AND dc.statut = 'envoye'
        """
        fournisseurs_attente = execute_query(query_en_attente, tuple(codes_articles))

        # Grouper par article
        for fa in fournisseurs_attente:
            code = fa["code_article"]
            if code in articles_dict:
                if "fournisseurs_en_attente" not in articles_dict[code]:
                    articles_dict[code]["fournisseurs_en_attente"] = []

                articles_dict[code]["fournisseurs_en_attente"].append({
                    "code_fournisseur": fa["code_fournisseur"],
                    "nom_fournisseur": fa["nom_fournisseur"],
                    "date_envoi": fa["date_envoi"]
                })

    # S'assurer que tous les articles ont le champ fournisseurs_en_attente
    for code in articles_dict:
        if "fournisseurs_en_attente" not in articles_dict[code]:
            articles_dict[code]["fournisseurs_en_attente"] = []

    # Trier par nombre d'offres décroissant
    articles.sort(key=lambda x: x["analyse"]["nb_offres"], reverse=True)

    return {
        "articles": articles,
        "total_articles": len(articles),
        "total_offres": sum(a["analyse"]["nb_offres"] for a in articles)
    }


# ──────────────────────────────────────────────────────────
# Saisie Manuelle de Réponse (Tables _acheteur)
# ──────────────────────────────────────────────────────────

def _generate_numero_rfq_acheteur() -> str:
    """Génère un numéro RFQ acheteur unique au format RFQA-YYYY-NNNN"""
    year = datetime.now().year

    result = execute_query(
        """
        SELECT numero_rfq FROM demandes_cotation_acheteur
        WHERE numero_rfq LIKE %s
        ORDER BY numero_rfq DESC LIMIT 1
        """,
        (f"RFQA-{year}-%",),
        fetch_one=True
    )

    if result:
        last_num = int(result["numero_rfq"].split("-")[-1])
        new_num = last_num + 1
    else:
        new_num = 1

    return f"RFQA-{year}-{new_num:04d}"


@router.post("/saisie-manuelle", response_model=ReponseAcheteurResponse)
async def saisie_manuelle_reponse(
    request: ReponseAcheteurRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Saisir manuellement des réponses fournisseurs.

    Utilise les tables _acheteur pour permettre:
    - Un fournisseur différent par article
    - Consolidation de plusieurs devis dans une seule saisie
    - Comparaison facile entre fournisseurs

    Crée automatiquement:
    - Une demande_cotation_acheteur
    - Les lignes_cotation_acheteur
    - L'entête reponses_entete_acheteur
    - Les détails reponses_detail_acheteur (avec fournisseur par ligne)
    """

    if not request.lignes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Au moins une ligne est requise"
        )

    # 1. Vérifier que la DA existe et récupérer ses articles
    articles_da = execute_query(
        """
        SELECT code_article, designation_article, quantite, unite, marque_souhaitee
        FROM demandes_achat
        WHERE numero_da = %s
        """,
        (request.numero_da,)
    )

    if not articles_da:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Aucun article trouvé pour la DA {request.numero_da}"
        )

    articles_da_dict = {a["code_article"]: a for a in articles_da}

    # 2. Vérifier que les articles de la réponse sont dans la DA
    codes_articles_reponse = [l.code_article for l in request.lignes]
    codes_invalides = [c for c in codes_articles_reponse if c not in articles_da_dict]

    if codes_invalides:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Articles non présents dans la DA: {', '.join(codes_invalides)}"
        )

    # 3. Générer les identifiants
    rfq_uuid = str(uuid_lib.uuid4())
    numero_rfq = _generate_numero_rfq_acheteur()
    uuid_reponse = str(uuid_lib.uuid4())

    # Récupérer la famille depuis le premier article
    first_article = articles_da[0]
    famille = None
    famille_result = execute_query(
        "SELECT code_famille FROM articles_ref WHERE code_article = %s",
        (first_article["code_article"],),
        fetch_one=True
    )
    if famille_result:
        famille = famille_result["code_famille"]

    try:
        # 4. Créer demandes_cotation_acheteur
        execute_query(
            """
            INSERT INTO demandes_cotation_acheteur (
                uuid, numero_rfq, acheteur_id, acheteur_email,
                famille, date_creation, statut, commentaire
            ) VALUES (%s, %s, %s, %s, %s, %s, 'complete', %s)
            """,
            (
                rfq_uuid, numero_rfq,
                current_user["id"],
                current_user.get("email", current_user["username"]),
                famille,
                datetime.now(),
                request.commentaire_global
            ),
            commit=True
        )

        # 5. Créer lignes_cotation_acheteur pour chaque article
        ligne_ids = {}
        for ligne in request.lignes:
            article_da = articles_da_dict[ligne.code_article]

            result = execute_query(
                """
                INSERT INTO lignes_cotation_acheteur (
                    rfq_uuid, numero_da, code_article, designation_article,
                    quantite_demandee, unite, marque_souhaitee
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    rfq_uuid, request.numero_da, ligne.code_article,
                    article_da["designation_article"],
                    article_da["quantite"],
                    article_da["unite"],
                    article_da["marque_souhaitee"]
                ),
                commit=True,
                return_lastrowid=True
            )
            ligne_ids[ligne.code_article] = result

        # 6. Créer reponses_entete_acheteur
        result = execute_query(
            """
            INSERT INTO reponses_entete_acheteur (
                rfq_uuid, uuid_reponse, devise, conditions_paiement,
                date_soumission, commentaire_global, saisi_par_email
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                rfq_uuid, uuid_reponse, request.devise,
                request.conditions_paiement, datetime.now(),
                request.commentaire_global,
                current_user.get("email", current_user["username"])
            ),
            commit=True,
            return_lastrowid=True
        )
        reponse_entete_id = result

        # 7. Créer reponses_detail_acheteur pour chaque ligne (avec fournisseur par ligne)
        for ligne in request.lignes:
            ligne_cotation_id = ligne_ids[ligne.code_article]

            execute_query(
                """
                INSERT INTO reponses_detail_acheteur (
                    reponse_entete_id, rfq_uuid, ligne_cotation_id, code_article,
                    code_fournisseur, nom_fournisseur, email_fournisseur, telephone_fournisseur,
                    prix_unitaire_ht, quantite_disponible, delai_livraison_jours,
                    date_livraison_prevue, marque_conforme, marque_proposee,
                    reference_fournisseur, commentaire_ligne, statut_ligne
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'recu')
                """,
                (
                    reponse_entete_id, rfq_uuid, ligne_cotation_id, ligne.code_article,
                    ligne.code_fournisseur, ligne.nom_fournisseur,
                    ligne.email_fournisseur, ligne.telephone_fournisseur,
                    ligne.prix_unitaire_ht, ligne.quantite_disponible,
                    ligne.delai_livraison_jours, ligne.date_livraison_prevue,
                    ligne.marque_conforme, ligne.marque_proposee,
                    ligne.reference_fournisseur, ligne.commentaire_ligne
                ),
                commit=True
            )

        # 8. Mettre à jour le statut de la DA
        execute_query(
            """
            UPDATE demandes_achat
            SET statut = 'cotations_recues', updated_at = NOW()
            WHERE numero_da = %s AND statut IN ('nouveau', 'en_cours')
            """,
            (request.numero_da,),
            commit=True
        )

        return ReponseAcheteurResponse(
            success=True,
            message=f"Réponse saisie avec succès ({len(request.lignes)} ligne(s))",
            numero_rfq=numero_rfq,
            uuid_reponse=uuid_reponse,
            nb_lignes=len(request.lignes)
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la saisie: {str(e)}"
        )


@router.get("/acheteur/list", response_model=ReponseAcheteurListResponse)
async def list_reponses_acheteur(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user)
):
    """Lister les réponses saisies par les acheteurs"""
    offset = (page - 1) * limit

    # Count
    total = execute_query(
        "SELECT COUNT(*) as total FROM reponses_entete_acheteur",
        fetch_one=True
    )["total"]

    # Get entetes
    entetes = execute_query(
        """
        SELECT
            re.id, re.uuid_reponse, re.rfq_uuid, re.devise,
            re.conditions_paiement, re.date_soumission,
            re.commentaire_global, re.saisi_par_email,
            dc.numero_rfq,
            (SELECT numero_da FROM lignes_cotation_acheteur lc WHERE lc.rfq_uuid = re.rfq_uuid LIMIT 1) as numero_da
        FROM reponses_entete_acheteur re
        JOIN demandes_cotation_acheteur dc ON re.rfq_uuid = dc.uuid
        ORDER BY re.date_soumission DESC
        LIMIT %s OFFSET %s
        """,
        (limit, offset)
    )

    reponses = []
    for entete in entetes:
        # Get details
        details = execute_query(
            """
            SELECT
                rd.id, rd.code_article, rd.code_fournisseur,
                rd.nom_fournisseur, rd.email_fournisseur,
                rd.prix_unitaire_ht, rd.quantite_disponible,
                rd.delai_livraison_jours, rd.marque_proposee, rd.statut_ligne,
                lc.designation_article, lc.quantite_demandee
            FROM reponses_detail_acheteur rd
            JOIN lignes_cotation_acheteur lc ON rd.ligne_cotation_id = lc.id
            WHERE rd.reponse_entete_id = %s
            """,
            (entete["id"],)
        )

        reponses.append(ReponseAcheteurComplete(
            id=entete["id"],
            uuid_reponse=entete["uuid_reponse"],
            rfq_uuid=entete["rfq_uuid"],
            numero_rfq=entete["numero_rfq"],
            numero_da=entete["numero_da"] or "",
            devise=entete["devise"],
            conditions_paiement=entete["conditions_paiement"],
            date_soumission=entete["date_soumission"],
            commentaire_global=entete["commentaire_global"],
            saisi_par_email=entete["saisi_par_email"],
            lignes=[LigneReponseAcheteurDetail(**d) for d in details]
        ))

    return ReponseAcheteurListResponse(
        reponses=reponses,
        total=total,
        page=page,
        limit=limit
    )


@router.get("/acheteur/{reponse_id}", response_model=ReponseAcheteurComplete)
async def get_reponse_acheteur(
    reponse_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Obtenir une réponse acheteur par son ID"""
    entete = execute_query(
        """
        SELECT
            re.id, re.uuid_reponse, re.rfq_uuid, re.devise,
            re.conditions_paiement, re.date_soumission,
            re.commentaire_global, re.saisi_par_email,
            dc.numero_rfq,
            (SELECT numero_da FROM lignes_cotation_acheteur lc WHERE lc.rfq_uuid = re.rfq_uuid LIMIT 1) as numero_da
        FROM reponses_entete_acheteur re
        JOIN demandes_cotation_acheteur dc ON re.rfq_uuid = dc.uuid
        WHERE re.id = %s
        """,
        (reponse_id,),
        fetch_one=True
    )

    if not entete:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Réponse non trouvée"
        )

    details = execute_query(
        """
        SELECT
            rd.id, rd.code_article, rd.code_fournisseur,
            rd.nom_fournisseur, rd.email_fournisseur,
            rd.prix_unitaire_ht, rd.quantite_disponible,
            rd.delai_livraison_jours, rd.marque_proposee, rd.statut_ligne,
            lc.designation_article, lc.quantite_demandee
        FROM reponses_detail_acheteur rd
        JOIN lignes_cotation_acheteur lc ON rd.ligne_cotation_id = lc.id
        WHERE rd.reponse_entete_id = %s
        """,
        (reponse_id,)
    )

    return ReponseAcheteurComplete(
        id=entete["id"],
        uuid_reponse=entete["uuid_reponse"],
        rfq_uuid=entete["rfq_uuid"],
        numero_rfq=entete["numero_rfq"],
        numero_da=entete["numero_da"] or "",
        devise=entete["devise"],
        conditions_paiement=entete["conditions_paiement"],
        date_soumission=entete["date_soumission"],
        commentaire_global=entete["commentaire_global"],
        saisi_par_email=entete["saisi_par_email"],
        lignes=[LigneReponseAcheteurDetail(**d) for d in details]
    )


@router.get("/da/{numero_da}/articles")
async def get_articles_da(
    numero_da: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Récupérer les articles d'une DA pour la saisie manuelle.
    Retourne la liste des articles avec leurs informations.
    """
    articles = execute_query(
        """
        SELECT
            da.code_article,
            da.designation_article,
            da.quantite,
            da.unite,
            da.marque_souhaitee,
            ar.prix_base as tarif_reference
        FROM demandes_achat da
        LEFT JOIN articles_ref ar ON da.code_article = ar.code_article
        WHERE da.numero_da = %s
        ORDER BY da.code_article
        """,
        (numero_da,)
    )

    if not articles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Aucun article trouvé pour la DA {numero_da}"
        )

    return {
        "numero_da": numero_da,
        "articles": articles,
        "total": len(articles)
    }


@router.get("/da/list")
async def list_da_disponibles(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user)
):
    """
    Lister les DAs disponibles pour la saisie manuelle.
    Retourne les DAs qui n'ont pas encore de commande créée.
    """
    offset = (page - 1) * limit

    total = execute_query(
        """
        SELECT COUNT(DISTINCT numero_da) as total
        FROM demandes_achat
        WHERE statut IN ('nouveau', 'en_cours', 'cotations_recues')
        """,
        fetch_one=True
    )["total"]

    das = execute_query(
        """
        SELECT
            numero_da,
            COUNT(*) as nb_articles,
            MIN(date_creation_da) as date_creation,
            MAX(statut) as statut
        FROM demandes_achat
        WHERE statut IN ('nouveau', 'en_cours', 'cotations_recues')
        GROUP BY numero_da
        ORDER BY date_creation DESC
        LIMIT %s OFFSET %s
        """,
        (limit, offset)
    )

    return {
        "das": das,
        "total": total,
        "page": page,
        "limit": limit
    }


# ──────────────────────────────────────────────────────────
# Modifier la marque proposée d'une réponse fournisseur
# ──────────────────────────────────────────────────────────

@router.put("/detail/{detail_id}/marque")
async def update_marque_reponse(
    detail_id: int,
    marque: str = Query(..., description="Nouvelle marque"),
    current_user: dict = Depends(get_current_user)
):
    """
    Modifier la marque proposée pour une réponse fournisseur.
    Permet de corriger ou définir la marque avant création du BC.
    """
    try:
        # Récupérer l'ancienne marque
        detail = execute_query(
            """
            SELECT id, marque_proposee
            FROM reponses_fournisseurs_detail
            WHERE id = %s
            """,
            (detail_id,),
            fetch_one=True
        )

        if not detail:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Réponse fournisseur avec id {detail_id} non trouvée"
            )

        ancienne_marque = detail.get("marque_proposee")
        nouvelle_marque = marque.strip()

        # Mettre à jour la marque
        execute_update(
            """
            UPDATE reponses_fournisseurs_detail
            SET marque_proposee = %s,
                date_modification = NOW()
            WHERE id = %s
            """,
            (nouvelle_marque, detail_id)
        )

        logging.info(f"Marque mise à jour pour detail_id={detail_id}: '{ancienne_marque}' -> '{nouvelle_marque}' par {current_user.get('username', 'unknown')}")

        return {
            "success": True,
            "message": "Marque mise à jour avec succès",
            "detail_id": detail_id,
            "ancienne_marque": ancienne_marque,
            "nouvelle_marque": nouvelle_marque
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Erreur modification marque detail_id={detail_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la modification de la marque: {str(e)}"
        )


# ──────────────────────────────────────────────────────────
# Récupérer le PDF du devis fournisseur
# ──────────────────────────────────────────────────────────

# Chemin vers le dossier uploads du formulaire PHP
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "formulaire")


@router.get("/devis/pdf")
async def get_devis_pdf(
    filename: str = Query(..., description="Chemin du fichier PDF"),
    current_user: dict = Depends(get_current_user)
):
    """
    Récupérer le fichier PDF du devis fournisseur.
    Le filename est le chemin relatif stocké en BDD (ex: uploads/2024/03/fichier.pdf)
    """
    # Sécurité: empêcher la traversée de répertoire
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chemin de fichier invalide"
        )

    # Construire le chemin complet
    filepath = os.path.join(UPLOADS_DIR, filename)
    filepath = os.path.normpath(filepath)

    # Vérifier que le fichier existe
    if not os.path.isfile(filepath):
        logging.warning(f"Fichier PDF non trouvé: {filepath}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fichier non trouvé"
        )

    # Retourner le fichier
    return FileResponse(
        path=filepath,
        media_type="application/pdf",
        filename=os.path.basename(filename)
    )


# ──────────────────────────────────────────────────────────
# Saisie Devis par RFQ existant
# ──────────────────────────────────────────────────────────

@router.get("/saisie-rfq/rfqs-disponibles", response_model=RFQPourSaisieListResponse)
async def list_rfqs_pour_saisie(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    code_fournisseur: Optional[str] = None,
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Lister les RFQs disponibles pour saisie de devis.
    Filtre les RFQ avec statut: envoye, vu, relance_1, relance_2, relance_3
    Exclut les RFQ déjà répondus.
    """
    conditions = ["dc.statut IN ('envoye', 'vu', 'relance_1', 'relance_2', 'relance_3')"]
    params = []

    if code_fournisseur:
        conditions.append("dc.code_fournisseur = %s")
        params.append(code_fournisseur)

    if search:
        conditions.append("(dc.numero_rfq LIKE %s OR f.nom_fournisseur LIKE %s)")
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern])

    where_clause = " AND ".join(conditions)

    # Count
    count_query = f"""
        SELECT COUNT(DISTINCT dc.id) as total
        FROM demandes_cotation dc
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE {where_clause}
    """
    total = execute_query(count_query, tuple(params) if params else None, fetch_one=True)["total"]

    # Get RFQs
    offset = (page - 1) * limit
    query = f"""
        SELECT
            dc.uuid,
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur,
            f.email as email_fournisseur,
            dc.date_envoi,
            dc.statut,
            (SELECT COUNT(*) FROM lignes_cotation lc WHERE lc.rfq_uuid = dc.uuid) as nb_articles
        FROM demandes_cotation dc
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE {where_clause}
        ORDER BY dc.date_envoi DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    rfqs = execute_query(query, tuple(params))

    return RFQPourSaisieListResponse(
        rfqs=[RFQPourSaisie(**rfq) for rfq in rfqs],
        total=total,
        page=page,
        limit=limit
    )


@router.get("/saisie-rfq/rfq/{rfq_uuid}", response_model=RFQDetailPourSaisie)
async def get_rfq_pour_saisie(
    rfq_uuid: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Obtenir le détail d'un RFQ pour la saisie de devis.
    Retourne les lignes de cotation avec leurs informations.
    """
    # Get RFQ
    query = """
        SELECT
            dc.uuid,
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur,
            f.email as email_fournisseur,
            dc.date_envoi,
            dc.statut
        FROM demandes_cotation dc
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE dc.uuid = %s
    """
    rfq = execute_query(query, (rfq_uuid,), fetch_one=True)

    if not rfq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RFQ non trouvé"
        )

    # Vérifier que la RFQ n'a pas déjà une réponse
    existing_response = execute_query(
        "SELECT id FROM reponses_fournisseurs_entete WHERE rfq_uuid = %s",
        (rfq_uuid,),
        fetch_one=True
    )

    if existing_response:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce RFQ a déjà une réponse enregistrée"
        )

    # Get lignes de cotation avec info article
    lignes = execute_query(
        """
        SELECT
            lc.id,
            lc.code_article,
            lc.designation_article,
            lc.quantite_demandee,
            lc.unite,
            lc.marque_souhaitee,
            lc.numero_da,
            ar.prix_base as tarif_reference
        FROM lignes_cotation lc
        LEFT JOIN articles_ref ar ON lc.code_article = ar.code_article
        WHERE lc.rfq_uuid = %s
          AND (lc.actif = TRUE OR lc.actif IS NULL)
        ORDER BY lc.code_article
        """,
        (rfq_uuid,)
    )

    return RFQDetailPourSaisie(
        **rfq,
        lignes=[LigneCotationPourSaisie(**l) for l in lignes]
    )


@router.post("/saisie-rfq", response_model=ReponseAcheteurResponse)
async def saisie_devis_rfq(
    request: SaisieDevisRFQRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Saisir un devis pour un RFQ existant.
    Crée une entrée dans reponses_fournisseurs_entete et reponses_fournisseurs_detail.
    Met à jour le statut du RFQ à 'repondu'.
    """
    if not request.lignes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Au moins une ligne est requise"
        )

    # 1. Vérifier que le RFQ existe
    rfq = execute_query(
        """
        SELECT dc.uuid, dc.numero_rfq, dc.code_fournisseur, dc.statut
        FROM demandes_cotation dc
        WHERE dc.uuid = %s
        """,
        (request.rfq_uuid,),
        fetch_one=True
    )

    if not rfq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RFQ non trouvé"
        )

    # 2. Vérifier que le RFQ n'a pas déjà une réponse
    existing_response = execute_query(
        "SELECT id FROM reponses_fournisseurs_entete WHERE rfq_uuid = %s",
        (request.rfq_uuid,),
        fetch_one=True
    )

    if existing_response:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce RFQ a déjà une réponse enregistrée"
        )

    # 3. Vérifier que les lignes de cotation existent
    ligne_ids = [l.ligne_cotation_id for l in request.lignes]
    placeholders = ",".join(["%s"] * len(ligne_ids))
    existing_lignes = execute_query(
        f"""
        SELECT id, code_article FROM lignes_cotation
        WHERE id IN ({placeholders}) AND rfq_uuid = %s
        """,
        (*ligne_ids, request.rfq_uuid)
    )

    if len(existing_lignes) != len(ligne_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Certaines lignes de cotation n'existent pas ou n'appartiennent pas à ce RFQ"
        )

    try:
        # 4. Créer l'entête de réponse
        now = datetime.now()
        reponse_entete_id = execute_insert(
            """
            INSERT INTO reponses_fournisseurs_entete (
                rfq_uuid, reference_fournisseur, devise,
                methodes_paiement, commentaire, date_reponse,
                saisie_manuelle, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
            """,
            (
                request.rfq_uuid,
                request.reference_fournisseur,
                request.devise,
                request.conditions_paiement,
                request.commentaire_global,
                now,
                now
            )
        )

        # 5. Créer les détails de réponse pour chaque ligne
        from datetime import timedelta
        for ligne in request.lignes:
            # Calculer date_livraison si délai fourni
            date_livraison = None
            if ligne.delai_livraison_jours:
                date_livraison = now + timedelta(days=ligne.delai_livraison_jours)

            execute_insert(
                """
                INSERT INTO reponses_fournisseurs_detail (
                    reponse_entete_id, rfq_uuid, ligne_cotation_id, code_article,
                    prix_unitaire_ht, quantite_disponible, date_livraison,
                    marque_proposee, commentaire_article
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    reponse_entete_id,
                    request.rfq_uuid,
                    ligne.ligne_cotation_id,
                    ligne.code_article,
                    ligne.prix_unitaire_ht,
                    ligne.quantite_disponible,
                    date_livraison,
                    ligne.marque_proposee,
                    ligne.commentaire_article
                )
            )

        # 6. Mettre à jour le statut du RFQ
        execute_update(
            """
            UPDATE demandes_cotation
            SET statut = 'repondu', date_reponse = %s
            WHERE uuid = %s
            """,
            (now, request.rfq_uuid)
        )

        logging.info(f"Devis saisi pour RFQ {rfq['numero_rfq']} par {current_user.get('username', 'unknown')}")

        return ReponseAcheteurResponse(
            success=True,
            message=f"Devis enregistré avec succès pour {rfq['numero_rfq']}",
            numero_rfq=rfq["numero_rfq"],
            nb_lignes=len(request.lignes)
        )

    except Exception as e:
        logging.error(f"Erreur saisie devis RFQ: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la saisie: {str(e)}"
        )
