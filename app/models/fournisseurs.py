"""Modèle Fournisseur"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Enum, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Fournisseur(Base):
    __tablename__ = "fournisseurs"

    id = Column(Integer, primary_key=True)
    code_fournisseur = Column(String(20), unique=True, nullable=False, index=True)
    nom_fournisseur = Column(String(255), nullable=False)
    email = Column(String(255), index=True)
    telephone = Column(String(20))
    fax = Column(String(20))
    adresse = Column(Text)
    pays = Column(String(50), default='Maroc')
    ville = Column(String(100))
    blacklist = Column(Boolean, default=False, index=True)
    motif_blacklist = Column(Text)
    date_blacklist = Column(DateTime)
    statut = Column(
        Enum('actif', 'inactif', 'suspendu'),
        nullable=False,
        default='actif',
        index=True
    )
    note_performance = Column(Float, default=0.00)
    nb_total_rfq = Column(Integer, default=0)
    nb_reponses = Column(Integer, default=0)
    taux_reponse = Column(Float, default=0.00)
    delai_moyen_reponse_heures = Column(Integer, default=0)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    def __repr__(self):
        return f"<Fournisseur {self.nom_fournisseur} - {self.statut}>"
