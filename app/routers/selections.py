"""
════════════════════════════════════════════════════════════
ROUTER - Selections Articles (Pre-Bon de Commande)
════════════════════════════════════════════════════════════
"""

import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional, List

from app.auth.dependencies import get_current_user
from app.database import execute_query, execute_insert, execute_update, get_cursor

# Configuration RPA API
RPA_API_URL = "http://localhost:8001/api/bonne-commande/data"
from app.schemas.selection import (
    SelectionArticleCreate,
    SelectionArticleUpdate,
    SelectionArticleResponse,
    SelectionAutoResponse,
    PreBCDashboardResponse,
    FournisseurPreBC,
    ArticleSelectionne,
    GenererBCFromPreBCRequest,
    GenererBCFromPreBCResponse,
    StatutSelection
)
from datetime import datetime


router = APIRouter(prefix="/selections", tags=["Selections Articles"])


# ──────────────────────────────────────────────────────────
# Selection automatique (meilleur prix)
# ──────────────────────────────────────────────────────────

@router.post("/auto", response_model=SelectionAutoResponse)
async def selection_automatique(
    current_user: dict = Depends(get_current_user)
):
    """
    Selection automatique du meilleur prix pour tous les articles
    ayant des reponses fournisseurs et pas encore selectionnes.
    """

    # Recuperer tous les articles avec reponses, groupes par article+DA
    # On prend le meilleur prix (prix min) pour chaque article/DA
    query = """
        SELECT
            rd.code_article,
            lc.designation_article as designation,
            lc.numero_da,
            lc.quantite_demandee as quantite,
            lc.unite,
            rd.id as detail_id,
            dc.code_fournisseur,
            rd.prix_unitaire_ht as prix,
            re.devise,
            rd.marque_proposee,
            rd.marque_conforme,
            rd.date_livraison,
            rd.delai_livraison
        FROM reponses_fournisseurs_detail rd
        JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        JOIN demandes_cotation dc ON rd.rfq_uuid = dc.uuid
        WHERE rd.prix_unitaire_ht IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM selections_articles sa
              WHERE sa.code_article = rd.code_article
                AND sa.numero_da = lc.numero_da
                AND sa.statut != 'bc_genere'
          )
        ORDER BY rd.code_article, lc.numero_da, rd.prix_unitaire_ht ASC
    """

    rows = execute_query(query)

    if not rows:
        return SelectionAutoResponse(
            success=True,
            message="Aucun nouvel article a selectionner",
            nb_articles_selectionnes=0,
            selections=[]
        )

    # Grouper par article+DA et prendre le premier (meilleur prix)
    articles_da_dict = {}
    for row in rows:
        key = (row["code_article"], row["numero_da"])
        if key not in articles_da_dict:
            articles_da_dict[key] = row

    # Inserer les selections
    selections = []
    for (code_article, numero_da), data in articles_da_dict.items():
        insert_query = """
            INSERT INTO selections_articles (
                code_article, designation, numero_da, quantite, unite,
                code_fournisseur, detail_id, prix_selectionne, devise,
                marque_proposee, marque_conforme, date_livraison, delai_livraison,
                selection_auto, modifie_par, statut
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                TRUE, %s, 'selectionne'
            )
        """
        params = (
            data["code_article"],
            data["designation"],
            data["numero_da"],
            data["quantite"],
            data["unite"],
            data["code_fournisseur"],
            data["detail_id"],
            data["prix"],
            data["devise"] or "MAD",
            data["marque_proposee"],
            data["marque_conforme"],
            data["date_livraison"],
            data["delai_livraison"],
            current_user.get("username", "system")
        )

        try:
            selection_id = execute_insert(insert_query, params)
            selections.append(SelectionArticleResponse(
                id=selection_id,
                code_article=data["code_article"],
                designation=data["designation"],
                numero_da=data["numero_da"],
                quantite=data["quantite"],
                unite=data["unite"],
                code_fournisseur=data["code_fournisseur"],
                detail_id=data["detail_id"],
                prix_selectionne=data["prix"],
                devise=data["devise"] or "MAD",
                marque_proposee=data["marque_proposee"],
                marque_conforme=data["marque_conforme"],
                date_livraison=data["date_livraison"],
                delai_livraison=data["delai_livraison"],
                selection_auto=True,
                modifie_par=current_user.get("username"),
                date_selection=datetime.now(),
                date_modification=None,
                statut=StatutSelection.SELECTIONNE,
                numero_bc=None
            ))
        except Exception as e:
            # Ignorer les doublons (contrainte unique)
            if "Duplicate" not in str(e):
                raise

    return SelectionAutoResponse(
        success=True,
        message=f"{len(selections)} article(s) selectionne(s) automatiquement",
        nb_articles_selectionnes=len(selections),
        selections=selections
    )


