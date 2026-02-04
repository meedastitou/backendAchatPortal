"""
API Routers
"""

from app.routers.auth import router as auth_router
from app.routers.dashboard import router as dashboard_router
from app.routers.fournisseurs import router as fournisseurs_router
from app.routers.rfq import router as rfq_router
from app.routers.reponses import router as reponses_router
from app.routers.decision import router as decision_router
from app.routers.bon_commande import router as bon_commande_router
from app.routers.selections import router as selections_router
from app.routers.x3 import router as x3_router
