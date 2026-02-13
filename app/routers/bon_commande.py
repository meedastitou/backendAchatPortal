"""
════════════════════════════════════════════════════════════
ROUTER - Bon de Commande (Multi-DA par Fournisseur)
════════════════════════════════════════════════════════════
Un BC peut contenir des lignes de plusieurs DA
Un BC est toujours pour UN seul fournisseur
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional
from datetime import datetime

from app.auth.dependencies import get_current_user
from app.database import execute_query
from app.schemas.bon_commande import (
    DADisponible,
    FournisseurDisponibleBC,
    FournisseursDisponiblesResponse,
    LigneDisponibleBC,
    LignesDisponiblesResponse,
    LigneBCPreparation,
    BCPreparation,
    LigneBCCreate,
    GenerateBCRequest,
    GenerateBCResponse,
    LigneBCResponse,
    BonCommandeResponse,
    BCListResponse,
    StatutBonCommande,
    ConvertOffreToRPARequest,
    ConvertOffreToRPAResponse
)
import uuid
# import httpx  # Pour appeler le RPA


router = APIRouter(prefix="/bon-commande", tags=["Bon de Commande"])


# ──────────────────────────────────────────────────────────
# Fournisseurs disponibles pour créer un BC
# ──────────────────────────────────────────────────────────

@router.get("/fournisseurs-disponibles", response_model=FournisseursDisponiblesResponse)
async def get_fournisseurs_disponibles(
    current_user: dict = Depends(get_current_user)
):
    """
    Liste des fournisseurs ayant des réponses non encore commandées.
    Un fournisseur peut avoir plusieurs DA avec des réponses.
    """

    # Requête pour obtenir les fournisseurs avec leurs réponses disponibles
    # Une ligne est disponible si elle n'a pas encore été commandée
    query = """
        SELECT
            f.code_fournisseur,
            f.nom_fournisseur,
            f.email,
            f.telephone,
            re.id as reponse_id,
            da.numero_da,
            dc.numero_rfq,
            re.date_reponse,
            COUNT(rd.id) as nb_lignes,
            COALESCE(SUM(rd.prix_unitaire_ht * COALESCE(rd.quantite_disponible, lc.quantite_demandee)), 0) as montant_ht
        FROM fournisseurs f
        JOIN demandes_cotation dc ON f.code_fournisseur = dc.code_fournisseur
        JOIN reponses_fournisseurs_entete re ON dc.uuid = re.rfq_uuid
        JOIN reponses_fournisseurs_detail rd ON re.id = rd.reponse_entete_id
        JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        JOIN demandes_achat da ON dc.numero_da = da.numero_da
        WHERE rd.prix_unitaire_ht IS NOT NULL
          AND f.statut = 'actif'
          AND f.blacklist = 0
          AND NOT EXISTS (
              SELECT 1 FROM lignes_bon_commande lbc
              WHERE lbc.ligne_source_id = rd.id
          )
        GROUP BY f.code_fournisseur, f.nom_fournisseur, f.email, f.telephone,
                 re.id, da.numero_da, dc.numero_rfq, re.date_reponse
        ORDER BY f.nom_fournisseur, da.numero_da
    """
    results = execute_query(query)

    # Grouper par fournisseur
    fournisseurs_dict = {}
    for row in results:
        code = row["code_fournisseur"]
        if code not in fournisseurs_dict:
            fournisseurs_dict[code] = {
                "code_fournisseur": code,
                "nom_fournisseur": row["nom_fournisseur"],
                "email": row["email"],
                "telephone": row["telephone"],
                "das_disponibles": [],
                "nb_lignes_total": 0,
                "montant_total_ht": 0.0
            }

        da = DADisponible(
            numero_da=row["numero_da"],
            numero_rfq=row["numero_rfq"],
            reponse_id=row["reponse_id"],
            date_reponse=row["date_reponse"],
            nb_lignes=row["nb_lignes"],
            montant_total_ht=float(row["montant_ht"]) if row["montant_ht"] else 0.0
        )
        fournisseurs_dict[code]["das_disponibles"].append(da)
        fournisseurs_dict[code]["nb_lignes_total"] += row["nb_lignes"]
        fournisseurs_dict[code]["montant_total_ht"] += float(row["montant_ht"]) if row["montant_ht"] else 0.0

    # Construire la liste finale
    fournisseurs = []
    for code, data in fournisseurs_dict.items():
        fournisseurs.append(FournisseurDisponibleBC(
            code_fournisseur=data["code_fournisseur"],
            nom_fournisseur=data["nom_fournisseur"],
            email=data["email"],
            telephone=data["telephone"],
            nb_da_disponibles=len(data["das_disponibles"]),
            nb_lignes_total=data["nb_lignes_total"],
            montant_total_ht=round(data["montant_total_ht"], 2),
            das_disponibles=data["das_disponibles"]
        ))

    return FournisseursDisponiblesResponse(
        fournisseurs=fournisseurs,
        total=len(fournisseurs)
    )


# ──────────────────────────────────────────────────────────
# Lignes disponibles d'un fournisseur
# ──────────────────────────────────────────────────────────

@router.get("/lignes/{code_fournisseur}", response_model=LignesDisponiblesResponse)
async def get_lignes_fournisseur(
    code_fournisseur: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Récupérer toutes les lignes disponibles d'un fournisseur (de toutes ses DA).
    Ces lignes peuvent être sélectionnées pour créer un BC.
    """

    # Vérifier que le fournisseur existe
    fournisseur = execute_query(
        "SELECT * FROM fournisseurs WHERE code_fournisseur = %s",
        (code_fournisseur,),
        fetch_one=True
    )
    if not fournisseur:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fournisseur non trouvé"
        )

    # Récupérer toutes les lignes disponibles
    query = """
        SELECT
            rd.id as ligne_id,
            re.id as reponse_id,
            da.numero_da,
            dc.numero_rfq,
            rd.code_article,
            lc.designation_article as designation,
            lc.quantite_demandee,
            COALESCE(rd.quantite_disponible, lc.quantite_demandee) as quantite_disponible,
            lc.unite,
            rd.prix_unitaire_ht,
            rd.date_livraison,
            rd.delai_livraison as delai_livraison_jours,
            rd.marque_proposee
        FROM reponses_fournisseurs_detail rd
        JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
        JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        JOIN demandes_achat da ON dc.numero_da = da.numero_da
        JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
        WHERE dc.code_fournisseur = %s
          AND rd.prix_unitaire_ht IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM lignes_bon_commande lbc
              WHERE lbc.ligne_source_id = rd.id
          )
        ORDER BY da.numero_da, rd.code_article
    """
    results = execute_query(query, (code_fournisseur,))

    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune ligne disponible pour ce fournisseur"
        )

    # Construire les lignes
    lignes = []
    das_set = set()
    montant_total_ht = 0.0
    tva_pourcent = 20.0

    for row in results:
        quantite = float(row["quantite_disponible"])
        prix_ht = float(row["prix_unitaire_ht"])
        montant_ligne_ht = quantite * prix_ht
        montant_ligne_ttc = montant_ligne_ht * (1 + tva_pourcent / 100)

        ligne = LigneDisponibleBC(
            ligne_id=row["ligne_id"],
            reponse_id=row["reponse_id"],
            numero_da=row["numero_da"],
            numero_rfq=row["numero_rfq"],
            code_article=row["code_article"],
            designation=row["designation"],
            quantite_demandee=float(row["quantite_demandee"]),
            quantite_disponible=quantite,
            unite=row["unite"],
            prix_unitaire_ht=prix_ht,
            montant_ligne_ht=round(montant_ligne_ht, 2),
            tva_pourcent=tva_pourcent,
            montant_ligne_ttc=round(montant_ligne_ttc, 2),
            delai_livraison_jours=row["delai_livraison_jours"],
            date_livraison_prevue=row["date_livraison"],
            marque_proposee=row["marque_proposee"],
            selectionne=True
        )
        lignes.append(ligne)
        das_set.add(row["numero_da"])
        montant_total_ht += montant_ligne_ht

    montant_tva = montant_total_ht * (tva_pourcent / 100)
    montant_total_ttc = montant_total_ht + montant_tva

    return LignesDisponiblesResponse(
        code_fournisseur=code_fournisseur,
        nom_fournisseur=fournisseur["nom_fournisseur"],
        email_fournisseur=fournisseur["email"],
        lignes=lignes,
        montant_total_ht=round(montant_total_ht, 2),
        montant_tva=round(montant_tva, 2),
        montant_total_ttc=round(montant_total_ttc, 2),
        nb_lignes=len(lignes),
        nb_da=len(das_set)
    )


