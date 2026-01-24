"""
════════════════════════════════════════════════════════════
ROUTER - Décision Achat (Comparaison & Validation)
════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional
from datetime import datetime

from app.auth.dependencies import get_current_user
from app.database import execute_query
from app.schemas.decision import (
    DAEnAttenteDecision,
    DAAttenteListResponse,
    DADecisionDetail,
    ArticleComparaison,
    OffreFournisseur,
    CreateCommandeRequest,
    CreateCommandeResponse
)


router = APIRouter(prefix="/decision", tags=["Decision Achat"])


# ──────────────────────────────────────────────────────────
# Liste des DA en attente de décision
# ──────────────────────────────────────────────────────────

@router.get("/da-en-attente", response_model=DAAttenteListResponse)
async def get_da_en_attente(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    priorite: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Obtenir les DA qui ont des réponses fournisseurs mais pas encore de commande créée.
    Ces DA sont prêtes pour la prise de décision.
    """

    # Requête pour trouver les DA avec réponses sans commande
    # Une DA est en attente si:
    # 1. Elle a au moins une RFQ avec statut 'repondu'
    # 2. Elle n'a pas de commande associée
    base_query = """
        SELECT DISTINCT
            da.id,
            da.numero_da,
            da.date_creation_da,
            da.date_besoin,
            da.priorite,
            da.statut,
            (SELECT COUNT(DISTINCT lc.code_article)
             FROM lignes_cotation lc
             JOIN demandes_cotation dc ON lc.rfq_uuid = dc.uuid
             WHERE lc.numero_da = da.numero_da) as nb_articles,
            (SELECT COUNT(DISTINCT dc.code_fournisseur)
             FROM demandes_cotation dc
             JOIN lignes_cotation lc ON dc.uuid = lc.rfq_uuid
             WHERE lc.numero_da = da.numero_da) as nb_fournisseurs_sollicites,
            (SELECT COUNT(DISTINCT dc.code_fournisseur)
             FROM demandes_cotation dc
             JOIN lignes_cotation lc ON dc.uuid = lc.rfq_uuid
             WHERE lc.numero_da = da.numero_da AND dc.statut = 'repondu') as nb_reponses_recues,
            (SELECT MIN(re.date_reponse)
             FROM reponses_fournisseurs_entete re
             JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
             JOIN lignes_cotation lc ON dc.uuid = lc.rfq_uuid
             WHERE lc.numero_da = da.numero_da) as date_premiere_reponse,
            (SELECT MAX(re.date_reponse)
             FROM reponses_fournisseurs_entete re
             JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
             JOIN lignes_cotation lc ON dc.uuid = lc.rfq_uuid
             WHERE lc.numero_da = da.numero_da) as date_derniere_reponse
        FROM demandes_achat da
        WHERE da.statut NOT IN ('commande_creee', 'annule')
          AND EXISTS (
              SELECT 1 FROM demandes_cotation dc
              JOIN lignes_cotation lc ON dc.uuid = lc.rfq_uuid
              WHERE lc.numero_da = da.numero_da AND dc.statut = 'repondu'
          )
          AND NOT EXISTS (
              SELECT 1 FROM commandes c WHERE c.numero_da = da.numero_da
          )
    """

    params = []
    if priorite:
        base_query += " AND da.priorite = %s"
        params.append(priorite)

    # Count total
    count_query = f"SELECT COUNT(*) as total FROM ({base_query}) as sub"
    total_result = execute_query(count_query, tuple(params), fetch_one=True)
    total = total_result["total"] if total_result else 0

    # Get paginated results
    offset = (page - 1) * limit
    query = base_query + " ORDER BY da.priorite DESC, da.date_besoin ASC, da.date_creation_da ASC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    da_results = execute_query(query, tuple(params))

    da_list = []
    total_articles = 0
    montant_min_global = 0
    montant_max_global = 0

    for da_row in da_results:
        # Récupérer les articles avec leurs offres pour cette DA
        articles = await get_articles_comparaison(da_row["numero_da"])

        nb_fournisseurs = da_row["nb_fournisseurs_sollicites"] or 0
        nb_reponses = da_row["nb_reponses_recues"] or 0
        taux_reponse = (nb_reponses / nb_fournisseurs * 100) if nb_fournisseurs > 0 else 0

        # Calculer montants min/max
        montant_min = sum(a.prix_min * a.quantite_demandee for a in articles if a.prix_min) or None
        montant_max = sum(a.prix_max * a.quantite_demandee for a in articles if a.prix_max) or None

        if montant_min:
            montant_min_global += montant_min
        if montant_max:
            montant_max_global += montant_max

        # Calculer jours depuis première réponse
        jours_depuis = None
        if da_row["date_premiere_reponse"]:
            delta = datetime.now() - da_row["date_premiere_reponse"]
            jours_depuis = delta.days

        da_obj = DAEnAttenteDecision(
            id=da_row["id"],
            numero_da=da_row["numero_da"],
            date_creation_da=da_row["date_creation_da"],
            date_besoin=da_row["date_besoin"],
            priorite=da_row["priorite"],
            statut=da_row["statut"],
            nb_articles=len(articles),
            nb_fournisseurs_sollicites=nb_fournisseurs,
            nb_reponses_recues=nb_reponses,
            taux_reponse=round(taux_reponse, 1),
            articles=articles,
            montant_min_total=round(montant_min, 2) if montant_min else None,
            montant_max_total=round(montant_max, 2) if montant_max else None,
            date_premiere_reponse=da_row["date_premiere_reponse"],
            date_derniere_reponse=da_row["date_derniere_reponse"],
            jours_depuis_premiere_reponse=jours_depuis
        )
        da_list.append(da_obj)
        total_articles += len(articles)

    return DAAttenteListResponse(
        da_list=da_list,
        total=total,
        page=page,
        limit=limit,
        total_articles_a_decider=total_articles,
        montant_potentiel_min=round(montant_min_global, 2) if montant_min_global else None,
        montant_potentiel_max=round(montant_max_global, 2) if montant_max_global else None
    )


