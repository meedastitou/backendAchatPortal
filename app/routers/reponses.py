"""
════════════════════════════════════════════════════════════
ROUTER - Réponses Fournisseurs
════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional

from app.auth.dependencies import get_current_user
from app.database import execute_query
from app.schemas.reponse import (
    ReponseEnteteResponse,
    ReponseDetailResponse,
    ReponseComplete,
    ReponseListResponse,
    ComparaisonArticle,
    ComparaisonResponse,
    RejetResponse
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
    date_debut: Optional[datetime] = None,
    date_fin: Optional[datetime] = None,
    current_user: dict = Depends(get_current_user)
):
    """Lister toutes les réponses fournisseurs"""

    conditions = ["1=1"]
    params = []

    if code_fournisseur:
        conditions.append("dc.code_fournisseur = %s")
        params.append(code_fournisseur)

    if date_debut:
        conditions.append("re.date_reponse >= %s")
        params.append(date_debut)

    if date_fin:
        conditions.append("re.date_reponse <= %s")
        params.append(date_fin)

    where_clause = " AND ".join(conditions)

    # Count
    count_query = f"""
        SELECT COUNT(*) as total
        FROM reponses_fournisseurs_entete re
        JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        WHERE {where_clause}
    """
    total = execute_query(count_query, tuple(params), fetch_one=True)["total"]

    # Get entetes
    offset = (page - 1) * limit
    query = f"""
        SELECT
            re.*,
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur
        FROM reponses_fournisseurs_entete re
        JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
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
    Retourne tous les articles ayant des réponses fournisseurs,
    groupés par article avec les DAs associées et les offres.

    IMPORTANT: Si un même fournisseur répond sur le même article plusieurs fois
    (car l'article est dans différentes DAs) avec la même entête de réponse,
    on n'affiche qu'une seule offre pour éviter les doublons.

    FILTRE: Exclut les articles/DA deja selectionnes ou convertis en BC.
    """

    # Récupérer tous les articles avec réponses
    # Exclure les articles/DA qui ont deja une selection (peu importe le statut)
    query = """
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
            ar.prix_base as tarif_reference
        FROM reponses_fournisseurs_detail rd
        JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        JOIN demandes_cotation dc ON rd.rfq_uuid = dc.uuid
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        LEFT JOIN articles_ref ar ON rd.code_article = ar.code_article
        WHERE rd.prix_unitaire_ht IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM selections_articles sa
              WHERE sa.code_article = rd.code_article
                AND sa.numero_da = lc.numero_da
          )
        ORDER BY rd.code_article, rd.prix_unitaire_ht ASC
    """

    rows = execute_query(query)

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

        # Clé de déduplication: même fournisseur + même entête réponse = même offre
        offre_key = (row["code_fournisseur"], row["reponse_entete_id"])

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
                "date_reponse": row["date_reponse"]
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