# ──────────────────────────────────────────────────────────
# CRUD Selections
# ──────────────────────────────────────────────────────────

@router.get("", response_model=List[SelectionArticleResponse])
async def list_selections(
    statut: Optional[str] = None,
    code_fournisseur: Optional[str] = None,
    numero_da: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Lister toutes les selections"""

    conditions = ["1=1"]
    params = []

    if statut:
        conditions.append("sa.statut = %s")
        params.append(statut)

    if code_fournisseur:
        conditions.append("sa.code_fournisseur = %s")
        params.append(code_fournisseur)

    if numero_da:
        conditions.append("sa.numero_da = %s")
        params.append(numero_da)

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            sa.*,
            f.nom_fournisseur
        FROM selections_articles sa
        JOIN fournisseurs f ON sa.code_fournisseur = f.code_fournisseur
        WHERE {where_clause}
        ORDER BY sa.date_selection DESC
    """

    rows = execute_query(query, tuple(params))

    return [SelectionArticleResponse(
        id=row["id"],
        code_article=row["code_article"],
        designation=row["designation"],
        numero_da=row["numero_da"],
        quantite=row["quantite"],
        unite=row["unite"],
        code_fournisseur=row["code_fournisseur"],
        nom_fournisseur=row["nom_fournisseur"],
        detail_id=row["detail_id"],
        prix_selectionne=row["prix_selectionne"],
        devise=row["devise"],
        marque_proposee=row["marque_proposee"],
        marque_conforme=row["marque_conforme"],
        date_livraison=row["date_livraison"],
        delai_livraison=row["delai_livraison"],
        selection_auto=row["selection_auto"],
        modifie_par=row["modifie_par"],
        date_selection=row["date_selection"],
        date_modification=row["date_modification"],
        statut=row["statut"],
        numero_bc=row["numero_bc"]
    ) for row in rows]


@router.post("", response_model=SelectionArticleResponse)
async def create_selection(
    selection: SelectionArticleCreate,
    current_user: dict = Depends(get_current_user)
):
    """Creer une selection manuelle"""

    # Verifier si une selection existe deja pour cet article/DA
    existing = execute_query(
        """
        SELECT id FROM selections_articles
        WHERE code_article = %s AND numero_da = %s AND statut != 'bc_genere'
        """,
        (selection.code_article, selection.numero_da),
        fetch_one=True
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Une selection existe deja pour cet article/DA. Utilisez PUT pour modifier."
        )

    insert_query = """
        INSERT INTO selections_articles (
            code_article, designation, numero_da, quantite, unite,
            code_fournisseur, detail_id, prix_selectionne, devise,
            marque_proposee, marque_conforme, date_livraison, delai_livraison,
            selection_auto, modifie_par, statut
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            FALSE, %s, 'selectionne'
        )
    """
    params = (
        selection.code_article,
        selection.designation,
        selection.numero_da,
        selection.quantite,
        selection.unite,
        selection.code_fournisseur,
        selection.detail_id,
        selection.prix_selectionne,
        selection.devise,
        selection.marque_proposee,
        selection.marque_conforme,
        selection.date_livraison,
        selection.delai_livraison,
        current_user.get("username", "system")
    )

    selection_id = execute_insert(insert_query, params)

    # Recuperer le nom du fournisseur
    fournisseur = execute_query(
        "SELECT nom_fournisseur FROM fournisseurs WHERE code_fournisseur = %s",
        (selection.code_fournisseur,),
        fetch_one=True
    )
    
    return SelectionArticleResponse(
        id=selection_id,
        code_article=selection.code_article,
        designation=selection.designation,
        numero_da=selection.numero_da,
        quantite=selection.quantite,
        unite=selection.unite,
        code_fournisseur=selection.code_fournisseur,
        nom_fournisseur=fournisseur["nom_fournisseur"] if fournisseur else None,
        detail_id=selection.detail_id,
        prix_selectionne=selection.prix_selectionne,
        devise=selection.devise,
        marque_proposee=selection.marque_proposee,
        marque_conforme=selection.marque_conforme,
        date_livraison=selection.date_livraison,
        delai_livraison=selection.delai_livraison,
        selection_auto=False,
        modifie_par=current_user.get("username"),
        date_selection=datetime.now(),
        date_modification=None,
        statut=StatutSelection.SELECTIONNE,
        numero_bc=None
    )


@router.put("/{selection_id}", response_model=SelectionArticleResponse)
async def update_selection(
    selection_id: int,
    update: SelectionArticleUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Modifier une selection (changer de fournisseur)"""

    # Verifier que la selection existe et n'est pas deja en BC
    existing = execute_query(
        "SELECT * FROM selections_articles WHERE id = %s",
        (selection_id,),
        fetch_one=True
    )

    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selection non trouvee"
        )

    if existing["statut"] == "bc_genere":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de modifier une selection deja convertie en BC"
        )

    update_query = """
        UPDATE selections_articles SET
            code_fournisseur = %s,
            detail_id = %s,
            prix_selectionne = %s,
            devise = %s,
            marque_proposee = %s,
            marque_conforme = %s,
            date_livraison = %s,
            delai_livraison = %s,
            selection_auto = FALSE,
            modifie_par = %s
        WHERE id = %s
    """
    params = (
        update.code_fournisseur,
        update.detail_id,
        update.prix_selectionne,
        update.devise,
        update.marque_proposee,
        update.marque_conforme,
        update.date_livraison,
        update.delai_livraison,
        current_user.get("username", "system"),
        selection_id
    )

    execute_update(update_query, params)

    # Recuperer la selection mise a jour
    updated = execute_query(
        """
        SELECT sa.*, f.nom_fournisseur
        FROM selections_articles sa
        JOIN fournisseurs f ON sa.code_fournisseur = f.code_fournisseur
        WHERE sa.id = %s
        """,
        (selection_id,),
        fetch_one=True
    )

    return SelectionArticleResponse(
        id=updated["id"],
        code_article=updated["code_article"],
        designation=updated["designation"],
        numero_da=updated["numero_da"],
        quantite=updated["quantite"],
        unite=updated["unite"],
        code_fournisseur=updated["code_fournisseur"],
        nom_fournisseur=updated["nom_fournisseur"],
        detail_id=updated["detail_id"],
        prix_selectionne=updated["prix_selectionne"],
        devise=updated["devise"],
        marque_proposee=updated["marque_proposee"],
        marque_conforme=updated["marque_conforme"],
        date_livraison=updated["date_livraison"],
        delai_livraison=updated["delai_livraison"],
        selection_auto=updated["selection_auto"],
        modifie_par=updated["modifie_par"],
        date_selection=updated["date_selection"],
        date_modification=updated["date_modification"],
        statut=updated["statut"],
        numero_bc=updated["numero_bc"]
    )


@router.delete("/{selection_id}")
async def delete_selection(
    selection_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Supprimer une selection"""

    existing = execute_query(
        "SELECT statut FROM selections_articles WHERE id = %s",
        (selection_id,),
        fetch_one=True
    )

    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selection non trouvee"
        )

    if existing["statut"] == "bc_genere":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de supprimer une selection deja convertie en BC"
        )

    execute_update("DELETE FROM selections_articles WHERE id = %s", (selection_id,))

    return {"success": True, "message": "Selection supprimee"}