# ──────────────────────────────────────────────────────────
# Générer le Bon de Commande
# ──────────────────────────────────────────────────────────

@router.post("/generer", response_model=GenerateBCResponse)
async def generer_bon_commande(
    request: GenerateBCRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Générer un bon de commande avec les lignes sélectionnées.
    Les lignes peuvent provenir de plusieurs DA.
    """

    if not request.lignes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucune ligne sélectionnée"
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

    # Vérifier que les lignes n'ont pas déjà été commandées
    ligne_ids = [l.ligne_id for l in request.lignes]
    placeholders = ",".join(["%s"] * len(ligne_ids))
    existing = execute_query(
        f"SELECT ligne_source_id FROM lignes_bon_commande WHERE ligne_source_id IN ({placeholders})",
        tuple(ligne_ids)
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Certaines lignes ont déjà été commandées"
        )

    # Générer le numéro de BC
    year = datetime.now().year
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

    # Calculer les totaux et collecter les DA
    montant_total_ht = 0.0
    das_set = set()
    tva_moyenne = 0.0

    for ligne in request.lignes:
        montant_total_ht += ligne.quantite * ligne.prix_unitaire_ht
        tva_moyenne += ligne.tva_pourcent

    tva_moyenne = tva_moyenne / len(request.lignes) if request.lignes else 20.0
    montant_tva = montant_total_ht * (tva_moyenne / 100)
    montant_total_ttc = montant_total_ht + montant_tva

    # Récupérer les infos des lignes sources pour les DA
    for ligne in request.lignes:
        ligne_info = execute_query(
            """
            SELECT da.numero_da
            FROM reponses_fournisseurs_detail rd
            JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
            JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
            JOIN demandes_achat da ON dc.numero_da = da.numero_da
            WHERE rd.id = %s
            """,
            (ligne.ligne_id,),
            fetch_one=True
        )
        if ligne_info:
            das_set.add(ligne_info["numero_da"])

    das_incluses = list(das_set)

    # Créer le bon de commande
    insert_bc = """
        INSERT INTO bons_commande (
            numero_bc, code_fournisseur,
            date_creation, montant_total_ht, montant_tva, montant_total_ttc,
            devise, statut, conditions_paiement, lieu_livraison, commentaire,
            creee_par
        ) VALUES (%s, %s, NOW(), %s, %s, %s, 'MAD', 'brouillon', %s, %s, %s, %s)
    """
    execute_query(insert_bc, (
        numero_bc,
        request.code_fournisseur,
        round(montant_total_ht, 2),
        round(montant_tva, 2),
        round(montant_total_ttc, 2),
        request.conditions_paiement,
        request.lieu_livraison,
        request.commentaire,
        current_user.get("username")
    ))

    # Créer les lignes de BC
    for ligne in request.lignes:
        montant_ligne_ht = ligne.quantite * ligne.prix_unitaire_ht
        montant_ligne_ttc = montant_ligne_ht * (1 + ligne.tva_pourcent / 100)

        # Récupérer les infos de la ligne source
        ligne_source = execute_query(
            """
            SELECT
                rd.id,
                da.numero_da,
                dc.numero_rfq,
                lc.unite
            FROM reponses_fournisseurs_detail rd
            JOIN reponses_fournisseurs_entete re ON rd.reponse_entete_id = re.id
            JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
            JOIN demandes_achat da ON dc.numero_da = da.numero_da
            JOIN lignes_cotation lc ON rd.ligne_cotation_id = lc.id
            WHERE rd.id = %s
            """,
            (ligne.ligne_id,),
            fetch_one=True
        )

        insert_ligne = """
            INSERT INTO lignes_bon_commande (
                numero_bc, ligne_source_id, reponse_id,
                numero_da, numero_rfq,
                code_article, designation, quantite, unite,
                prix_unitaire_ht, montant_ligne_ht, tva_pourcent, montant_ligne_ttc,
                date_livraison_prevue, commentaire
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        execute_query(insert_ligne, (
            numero_bc,
            ligne.ligne_id,
            ligne.reponse_id,
            ligne_source["numero_da"] if ligne_source else None,
            ligne_source["numero_rfq"] if ligne_source else None,
            ligne.code_article,
            ligne.designation,
            ligne.quantite,
            ligne_source["unite"] if ligne_source else None,
            ligne.prix_unitaire_ht,
            round(montant_ligne_ht, 2),
            ligne.tva_pourcent,
            round(montant_ligne_ttc, 2),
            ligne.date_livraison_prevue,
            ligne.commentaire
        ))

    return GenerateBCResponse(
        success=True,
        numero_bc=numero_bc,
        message=f"Bon de commande {numero_bc} créé avec succès",
        montant_total_ht=round(montant_total_ht, 2),
        montant_total_ttc=round(montant_total_ttc, 2),
        code_fournisseur=request.code_fournisseur,
        nom_fournisseur=fournisseur["nom_fournisseur"],
        nb_lignes=len(request.lignes),
        das_incluses=das_incluses
    )


# ──────────────────────────────────────────────────────────
# Liste des Bons de Commande
# ──────────────────────────────────────────────────────────

@router.get("", response_model=BCListResponse)
async def list_bons_commande(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    statut: Optional[str] = None,
    code_fournisseur: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Liste des bons de commande"""

    conditions = ["1=1"]
    params = []

    if statut:
        conditions.append("bc.statut = %s")
        params.append(statut)

    if code_fournisseur:
        conditions.append("bc.code_fournisseur = %s")
        params.append(code_fournisseur)

    where_clause = " AND ".join(conditions)

    # Count
    count_query = f"""
        SELECT COUNT(*) as total FROM bons_commande bc WHERE {where_clause}
    """
    total = execute_query(count_query, tuple(params), fetch_one=True)["total"]
    
    # Get BCs
    offset = (page - 1) * limit
    query = f"""
        SELECT
            bc.*,
            f.nom_fournisseur
        FROM bons_commande bc
        JOIN fournisseurs f ON bc.code_fournisseur = f.code_fournisseur
        WHERE {where_clause}
        ORDER BY bc.date_creation DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    bcs = execute_query(query, tuple(params))

    # Construire la réponse
    bc_list = []
    for bc in bcs:
        # Récupérer les lignes
        lignes = execute_query(
            "SELECT * FROM lignes_bon_commande WHERE numero_bc = %s",
            (bc["numero_bc"],)
        )

        # Collecter les DA uniques
        das_incluses = list(set(l["numero_da"] for l in lignes if l.get("numero_da")))

        bc_response = BonCommandeResponse(
            id=bc["id"],
            numero_bc=bc["numero_bc"],
            code_fournisseur=bc["code_fournisseur"],
            nom_fournisseur=bc["nom_fournisseur"],
            date_creation=bc["date_creation"],
            date_validation=bc.get("date_validation"),
            validee_par=bc.get("validee_par"),
            montant_total_ht=float(bc["montant_total_ht"]),
            montant_tva=float(bc["montant_tva"]),
            montant_total_ttc=float(bc["montant_total_ttc"]),
            devise=bc["devise"],
            statut=bc["statut"],
            conditions_paiement=bc.get("conditions_paiement"),
            lieu_livraison=bc.get("lieu_livraison"),
            commentaire=bc.get("commentaire"),
            lignes=[LigneBCResponse(
                id=l["id"],
                numero_bc=l["numero_bc"],
                ligne_source_id=l.get("ligne_source_id"),
                reponse_id=l.get("reponse_id"),
                numero_da=l.get("numero_da"),
                numero_rfq=l.get("numero_rfq"),
                code_article=l["code_article"],
                designation=l.get("designation"),
                quantite=float(l["quantite"]),
                unite=l.get("unite"),
                prix_unitaire_ht=float(l["prix_unitaire_ht"]),
                montant_ligne_ht=float(l["montant_ligne_ht"]),
                tva_pourcent=float(l["tva_pourcent"]),
                montant_ligne_ttc=float(l["montant_ligne_ttc"]),
                date_livraison_prevue=l.get("date_livraison_prevue"),
                commentaire=l.get("commentaire")
            ) for l in lignes],
            das_incluses=das_incluses,
            nb_lignes=len(lignes)
        )
        bc_list.append(bc_response)

    return BCListResponse(
        bons_commande=bc_list,
        total=total,
        page=page,
        limit=limit
    )


# ──────────────────────────────────────────────────────────
# Détail d'un Bon de Commande
# ──────────────────────────────────────────────────────────

@router.get("/{numero_bc}", response_model=BonCommandeResponse)
async def get_bon_commande(
    numero_bc: str,
    current_user: dict = Depends(get_current_user)
):
    """Obtenir les détails d'un bon de commande"""

    query = """
        SELECT bc.*, f.nom_fournisseur
        FROM bons_commande bc
        JOIN fournisseurs f ON bc.code_fournisseur = f.code_fournisseur
        WHERE bc.numero_bc = %s
    """
    bc = execute_query(query, (numero_bc,), fetch_one=True)

    if not bc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bon de commande non trouvé"
        )

    lignes = execute_query(
        "SELECT * FROM lignes_bon_commande WHERE numero_bc = %s",
        (numero_bc,)
    )

    das_incluses = list(set(l["numero_da"] for l in lignes if l.get("numero_da")))

    return BonCommandeResponse(
        id=bc["id"],
        numero_bc=bc["numero_bc"],
        code_fournisseur=bc["code_fournisseur"],
        nom_fournisseur=bc["nom_fournisseur"],
        date_creation=bc["date_creation"],
        date_validation=bc.get("date_validation"),
        validee_par=bc.get("validee_par"),
        montant_total_ht=float(bc["montant_total_ht"]),
        montant_tva=float(bc["montant_tva"]),
        montant_total_ttc=float(bc["montant_total_ttc"]),
        devise=bc["devise"],
        statut=bc["statut"],
        conditions_paiement=bc.get("conditions_paiement"),
        lieu_livraison=bc.get("lieu_livraison"),
        commentaire=bc.get("commentaire"),
        lignes=[LigneBCResponse(
            id=l["id"],
            numero_bc=l["numero_bc"],
            ligne_source_id=l.get("ligne_source_id"),
            reponse_id=l.get("reponse_id"),
            numero_da=l.get("numero_da"),
            numero_rfq=l.get("numero_rfq"),
            code_article=l["code_article"],
            designation=l.get("designation"),
            quantite=float(l["quantite"]),
            unite=l.get("unite"),
            prix_unitaire_ht=float(l["prix_unitaire_ht"]),
            montant_ligne_ht=float(l["montant_ligne_ht"]),
            tva_pourcent=float(l["tva_pourcent"]),
            montant_ligne_ttc=float(l["montant_ligne_ttc"]),
            date_livraison_prevue=l.get("date_livraison_prevue"),
            commentaire=l.get("commentaire")
        ) for l in lignes],
        das_incluses=das_incluses,
        nb_lignes=len(lignes)
    )


# ──────────────────────────────────────────────────────────
# Valider un Bon de Commande
# ──────────────────────────────────────────────────────────

@router.post("/{numero_bc}/valider", response_model=BonCommandeResponse)
async def valider_bon_commande(
    numero_bc: str,
    current_user: dict = Depends(get_current_user)
):
    """Valider un bon de commande (passer de brouillon à validé)"""

    bc = execute_query(
        "SELECT * FROM bons_commande WHERE numero_bc = %s",
        (numero_bc,),
        fetch_one=True
    )

    if not bc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bon de commande non trouvé"
        )

    if bc["statut"] != "brouillon":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Le BC ne peut pas être validé (statut actuel: {bc['statut']})"
        )

    execute_query(
        """
        UPDATE bons_commande
        SET statut = 'valide', date_validation = NOW(), validee_par = %s
        WHERE numero_bc = %s
        """,
        (current_user.get("username"), numero_bc)
    )

    return await get_bon_commande(numero_bc, current_user)


