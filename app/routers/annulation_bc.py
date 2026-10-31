"""
════════════════════════════════════════════════════════════
ROUTER - Annulation Bon de Commande
════════════════════════════════════════════════════════════
Permet aux utilisateurs de demander l'annulation d'un BC
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional

from app.auth.dependencies import get_current_user
from app.database import execute_query
from app.schemas.annulation_bc import (
    AnnulationBCCreate,
    AnnulationBC,
    AnnulationBCResponse,
    AnnulationBCListResponse,
    StatutAnnulation
)


router = APIRouter(prefix="/annulation-bc", tags=["Annulation BC"])


# ──────────────────────────────────────────────────────────
# Créer une demande d'annulation
# ──────────────────────────────────────────────────────────

@router.post("", response_model=AnnulationBCResponse)
async def creer_demande_annulation(
    request: AnnulationBCCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Créer une demande d'annulation de bon de commande.
    Le champ demande_par est automatiquement rempli avec le username de l'utilisateur connecté.
    """

    # Vérifier que le numéro de commande n'est pas vide
    if not request.numero_commande.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le numéro de commande est obligatoire"
        )

    if not request.motif_annulation.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le motif d'annulation est obligatoire"
        )

    # Récupérer le username de l'utilisateur connecté
    demande_par = current_user.get("username")

    # Insérer la demande d'annulation
    insert_query = """
        INSERT INTO annulation_bc (
            numero_commande,
            motif_annulation,
            demande_par,
            statut
        ) VALUES (%s, %s, %s, 'en_attente')
    """
    execute_query(insert_query, (
        request.numero_commande.strip(),
        request.motif_annulation.strip(),
        demande_par
    ))

    # Récupérer l'annulation créée
    annulation = execute_query(
        """
        SELECT * FROM annulation_bc
        WHERE numero_commande = %s AND demande_par = %s
        ORDER BY id DESC LIMIT 1
        """,
        (request.numero_commande.strip(), demande_par),
        fetch_one=True
    )

    return AnnulationBCResponse(
        success=True,
        message=f"Demande d'annulation créée avec succès pour la commande {request.numero_commande}",
        annulation=AnnulationBC(
            id=annulation["id"],
            numero_commande=annulation["numero_commande"],
            motif_annulation=annulation["motif_annulation"],
            demande_par=annulation["demande_par"],
            statut=annulation["statut"],
            numero_abc=annulation.get("numero_abc"),
            code_tier=annulation.get("code_tier"),
            email_fournisseur=annulation.get("email_fournisseur"),
            created_at=annulation["created_at"]
        )
    )


# ──────────────────────────────────────────────────────────
# Liste des demandes d'annulation
# ──────────────────────────────────────────────────────────

@router.get("", response_model=AnnulationBCListResponse)
async def liste_demandes_annulation(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    statut: Optional[str] = None,
    numero_commande: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Liste des demandes d'annulation avec filtres optionnels.
    """

    conditions = ["1=1"]
    params = []

    if statut:
        conditions.append("statut = %s")
        params.append(statut)

    if numero_commande:
        conditions.append("numero_commande LIKE %s")
        params.append(f"%{numero_commande}%")

    where_clause = " AND ".join(conditions)

    # Count total
    count_query = f"SELECT COUNT(*) as total FROM annulation_bc WHERE {where_clause}"
    total = execute_query(count_query, tuple(params), fetch_one=True)["total"]

    # Get annulations
    offset = (page - 1) * limit
    query = f"""
        SELECT * FROM annulation_bc
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    annulations = execute_query(query, tuple(params))

    return AnnulationBCListResponse(
        annulations=[
            AnnulationBC(
                id=a["id"],
                numero_commande=a["numero_commande"],
                motif_annulation=a["motif_annulation"],
                demande_par=a["demande_par"],
                statut=a["statut"],
                numero_abc=a.get("numero_abc"),
                code_tier=a.get("code_tier"),
                email_fournisseur=a.get("email_fournisseur"),
                created_at=a["created_at"]
            ) for a in annulations
        ],
        total=total,
        page=page,
        limit=limit
    )


# ──────────────────────────────────────────────────────────
# Détail d'une demande d'annulation
# ──────────────────────────────────────────────────────────

@router.get("/{id}", response_model=AnnulationBC)
async def get_demande_annulation(
    id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Récupérer le détail d'une demande d'annulation.
    """

    annulation = execute_query(
        "SELECT * FROM annulation_bc WHERE id = %s",
        (id,),
        fetch_one=True
    )

    if not annulation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demande d'annulation non trouvée"
        )

    return AnnulationBC(
        id=annulation["id"],
        numero_commande=annulation["numero_commande"],
        motif_annulation=annulation["motif_annulation"],
        demande_par=annulation["demande_par"],
        statut=annulation["statut"],
        numero_abc=annulation.get("numero_abc"),
        code_tier=annulation.get("code_tier"),
        email_fournisseur=annulation.get("email_fournisseur"),
        created_at=annulation["created_at"]
    )