# ──────────────────────────────────────────────────────────
# Dashboard Pre-BC (groupe par fournisseur)
# ──────────────────────────────────────────────────────────

@router.get("/pre-bc", response_model=PreBCDashboardResponse)
async def get_pre_bc_dashboard(
    current_user: dict = Depends(get_current_user)
):
    """
    Recuperer le dashboard Pre-BC avec les selections groupees par fournisseur.
    Seules les selections avec statut 'selectionne' sont incluses.
    """

    query = """
        SELECT
            sa.*,
            f.nom_fournisseur,
            f.email,
            f.telephone
        FROM selections_articles sa
        JOIN fournisseurs f ON sa.code_fournisseur = f.code_fournisseur
        WHERE sa.statut = 'selectionne'
        ORDER BY sa.code_fournisseur, sa.numero_da, sa.code_article
    """

    rows = execute_query(query)

    if not rows:
        return PreBCDashboardResponse(
            fournisseurs=[],
            total_fournisseurs=0,
            total_articles=0,
            total_das=0,
            montant_global_ht=0.0
        )

    # Grouper par fournisseur
    fournisseurs_dict = {}
    all_das = set()

    for row in rows:
        code_f = row["code_fournisseur"]

        if code_f not in fournisseurs_dict:
            fournisseurs_dict[code_f] = {
                "code_fournisseur": code_f,
                "nom_fournisseur": row["nom_fournisseur"],
                "email": row["email"],
                "telephone": row["telephone"],
                "articles": [],
                "das": set(),
                "montant_total_ht": 0.0,
                "devise": row["devise"] or "MAD"
            }

        montant_ligne = float(row["prix_selectionne"]) * float(row["quantite"])

        fournisseurs_dict[code_f]["articles"].append(ArticleSelectionne(
            id=row["id"],
            code_article=row["code_article"],
            designation=row["designation"],
            numero_da=row["numero_da"],
            quantite=float(row["quantite"]),
            unite=row["unite"],
            prix_unitaire=float(row["prix_selectionne"]),
            montant_ligne=montant_ligne,
            devise=row["devise"] or "MAD",
            marque_proposee=row["marque_proposee"],
            marque_conforme=row["marque_conforme"],
            date_livraison=row["date_livraison"],
            selection_auto=row["selection_auto"]
        ))

        fournisseurs_dict[code_f]["das"].add(row["numero_da"])
        fournisseurs_dict[code_f]["montant_total_ht"] += montant_ligne
        all_das.add(row["numero_da"])

    # Construire la reponse
    fournisseurs = []
    montant_global = 0.0

    for code_f, data in fournisseurs_dict.items():
        fournisseurs.append(FournisseurPreBC(
            code_fournisseur=data["code_fournisseur"],
            nom_fournisseur=data["nom_fournisseur"],
            email=data["email"],
            telephone=data["telephone"],
            articles=data["articles"],
            nb_articles=len(data["articles"]),
            nb_das=len(data["das"]),
            das=list(data["das"]),
            montant_total_ht=data["montant_total_ht"],
            devise=data["devise"]
        ))
        montant_global += data["montant_total_ht"]

    # Trier par montant total decroissant
    fournisseurs.sort(key=lambda x: x.montant_total_ht, reverse=True)

    return PreBCDashboardResponse(
        fournisseurs=fournisseurs,
        total_fournisseurs=len(fournisseurs),
        total_articles=sum(f.nb_articles for f in fournisseurs),
        total_das=len(all_das),
        montant_global_ht=montant_global
    )


