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
from app.routers.admin_cotations import router as admin_cotations_router
from app.routers.auto_bc import router as auto_bc_router
from app.routers.sync_x3 import router as sync_x3_router
from app.routers.das_non_soldees import router as  das_non_soldees_router
from app.routers.n8n_communication import router as n8n_communication_router
from app.routers.analyse import router as analyse_router