# ──────────────────────────────────────────────────────────
# Détail d'une DA pour décision
# ──────────────────────────────────────────────────────────

@router.get("/da/{numero_da}", response_model=DADecisionDetail)
async def get_da_decision_detail(
    numero_da: str,
    current_user: dict = Depends(get_current_user)
):
    """Obtenir le détail complet d'une DA pour prise de décision"""

    # Vérifier que la DA existe
    da_query = """
        SELECT * FROM demandes_achat WHERE numero_da = %s
    """
    da = execute_query(da_query, (numero_da,))
    
    if not da:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demande d'achat non trouvée"
        )

    # Vérifier qu'il n'y a pas déjà de commande
    commande_check = execute_query(
        "SELECT numero_commande FROM commandes WHERE numero_da = %s",
        (numero_da,),
        fetch_one=True
    )
    if commande_check:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Une commande existe déjà pour cette DA: {commande_check['numero_commande']}"
        )

    # Récupérer les articles avec comparaison
    articles = await get_articles_comparaison(numero_da)

    # Récupérer les RFQ envoyées
    rfqs_query = """
        SELECT DISTINCT
            dc.id,
            dc.numero_rfq,
            dc.code_fournisseur,
            f.nom_fournisseur,
            dc.date_envoi,
            dc.statut,
            dc.nb_relances,
            dc.date_reponse
        FROM demandes_cotation dc
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        JOIN lignes_cotation lc ON dc.uuid = lc.rfq_uuid
        WHERE lc.numero_da = %s
        ORDER BY dc.date_envoi DESC
    """
    rfqs = execute_query(rfqs_query, (numero_da,))

    # Stats
    nb_fournisseurs = len(set(r["code_fournisseur"] for r in rfqs))
    nb_reponses = len([r for r in rfqs if r["statut"] == "repondu"])
    taux_reponse = (nb_reponses / nb_fournisseurs * 100) if nb_fournisseurs > 0 else 0

    # Dates
    dates_reponse = [r["date_reponse"] for r in rfqs if r["date_reponse"]]
    date_premiere = min(dates_reponse) if dates_reponse else None
    date_derniere = max(dates_reponse) if dates_reponse else None

    jours_depuis = None
    if date_premiere:
        delta = datetime.now() - date_premiere
        jours_depuis = delta.days

    # Montants
    montant_min = sum(a.prix_min * a.quantite_demandee for a in articles if a.prix_min) or None
    montant_max = sum(a.prix_max * a.quantite_demandee for a in articles if a.prix_max) or None

    # Recommandation globale (fournisseur qui propose le meilleur rapport qualité/prix)
    fournisseur_scores = {}
    for article in articles:
        for offre in article.offres:
            if offre.code_fournisseur not in fournisseur_scores:
                fournisseur_scores[offre.code_fournisseur] = {
                    "nom": offre.nom_fournisseur,
                    "total_score": 0,
                    "nb_articles": 0,
                    "montant_total": 0
                }
            if offre.score_global:
                fournisseur_scores[offre.code_fournisseur]["total_score"] += offre.score_global
                fournisseur_scores[offre.code_fournisseur]["nb_articles"] += 1
            if offre.prix_unitaire_ht:
                fournisseur_scores[offre.code_fournisseur]["montant_total"] += (
                    offre.prix_unitaire_ht * article.quantite_demandee
                )

    # Trouver le meilleur fournisseur global
    best_fournisseur = None
    best_score = 0
    best_montant = None
    raison = None

    for code, data in fournisseur_scores.items():
        if data["nb_articles"] > 0:
            avg_score = data["total_score"] / data["nb_articles"]
            if avg_score > best_score:
                best_score = avg_score
                best_fournisseur = code
                best_montant = data["montant_total"]
                raison = f"Score moyen: {avg_score:.0f}/100, {data['nb_articles']} article(s) proposé(s)"

    return DADecisionDetail(
        id=da["id"],
        numero_da=da["numero_da"],
        date_creation_da=da["date_creation_da"],
        date_besoin=da["date_besoin"],
        priorite=da["priorite"],
        statut=da["statut"],
        nb_articles=len(articles),
        nb_fournisseurs_sollicites=nb_fournisseurs,
        nb_reponses_recues=nb_reponses,
        taux_reponse=round(taux_reponse, 1),
        articles=articles,
        montant_min_total=round(montant_min, 2) if montant_min else None,
        montant_max_total=round(montant_max, 2) if montant_max else None,
        date_premiere_reponse=date_premiere,
        date_derniere_reponse=date_derniere,
        jours_depuis_premiere_reponse=jours_depuis,
        rfqs_envoyees=rfqs,
        fournisseur_recommande_global=best_fournisseur,
        raison_recommandation=raison,
        montant_recommande=round(best_montant, 2) if best_montant else None
    )


