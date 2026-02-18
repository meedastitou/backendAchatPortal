"""
════════════════════════════════════════════════════════════
ROUTER - Gestion des Fournisseurs
════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional

from app.auth.dependencies import get_current_user, get_responsable_or_admin
from app.database import execute_query, execute_insert, execute_update
from app.schemas.fournisseur import (
    FournisseurCreate,
    FournisseurUpdate,
    FournisseurResponse,
    FournisseurListResponse,
    BlacklistRequest,
    BlacklistResponse,
    StatutFournisseur
)


router = APIRouter(prefix="/fournisseurs", tags=["Fournisseurs"])


# ──────────────────────────────────────────────────────────
# Liste des fournisseurs
# ──────────────────────────────────────────────────────────

@router.get("", response_model=FournisseurListResponse)
async def list_fournisseurs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    statut: Optional[StatutFournisseur] = None,
    blacklist: Optional[bool] = None,
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Lister les fournisseurs avec filtres et pagination"""

    # Construction de la requête
    conditions = ["1=1"]
    params = []

    if statut:
        conditions.append("statut = %s")
        params.append(statut.value)

    if blacklist is not None:
        conditions.append("blacklist = %s")
        params.append(blacklist)

    if search:
        conditions.append("(code_fournisseur LIKE %s OR nom_fournisseur LIKE %s OR email LIKE %s)")
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern, search_pattern])

    where_clause = " AND ".join(conditions)

    # Count total
    count_query = f"SELECT COUNT(*) as total FROM fournisseurs WHERE {where_clause}"
    total = execute_query(count_query, tuple(params), fetch_one=True)["total"]

    # Get page
    offset = (page - 1) * limit
    query = f"""
        SELECT * FROM fournisseurs
        WHERE {where_clause}
        ORDER BY nom_fournisseur ASC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    fournisseurs = execute_query(query, tuple(params))

    return FournisseurListResponse(
        fournisseurs=[FournisseurResponse(**f) for f in fournisseurs],
        total=total,
        page=page,
        limit=limit
    )


# ──────────────────────────────────────────────────────────
# Détail d'un fournisseur
# ──────────────────────────────────────────────────────────

@router.get("/{code_fournisseur}", response_model=FournisseurResponse)
async def get_fournisseur(
    code_fournisseur: str,
    current_user: dict = Depends(get_current_user)
):
    """Obtenir les détails d'un fournisseur"""

    query = "SELECT * FROM fournisseurs WHERE code_fournisseur = %s"
    fournisseur = execute_query(query, (code_fournisseur,), fetch_one=True)

    if not fournisseur:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fournisseur non trouvé"
        )

    return FournisseurResponse(**fournisseur)


# ──────────────────────────────────────────────────────────
# Créer un fournisseur
# ──────────────────────────────────────────────────────────

