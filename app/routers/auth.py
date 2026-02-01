"""
════════════════════════════════════════════════════════════
ROUTER - Authentification
════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.auth.jwt import create_token_for_user, get_password_hash, verify_password
from app.auth.dependencies import (
    authenticate_user,
    get_current_user,
    get_admin_user,
    update_last_login,
    get_user_by_username
)
from app.database import execute_query, execute_insert, execute_update
from app.schemas.auth import (
    Token,
    LoginRequest,
    LoginResponse,
    UserCreate,
    UserUpdate,
    UserResponse,
    ChangePasswordRequest
)


router = APIRouter(prefix="/auth", tags=["Authentification"])


# ──────────────────────────────────────────────────────────
# Login
# ──────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Authentification et génération du token JWT

    - **username**: Nom d'utilisateur
    - **password**: Mot de passe
    """
    user = authenticate_user(form_data.username, form_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nom d'utilisateur ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Mettre à jour dernière connexion
    update_last_login(user["id"])

    # Créer le token
    access_token = create_token_for_user(user)

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse(
            id=user["id"],
            username=user["username"],
            email=user["email"],
            nom=user["nom"],
            prenom=user["prenom"],
            role=user["role"],
            actif=user["actif"],
            derniere_connexion=user["derniere_connexion"],
            created_at=user["created_at"]
        )
    )


# ──────────────────────────────────────────────────────────
# Current User
# ──────────────────────────────────────────────────────────

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Obtenir les informations de l'utilisateur connecté"""
    return UserResponse(
        id=current_user["id"],
        username=current_user["username"],
        email=current_user["email"],
        nom=current_user["nom"],
        prenom=current_user["prenom"],
        role=current_user["role"],
        actif=current_user["actif"],
        derniere_connexion=current_user["derniere_connexion"],
        created_at=current_user["created_at"]
    )


# ──────────────────────────────────────────────────────────
# Change Password
# ──────────────────────────────────────────────────────────

@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user)
):
    """Changer son mot de passe"""
    # Vérifier l'ancien mot de passe
    if not verify_password(data.current_password, current_user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mot de passe actuel incorrect"
        )

    # Hasher le nouveau mot de passe
    new_hash = get_password_hash(data.new_password)

    # Mettre à jour
    query = "UPDATE utilisateurs SET password_hash = %s WHERE id = %s"
    execute_update(query, (new_hash, current_user["id"]))

    return {"message": "Mot de passe modifié avec succès"}


# ──────────────────────────────────────────────────────────
# Admin: Create User
# ──────────────────────────────────────────────────────────

@router.post("/users", response_model=UserResponse)
async def create_user(
    user: UserCreate,
    admin: dict = Depends(get_admin_user)
):
    """Créer un nouvel utilisateur (Admin uniquement)"""
    # Vérifier si username existe déjà
    existing = get_user_by_username(user.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce nom d'utilisateur existe déjà"
        )

    # Vérifier si email existe déjà
    email_check = execute_query(
        "SELECT id FROM utilisateurs WHERE email = %s",
        (user.email,),
        fetch_one=True
    )
    if email_check:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cet email est déjà utilisé"
        )

    # Créer l'utilisateur
    password_hash = get_password_hash(user.password)

    query = """
        INSERT INTO utilisateurs (username, email, password_hash, nom, prenom, role, actif)
        VALUES (%s, %s, %s, %s, %s, %s, TRUE)
    """
    user_id = execute_insert(query, (
        user.username,
        user.email,
        password_hash,
        user.nom,
        user.prenom,
        user.role.value
    ))

    # Récupérer l'utilisateur créé
    new_user = execute_query(
        "SELECT * FROM utilisateurs WHERE id = %s",
        (user_id,),
        fetch_one=True
    )

    return UserResponse(
        id=new_user["id"],
        username=new_user["username"],
        email=new_user["email"],
        nom=new_user["nom"],
        prenom=new_user["prenom"],
        role=new_user["role"],
        actif=new_user["actif"],
        derniere_connexion=new_user["derniere_connexion"],
        created_at=new_user["created_at"]
    )


# ──────────────────────────────────────────────────────────
# Admin: List Users
# ──────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(admin: dict = Depends(get_admin_user)):
    """Lister tous les utilisateurs (Admin uniquement)"""
    query = """
        SELECT id, username, email, nom, prenom, role, actif,
               derniere_connexion, created_at
        FROM utilisateurs
        ORDER BY created_at DESC
    """
    users = execute_query(query)

    return {
        "users": [UserResponse(**u) for u in users],
        "total": len(users)
    }


# ──────────────────────────────────────────────────────────
# Admin: Get User by ID
# ──────────────────────────────────────────────────────────

