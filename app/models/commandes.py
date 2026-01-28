"""Modèle Commande"""

from sqlalchemy import Column, Integer, String, Float, DateTime, Enum, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Commande(Base):
    __tablename__ = "commandes"

    id = Column(Integer, primary_key=True)
    numero_commande = Column(String(30), unique=True, nullable=False, index=True)
    numero_da = Column(String(20), nullable=False, index=True)
    code_fournisseur = Column(String(20), nullable=False, index=True)
    nom_fournisseur = Column(String(255))
    email_fournisseur = Column(String(255))
    montant_total_ht = Column(Float, nullable=False, default=0)
    tva_pourcent = Column(Float, default=20.00)
    montant_tva = Column(Float)
    montant_total_ttc = Column(Float, nullable=False)
    devise = Column(String(3), default='MAD')
    delai_livraison_jours = Column(Integer)
    date_commande = Column(DateTime, nullable=False)
    date_livraison_prevue = Column(DateTime)
    date_livraison_reelle = Column(DateTime)
    statut = Column(
        Enum('brouillon', 'validee', 'envoyee', 'confirmee', 'livree', 'annulee'),
        nullable=False,
        default='brouillon',
        index=True
    )
    validee_par = Column(String(100))
    date_validation = Column(DateTime)
    envoyee_par = Column(String(100))
    date_envoi = Column(DateTime)
    commentaire_interne = Column(Text)
    fichier_commande_url = Column(String(500))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    def __repr__(self):
        return f"<Commande {self.numero_commande} - {self.statut}>"