# ──────────────────────────────────────────────────────────
# Convertir Offre vers BC via RPA (Sage X3)
# ──────────────────────────────────────────────────────────

@router.post("/convert-to-rpa", response_model=ConvertOffreToRPAResponse)
async def convert_offre_to_rpa(
    request: ConvertOffreToRPARequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Convertir une offre fournisseur en Bon de Commande via RPA.
    Les articles sélectionnés sont envoyés à un projet RPA qui va
    saisir les données dans Sage X3.
    """
    print("Conversion offre vers RPA demandée:", request)
    exit(0)
    if not request.articles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucun article sélectionné"
        )

    # Récupérer les infos de la réponse fournisseur
    reponse_query = """
        SELECT
            re.id,
            re.rfq_uuid,
            re.devise,
            re.reference_fournisseur,
            dc.numero_rfq,
            dc.code_fournisseur,
            da.numero_da,
            f.nom_fournisseur,
            f.email as email_fournisseur
        FROM reponses_fournisseurs_entete re
        JOIN demandes_cotation dc ON re.rfq_uuid = dc.uuid
        JOIN demandes_achat da ON dc.numero_da = da.numero_da
        JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
        WHERE re.id = %s
    """
    reponse = execute_query(reponse_query, (request.reponse_id,), fetch_one=True)

    if not reponse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Réponse fournisseur non trouvée"
        )

    # Générer un ID unique pour cette requête RPA
    rpa_request_id = f"RPA-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:8].upper()}"

    # Calculer le montant total
    montant_total_ht = sum(
        art.quantite * art.prix_unitaire_ht for art in request.articles
    )

    # Préparer le payload pour le RPA
    payload_rpa = {
        "request_id": rpa_request_id,
        "timestamp": datetime.now().isoformat(),
        "user": current_user.get("username"),

        # Infos fournisseur
        "fournisseur": {
            "code": reponse["code_fournisseur"],
            "nom": reponse["nom_fournisseur"],
            "email": reponse["email_fournisseur"]
        },

        # Infos source
        "source": {
            "reponse_id": request.reponse_id,
            "numero_rfq": reponse["numero_rfq"],
            "numero_da": reponse["numero_da"],
            "reference_fournisseur": reponse["reference_fournisseur"]
        },

        # Articles à commander
        "articles": [
            {
                "ligne_id": art.ligne_detail_id,
                "code_article": art.code_article,
                "designation": art.designation,
                "quantite": art.quantite,
                "unite": art.unite,
                "prix_unitaire_ht": art.prix_unitaire_ht,
                "tva_pourcent": art.tva_pourcent,
                "montant_ht": round(art.quantite * art.prix_unitaire_ht, 2),
                "date_livraison": art.date_livraison,
                "marque": art.marque,
                "commentaire": art.commentaire
            }
            for art in request.articles
        ],

        # Totaux
        "totaux": {
            "montant_ht": round(montant_total_ht, 2),
            "tva_pourcent": 20.0,
            "montant_tva": round(montant_total_ht * 0.20, 2),
            "montant_ttc": round(montant_total_ht * 1.20, 2),
            "devise": reponse["devise"] or "MAD"
        },

        # Conditions BC
        "conditions": {
            "paiement": request.conditions_paiement,
            "lieu_livraison": request.lieu_livraison,
            "commentaire": request.commentaire_bc
        }
    }

    # Log la requête RPA
    log_query = """
        INSERT INTO logs_systeme (niveau, module, action, message, donnees_json, user_id, date_log)
        VALUES ('info', 'bon_commande', 'rpa_bc_request', %s, %s, %s, NOW())
    """
    execute_query(log_query, (
        f"Conversion offre {request.reponse_id} vers BC via RPA",
        str(payload_rpa),
        current_user.get("id")
    ))

    # TODO: Appeler le projet RPA ici
    # Pour l'instant, on simule le succès
    # Exemple d'appel futur:
    # async with httpx.AsyncClient() as client:
    #     rpa_response = await client.post(
    #         "http://rpa-server:8080/api/sage-x3/create-bc",
    #         json=payload_rpa,
    #         timeout=30.0
    #     )

    return ConvertOffreToRPAResponse(
        success=True,
        message=f"Demande de création BC envoyée au RPA avec succès",
        rpa_request_id=rpa_request_id,
        code_fournisseur=reponse["code_fournisseur"],
        nom_fournisseur=reponse["nom_fournisseur"],
        nb_articles=len(request.articles),
        montant_total_ht=round(montant_total_ht, 2),
        payload_rpa=payload_rpa
    )
