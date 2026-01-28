"""Modèle Demande d'Achat"""

from sqlalchemy import Column, Integer, String, Text, Enum, DateTime, Numeric
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class DemandeAchat(Base):
    __tablename__ = "demandes_achat"

    id = Column(Integer, primary_key=True)
    numero_da = Column(String(20), nullable=False, index=True)
    code_article = Column(String(20), nullable=False, index=True)
    designation_article = Column(Text)
    quantite = Column(Numeric(10, 2), nullable=False)
    unite = Column(String(10))
    marque_souhaitee = Column(String(100))
    date_creation_da = Column(DateTime, nullable=False, index=True)
    date_besoin = Column(DateTime)
    statut = Column(
        Enum('nouveau', 'en_cours', 'cotations_recues', 'commande_creee', 'annule'),
        nullable=False,
        default='nouveau'
    )
    priorite = Column(
        Enum('basse', 'normale', 'haute', 'urgente'),
        default='normale'
    )
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    def __repr__(self):
        return f"<DemandeAchat {self.numero_da} - {self.statut}>"