# ──────────────────────────────────────────────────────────
# Generation BC depuis Pre-BC
# ──────────────────────────────────────────────────────────

@router.post("/generer-bc", response_model=GenererBCFromPreBCResponse)
async def generer_bc_from_pre_bc(
    request: GenererBCFromPreBCRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Generer un bon de commande a partir des selections Pre-BC.
    Met a jour le statut des selections en 'bc_genere'.
    Envoie les donnees a l'API RPA pour creation dans Sage X3.
    """

    # Verifier que les selections existent et appartiennent au fournisseur
    placeholders = ",".join(["%s"] * len(request.selection_ids))
    query = f"""
        SELECT sa.*, f.nom_fournisseur, f.email as email_fournisseur, f.telephone as tel_fournisseur
        FROM selections_articles sa
        JOIN fournisseurs f ON sa.code_fournisseur = f.code_fournisseur
        WHERE sa.id IN ({placeholders})
          AND sa.code_fournisseur = %s
          AND sa.statut = 'selectionne'
    """
    print(00)
    params = tuple(request.selection_ids) + (request.code_fournisseur,)
    selections = execute_query(query, params)
    print(0)
    if len(selections) != len(request.selection_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Certaines selections sont invalides ou deja converties en BC"
        )
    print(1)
    # Generer le numero BC
    year = datetime.now().year
    last_bc = execute_query(
        """
        SELECT numero_bc FROM bons_commande
        WHERE numero_bc LIKE %s
        ORDER BY id DESC LIMIT 1
        """,
        (f"BC-{year}-%",),
        fetch_one=True
    )
    print(2)
    if last_bc:
        last_num = int(last_bc["numero_bc"].split("-")[-1])
        new_num = last_num + 1
    else:
        new_num = 1
    print(3)
    numero_bc = f"BC-{year}-{new_num:04d}"
    # Calculer les totaux
    montant_total_ht = sum(
        float(s["prix_selectionne"]) * float(s["quantite"])
        for s in selections
    )
    tva_pourcent = 20.0
    montant_tva = montant_total_ht * tva_pourcent / 100
    montant_total_ttc = montant_total_ht + montant_tva

    # Creer le BC
    with get_cursor() as cursor:
        # Insert BC header
        cursor.execute(
            """
            INSERT INTO bons_commande (
                numero_bc, code_fournisseur, montant_total_ht, montant_tva,
                montant_total_ttc, devise, statut, conditions_paiement,
                lieu_livraison, commentaire, creee_par
            ) VALUES (%s, %s, %s, %s, %s, %s, 'brouillon', %s, %s, %s, %s)
            """,
            (
                numero_bc,
                request.code_fournisseur,
                montant_total_ht,
                montant_tva,
                montant_total_ttc,
                selections[0]["devise"] or "MAD",
                request.conditions_paiement,
                request.lieu_livraison,
                request.commentaire,
                current_user.get("username", "system")
            )
        )

        # Insert BC lines
        for sel in selections:
            montant_ligne_ht = float(sel["prix_selectionne"]) * float(sel["quantite"])
            montant_ligne_ttc = montant_ligne_ht * (1 + tva_pourcent / 100)

            cursor.execute(
                """
                INSERT INTO lignes_bon_commande (
                    numero_bc, ligne_source_id, numero_da, code_article,
                    designation, quantite, unite, prix_unitaire_ht,
                    montant_ligne_ht, tva_pourcent, montant_ligne_ttc,
                    date_livraison_prevue
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    numero_bc,
                    sel["detail_id"],
                    sel["numero_da"],
                    sel["code_article"],
                    sel["designation"],
                    sel["quantite"],
                    sel["unite"],
                    sel["prix_selectionne"],
                    montant_ligne_ht,
                    tva_pourcent,
                    montant_ligne_ttc,
                    sel["date_livraison"]
                )
            )

        # Update selections status
        cursor.execute(
            f"""
            UPDATE selections_articles
            SET statut = 'bc_genere', numero_bc = %s
            WHERE id IN ({placeholders})
            """,
            (numero_bc,) + tuple(request.selection_ids)
        )

    nom_fournisseur = selections[0]["nom_fournisseur"] if selections else None
    email_fournisseur = selections[0]["email_fournisseur"] if selections else ""
    tel_fournisseur = selections[0]["tel_fournisseur"] if selections else ""

    # Preparer les donnees pour l'API RPA
    acheteur = current_user.get("username", "ACHAT")
    donnees_rpa = []

    for sel in selections:
        donnees_rpa.append({
            "Numero_DA": sel["numero_da"],
            "Acheteur": acheteur,
            "Code_Fournisseur": sel["code_fournisseur"],
            "Email_Fournisseur": email_fournisseur or "",
            "TEL_Fournisseu": tel_fournisseur or "",
            "Code_Article": sel["code_article"],
            "Montant": float(sel["prix_selectionne"]),
            "Marque": sel["marque_proposee"] or "",
            "Affaire": ""
        })

    # Appeler l'API RPA
    # L'email expediteur est l'email de l'acheteur connecte
    email_acheteur = current_user.get("email", "")

    rpa_payload = {
        "donnees": donnees_rpa,
        "email_expediteur": email_acheteur,
        "headless": True  # Mode headless en production
    }

    rpa_success = False
    rpa_message = ""

    try:
        print(4)
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                RPA_API_URL,
                json=rpa_payload,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 200:
                rpa_success = True
                rpa_message = "Donnees envoyees au RPA avec succes"
                logging.info(f"RPA API call successful for BC {numero_bc}")
                print(6)
            else:
                rpa_message = f"Erreur RPA: {response.status_code} - {response.text}"
                logging.error(f"RPA API error for BC {numero_bc}: {rpa_message}")
                print(7)
        print(5)
    except httpx.TimeoutException:
        rpa_message = "Timeout lors de l'appel RPA"
        logging.error(f"RPA API timeout for BC {numero_bc}")
    except Exception as e:
        rpa_message = f"Erreur RPA: {str(e)}"
        logging.error(f"RPA API exception for BC {numero_bc}: {e}")

    # Le BC est cree meme si le RPA echoue
    message = f"Bon de commande {numero_bc} genere avec succes"
    if rpa_success:
        message += ". " + rpa_message
    else:
        message += f". Attention: {rpa_message}"

    return GenererBCFromPreBCResponse(
        success=True,
        message=message,
        numero_bc=numero_bc,
        code_fournisseur=request.code_fournisseur,
        nom_fournisseur=nom_fournisseur,
        nb_lignes=len(selections),
        montant_total_ht=montant_total_ht,
        montant_total_ttc=montant_total_ttc
    )