@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    admin: dict = Depends(get_admin_user)
):
    """Obtenir un utilisateur par ID (Admin uniquement)"""
    user = execute_query(
        """
        SELECT id, username, email, nom, prenom, role, actif,
               derniere_connexion, created_at
        FROM utilisateurs WHERE id = %s
        """,
        (user_id,),
        fetch_one=True
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )

    return UserResponse(**user)


# ──────────────────────────────────────────────────────────
# Admin: Update User
# ──────────────────────────────────────────────────────────

@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    admin: dict = Depends(get_admin_user)
):
    """Modifier un utilisateur (Admin uniquement)"""
    # Vérifier que l'utilisateur existe
    existing = execute_query(
        "SELECT * FROM utilisateurs WHERE id = %s",
        (user_id,),
        fetch_one=True
    )

    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )

    # Construire la requête de mise à jour dynamiquement
    update_fields = []
    params = []

    if user_update.email is not None:
        # Vérifier que l'email n'est pas déjà utilisé
        email_check = execute_query(
            "SELECT id FROM utilisateurs WHERE email = %s AND id != %s",
            (user_update.email, user_id),
            fetch_one=True
        )
        if email_check:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cet email est déjà utilisé"
            )
        update_fields.append("email = %s")
        params.append(user_update.email)

    if user_update.nom is not None:
        update_fields.append("nom = %s")
        params.append(user_update.nom)

    if user_update.prenom is not None:
        update_fields.append("prenom = %s")
        params.append(user_update.prenom)

    if user_update.role is not None:
        update_fields.append("role = %s")
        params.append(user_update.role.value)

    if user_update.actif is not None:
        update_fields.append("actif = %s")
        params.append(user_update.actif)

    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucune modification fournie"
        )

    params.append(user_id)
    query = f"UPDATE utilisateurs SET {', '.join(update_fields)} WHERE id = %s"
    execute_update(query, tuple(params))

    # Récupérer l'utilisateur mis à jour
    updated = execute_query(
        """
        SELECT id, username, email, nom, prenom, role, actif,
               derniere_connexion, created_at
        FROM utilisateurs WHERE id = %s
        """,
        (user_id,),
        fetch_one=True
    )

    return UserResponse(**updated)


# ──────────────────────────────────────────────────────────
# Admin: Toggle User Active Status
# ──────────────────────────────────────────────────────────

@router.patch("/users/{user_id}/toggle-active")
async def toggle_user_active(
    user_id: int,
    admin: dict = Depends(get_admin_user)
):
    """Activer/Désactiver un utilisateur (Admin uniquement)"""
    # Empêcher l'admin de se désactiver lui-même
    if user_id == admin["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous ne pouvez pas vous désactiver vous-même"
        )

    user = execute_query(
        "SELECT id, actif FROM utilisateurs WHERE id = %s",
        (user_id,),
        fetch_one=True
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )

    new_status = not user["actif"]
    execute_update(
        "UPDATE utilisateurs SET actif = %s WHERE id = %s",
        (new_status, user_id)
    )

    return {
        "message": f"Utilisateur {'activé' if new_status else 'désactivé'}",
        "actif": new_status
    }


# ──────────────────────────────────────────────────────────
# Admin: Reset User Password
# ──────────────────────────────────────────────────────────

@router.patch("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    admin: dict = Depends(get_admin_user)
):
    """Réinitialiser le mot de passe d'un utilisateur (Admin uniquement)"""
    user = execute_query(
        "SELECT id, username FROM utilisateurs WHERE id = %s",
        (user_id,),
        fetch_one=True
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )

    # Générer un mot de passe temporaire (username + "123")
    temp_password = f"{user['username']}123"
    password_hash = get_password_hash(temp_password)

    execute_update(
        "UPDATE utilisateurs SET password_hash = %s WHERE id = %s",
        (password_hash, user_id)
    )

    return {
        "message": "Mot de passe réinitialisé",
        "temp_password": temp_password
    }


# ──────────────────────────────────────────────────────────
# Admin: Delete User
# ──────────────────────────────────────────────────────────

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: dict = Depends(get_admin_user)
):
    """Supprimer un utilisateur (Admin uniquement)"""
    # Empêcher l'admin de se supprimer lui-même
    if user_id == admin["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous ne pouvez pas vous supprimer vous-même"
        )

    user = execute_query(
        "SELECT id FROM utilisateurs WHERE id = %s",
        (user_id,),
        fetch_one=True
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )

    # Désactiver plutôt que supprimer (soft delete)
    execute_update(
        "UPDATE utilisateurs SET actif = FALSE WHERE id = %s",
        (user_id,)
    )

    return {"message": "Utilisateur supprimé (désactivé)"}