# ──────────────────────────────────────────────────────────
# Fonction utilitaire: Récupérer articles avec comparaison
# ──────────────────────────────────────────────────────────

async def get_articles_comparaison(numero_da: str) -> list[ArticleComparaison]:
    """Récupérer tous les articles d'une DA avec leurs offres comparées"""

    # Récupérer les articles distincts de la DA
    articles_query = """
        SELECT DISTINCT
            lc.code_article,
            lc.designation_article,
            lc.quantite_demandee,
            lc.unite,
            lc.marque_souhaitee
        FROM lignes_cotation lc
        WHERE lc.numero_da = %s
    """
    articles_rows = execute_query(articles_query, (numero_da,))

    articles = []
    for art_row in articles_rows:
        # Récupérer toutes les offres pour cet article
        offres_query = """
            SELECT
                rd.prix_unitaire_ht,
                rd.quantite_disponible,
                rd.date_livraison,
                rd.marque_conforme,
                rd.marque_proposee,
                rd.commentaire_article,
                dc.code_fournisseur,
                f.nom_fournisseur,
                dc.numero_rfq,
                re.devise,
                re.date_reponse,
                DATEDIFF(rd.date_livraison, NOW()) as delai_jours
            FROM reponses_fournisseurs_detail rd
            JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
            JOIN demandes_cotation dc ON rd.rfq_uuid = dc.uuid
            JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
            JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
            WHERE lc.numero_da = %s
              AND rd.code_article = %s
              AND dc.statut = 'repondu'
        """
        offres_rows = execute_query(offres_query, (numero_da, art_row["code_article"]))

        offres = []
        prix_list = []

        for offre_row in offres_rows:
            prix = offre_row["prix_unitaire_ht"]
            if prix:
                prix_list.append(prix)

            offre = OffreFournisseur(
                code_fournisseur=offre_row["code_fournisseur"],
                nom_fournisseur=offre_row["nom_fournisseur"],
                numero_rfq=offre_row["numero_rfq"],
                prix_unitaire_ht=float(prix) if prix else None,
                quantite_disponible=float(offre_row["quantite_disponible"]) if offre_row["quantite_disponible"] else None,
                date_livraison=offre_row["date_livraison"],
                delai_jours=offre_row["delai_jours"],
                marque_conforme=offre_row["marque_conforme"],
                marque_proposee=offre_row["marque_proposee"],
                devise=offre_row["devise"] or "MAD",
                commentaire=offre_row["commentaire_article"],
                date_reponse=offre_row["date_reponse"]
            )
            offres.append(offre)

        # Calculer les scores
        if prix_list:
            prix_min = min(prix_list)
            prix_max = max(prix_list)
            prix_moyen = sum(prix_list) / len(prix_list)
            ecart = ((prix_max - prix_min) / prix_min * 100) if prix_min > 0 else 0

            # Attribuer les scores
            for offre in offres:
                if offre.prix_unitaire_ht:
                    # Score prix: 100 pour le moins cher, diminue proportionnellement
                    if prix_max > prix_min:
                        offre.score_prix = 100 - ((offre.prix_unitaire_ht - prix_min) / (prix_max - prix_min) * 100)
                    else:
                        offre.score_prix = 100

                    # Score délai: bonus si délai court
                    if offre.delai_jours is not None:
                        if offre.delai_jours <= 7:
                            offre.score_delai = 100
                        elif offre.delai_jours <= 14:
                            offre.score_delai = 80
                        elif offre.delai_jours <= 30:
                            offre.score_delai = 60
                        else:
                            offre.score_delai = 40
                    else:
                        offre.score_delai = 50  # Pas d'info

                    # Score global: 70% prix, 30% délai
                    offre.score_global = (offre.score_prix * 0.7) + (offre.score_delai * 0.3)

            # Trouver les meilleurs
            meilleur_prix = min(offres, key=lambda o: o.prix_unitaire_ht or float('inf'))
            offres_avec_delai = [o for o in offres if o.delai_jours is not None]
            meilleur_delai = min(offres_avec_delai, key=lambda o: o.delai_jours) if offres_avec_delai else None
            meilleur_global = max(offres, key=lambda o: o.score_global or 0)

            article = ArticleComparaison(
                code_article=art_row["code_article"],
                designation=art_row["designation_article"],
                quantite_demandee=float(art_row["quantite_demandee"]),
                unite=art_row["unite"],
                marque_souhaitee=art_row["marque_souhaitee"],
                offres=offres,
                nb_offres=len(offres),
                prix_min=prix_min,
                prix_max=prix_max,
                prix_moyen=round(prix_moyen, 2),
                ecart_prix_pourcent=round(ecart, 1),
                meilleur_prix_fournisseur=meilleur_prix.nom_fournisseur if meilleur_prix.prix_unitaire_ht else None,
                meilleur_delai_fournisseur=meilleur_delai.nom_fournisseur if meilleur_delai else None,
                recommande_fournisseur=meilleur_global.nom_fournisseur,
                recommande_raison=f"Score: {meilleur_global.score_global:.0f}/100"
            )
        else:
            article = ArticleComparaison(
                code_article=art_row["code_article"],
                designation=art_row["designation_article"],
                quantite_demandee=float(art_row["quantite_demandee"]),
                unite=art_row["unite"],
                marque_souhaitee=art_row["marque_souhaitee"],
                offres=offres,
                nb_offres=len(offres)
            )

        articles.append(article)

    return articles


