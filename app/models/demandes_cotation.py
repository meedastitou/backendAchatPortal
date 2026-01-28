"""Modèle Demande de Cotation (RFQ)"""

from sqlalchemy import Column, Integer, String, Enum, DateTime
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class DemandeCotation(Base):
    __tablename__ = "demandes_cotation"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True, nullable=False, index=True)
    numero_rfq = Column(String(30), unique=True, nullable=False, index=True)
    code_fournisseur = Column(String(20), nullable=False, index=True)
    date_envoi = Column(DateTime, nullable=False, index=True)
    date_limite_reponse = Column(DateTime)
    statut = Column(
        Enum('envoye', 'vu', 'repondu', 'rejete', 'expire', 'relance_1', 'relance_2', 'relance_3'),
        nullable=False,
        default='envoye'
    )
    nb_relances = Column(Integer, default=0)
    date_derniere_relance = Column(DateTime)
    date_ouverture_email = Column(DateTime)
    date_clic_formulaire = Column(DateTime)
    date_reponse = Column(DateTime)
    ip_ouverture = Column(String(45))
    ip_reponse = Column(String(45))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    def __repr__(self):
        return f"<DemandeCotation {self.numero_rfq} - {self.statut}>"
