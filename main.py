"""
════════════════════════════════════════════════════════════
FLUX ACHAT PORTAL - API Backend
════════════════════════════════════════════════════════════

Démarrage:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

Documentation:
    - Swagger UI: http://localhost:8000/docs
    - ReDoc: http://localhost:8000/redoc
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import get_db
from app.config import settings
from app.routers import (
    auth_router,
    dashboard_router,
    fournisseurs_router,
    rfq_router,
    reponses_router,
    decision_router,
    bon_commande_router,
    selections_router
)


# ──────────────────────────────────────────────────────────
# Application FastAPI
# ──────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## API REST pour le Portail Achat Intelligent

Cette API permet de gérer:
- **Authentification** - Login JWT, gestion utilisateurs
- **Dashboard** - Statistiques et KPIs
- **Fournisseurs** - CRUD, blacklist, performance
- **RFQ** - Demandes de cotation
- **Réponses** - Offres fournisseurs, comparaisons
    """,
    docs_url="/docs",
    redoc_url="/redoc"
)


# ──────────────────────────────────────────────────────────
# CORS Middleware
# ──────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    # allow_origin=settings.CORS_ALLOW_ORIGINS,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────
# Routers
# ──────────────────────────────────────────────────────────

app.include_router(auth_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(fournisseurs_router, prefix="/api")
app.include_router(rfq_router, prefix="/api")
app.include_router(reponses_router, prefix="/api")
app.include_router(decision_router, prefix="/api")
app.include_router(bon_commande_router, prefix="/api")
app.include_router(selections_router, prefix="/api")


# ──────────────────────────────────────────────────────────
# Routes de base
# ──────────────────────────────────────────────────────────

@app.get("/", tags=["Root"])
async def root():
    """Page d'accueil de l'API"""
    return {
        "message": "Bienvenue sur l'API Flux Achat Portal",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Vérification de l'état de l'API"""
    from app.database import get_db_connection

    # Test connexion DB
    db_status = "ok"
    try:
        conn = get_db_connection()
        conn.close()
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "healthy" if db_status == "ok" else "unhealthy",
        "database": db_status,
        "version": settings.APP_VERSION
    }


# ──────────────────────────────────────────────────────────
# Démarrage
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