@router.post("", response_model=FournisseurResponse, status_code=status.HTTP_201_CREATED)
async def create_fournisseur(
    data: FournisseurCreate,
    current_user: dict = Depends(get_responsable_or_admin)
):
    """Créer un nouveau fournisseur"""

    # Vérifier si code existe déjà
    existing = execute_query(
        "SELECT id FROM fournisseurs WHERE code_fournisseur = %s",
        (data.code_fournisseur,),
        fetch_one=True
    )
    print(existing)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce code fournisseur existe déjà"
        )

    query = """
        INSERT INTO fournisseurs
        (code_fournisseur, nom_fournisseur, email, telephone, fax, adresse, pays, ville)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    print(12)
    execute_insert(query, (
        data.code_fournisseur,
        data.nom_fournisseur,
        data.email,
        data.telephone,
        data.fax,
        data.adresse,
        data.pays,
        data.ville
    ))

    return await get_fournisseur(data.code_fournisseur, current_user)


# ──────────────────────────────────────────────────────────
# Mettre à jour un fournisseur
# ──────────────────────────────────────────────────────────

@router.put("/{code_fournisseur}", response_model=FournisseurResponse)
async def update_fournisseur(
    code_fournisseur: str,
    data: FournisseurUpdate,
    current_user: dict = Depends(get_responsable_or_admin)
):
    """Mettre à jour un fournisseur"""

    # Vérifier existence
    existing = execute_query(
        "SELECT id FROM fournisseurs WHERE code_fournisseur = %s",
        (code_fournisseur,),
        fetch_one=True
    )
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fournisseur non trouvé"
        )

    # Construire la requête de mise à jour
    updates = []
    params = []

    if data.nom_fournisseur is not None:
        updates.append("nom_fournisseur = %s")
        params.append(data.nom_fournisseur)

    if data.email is not None:
        updates.append("email = %s")
        params.append(data.email)

    if data.telephone is not None:
        updates.append("telephone = %s")
        params.append(data.telephone)

    if data.fax is not None:
        updates.append("fax = %s")
        params.append(data.fax)

    if data.adresse is not None:
        updates.append("adresse = %s")
        params.append(data.adresse)

    if data.pays is not None:
        updates.append("pays = %s")
        params.append(data.pays)

    if data.ville is not None:
        updates.append("ville = %s")
        params.append(data.ville)

    if data.statut is not None:
        updates.append("statut = %s")
        params.append(data.statut.value)

    if updates:
        query = f"UPDATE fournisseurs SET {', '.join(updates)} WHERE code_fournisseur = %s"
        params.append(code_fournisseur)
        execute_update(query, tuple(params))

    return await get_fournisseur(code_fournisseur, current_user)


# ──────────────────────────────────────────────────────────
# Blacklister un fournisseur
# ──────────────────────────────────────────────────────────

@router.post("/{code_fournisseur}/blacklist", response_model=BlacklistResponse)
async def blacklist_fournisseur(
    code_fournisseur: str,
    data: BlacklistRequest,
    current_user: dict = Depends(get_responsable_or_admin)
):
    """Ajouter un fournisseur à la blacklist"""

    query = """
        UPDATE fournisseurs
        SET blacklist = TRUE,
            motif_blacklist = %s,
            date_blacklist = NOW(),
            statut = 'suspendu'
        WHERE code_fournisseur = %s
    """
    rows = execute_update(query, (data.motif, code_fournisseur))

    if rows == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fournisseur non trouvé"
        )

    fournisseur = await get_fournisseur(code_fournisseur, current_user)

    return BlacklistResponse(
        success=True,
        message=f"Fournisseur {code_fournisseur} ajouté à la blacklist",
        fournisseur=fournisseur
    )


# ──────────────────────────────────────────────────────────
# Retirer de la blacklist
# ──────────────────────────────────────────────────────────

@router.delete("/{code_fournisseur}/blacklist", response_model=BlacklistResponse)
async def unblacklist_fournisseur(
    code_fournisseur: str,
    current_user: dict = Depends(get_responsable_or_admin)
):
    """Retirer un fournisseur de la blacklist"""

    query = """
        UPDATE fournisseurs
        SET blacklist = FALSE,
            motif_blacklist = NULL,
            date_blacklist = NULL,
            statut = 'actif'
        WHERE code_fournisseur = %s
    """
    rows = execute_update(query, (code_fournisseur,))

    if rows == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fournisseur non trouvé"
        )

    fournisseur = await get_fournisseur(code_fournisseur, current_user)

    return BlacklistResponse(
        success=True,
        message=f"Fournisseur {code_fournisseur} retiré de la blacklist",
        fournisseur=fournisseur
    )


# ──────────────────────────────────────────────────────────
# Historique des RFQ d'un fournisseur
# ──────────────────────────────────────────────────────────

@router.get("/{code_fournisseur}/rfq")
async def get_fournisseur_rfq_history(
    code_fournisseur: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user)
):
    """Obtenir l'historique des RFQ d'un fournisseur"""

    # Vérifier existence
    fournisseur = execute_query(
        "SELECT id FROM fournisseurs WHERE code_fournisseur = %s",
        (code_fournisseur,),
        fetch_one=True
    )
    if not fournisseur:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fournisseur non trouvé"
        )

    # Count
    total = execute_query(
        "SELECT COUNT(*) as c FROM demandes_cotation WHERE code_fournisseur = %s",
        (code_fournisseur,),
        fetch_one=True
    )["c"]

    # Get RFQs
    offset = (page - 1) * limit
    query = """
        SELECT dc.*, COUNT(lc.id) as nb_articles
        FROM demandes_cotation dc
        LEFT JOIN lignes_cotation lc ON dc.uuid = lc.rfq_uuid
        WHERE dc.code_fournisseur = %s
        GROUP BY dc.id
        ORDER BY dc.date_envoi DESC
        LIMIT %s OFFSET %s
    """
    rfqs = execute_query(query, (code_fournisseur, limit, offset))

    return {
        "rfqs": rfqs,
        "total": total,
        "page": page,
        "limit": limit
    }