# ──────────────────────────────────────────────────────────
# Créer une commande
# ──────────────────────────────────────────────────────────

@router.post("/creer-commande", response_model=CreateCommandeResponse)
async def creer_commande(
    request: CreateCommandeRequest,
    current_user: dict = Depends(get_current_user)
):
    """Créer une commande à partir d'une décision d'achat"""

    # Vérifier que la DA existe
    da = execute_query(
        "SELECT * FROM demandes_achat WHERE numero_da = %s",
        (request.numero_da,),
        fetch_one=True
    )
    if not da:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demande d'achat non trouvée"
        )

    # Vérifier qu'il n'y a pas déjà de commande
    existing = execute_query(
        "SELECT numero_commande FROM commandes WHERE numero_da = %s",
        (request.numero_da,),
        fetch_one=True
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Une commande existe déjà: {existing['numero_commande']}"
        )

    # Vérifier que le fournisseur existe
    fournisseur = execute_query(
        "SELECT * FROM fournisseurs WHERE code_fournisseur = %s",
        (request.code_fournisseur,),
        fetch_one=True
    )
    if not fournisseur:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fournisseur non trouvé"
        )

    # Générer le numéro de commande
    year = datetime.now().year
    last_cmd = execute_query(
        "SELECT numero_commande FROM commandes WHERE numero_commande LIKE %s ORDER BY id DESC LIMIT 1",
        (f"CMD-{year}-%",),
        fetch_one=True
    )
    if last_cmd:
        last_num = int(last_cmd["numero_commande"].split("-")[-1])
        new_num = last_num + 1
    else:
        new_num = 1

    numero_commande = f"CMD-{year}-{new_num:04d}"

    # Calculer le montant total
    montant_total_ht = 0
    for article in request.articles:
        montant_total_ht += article["prix_unitaire_ht"] * article["quantite"]

    montant_total_ttc = montant_total_ht * 1.20  # TVA 20%

    # Insérer la commande
    insert_cmd = """
        INSERT INTO commandes (
            numero_commande, numero_da, code_fournisseur, date_commande,
            montant_total_ht, montant_total_ttc, statut
        ) VALUES (%s, %s, %s, NOW(), %s, %s, 'brouillon')
    """
    execute_query(insert_cmd, (
        numero_commande, request.numero_da, request.code_fournisseur,
        montant_total_ht, montant_total_ttc
    ))

    # Insérer les lignes de commande
    for article in request.articles:
        montant_ligne_ht = article["prix_unitaire_ht"] * article["quantite"]
        montant_ligne_ttc = montant_ligne_ht * 1.20

        insert_ligne = """
            INSERT INTO lignes_commande (
                numero_commande, code_article, designation, quantite,
                prix_unitaire_ht, montant_ligne_ht, montant_ligne_ttc
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        execute_query(insert_ligne, (
            numero_commande, article["code_article"],
            article.get("designation", ""), article["quantite"],
            article["prix_unitaire_ht"], montant_ligne_ht, montant_ligne_ttc
        ))

    # Mettre à jour le statut de la DA
    execute_query(
        "UPDATE demandes_achat SET statut = 'commande_creee' WHERE numero_da = %s",
        (request.numero_da,)
    )

    return CreateCommandeResponse(
        success=True,
        numero_commande=numero_commande,
        message=f"Commande {numero_commande} créée avec succès",
        montant_total_ht=round(montant_total_ht, 2)
    )
