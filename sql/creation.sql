-- ════════════════════════════════════════════════════════════
-- PROJET : FLUX ACHAT AI AGENT - PORTAIL AUTOMATISATION ACHATS
-- BASE DE DONNÉES : flux_achat_portal
-- VERSION : 1.0
-- DATE : 13 Janvier 2026
-- ════════════════════════════════════════════════════════════

-- ┌─────────────────────────────────────────────────────────┐
-- │ ÉTAPE 1 : CRÉATION DE LA BASE DE DONNÉES                │
-- └─────────────────────────────────────────────────────────┘

DROP DATABASE IF EXISTS flux_achat_portal;
CREATE DATABASE flux_achat_portal 
    CHARACTER SET utf8mb4 
    COLLATE utf8mb4_unicode_ci;

USE flux_achat_portal;

-- ════════════════════════════════════════════════════════════
-- MODULE 1 : GESTION DES DEMANDES D'ACHAT (DA)
-- ════════════════════════════════════════════════════════════

CREATE TABLE demandes_achat (
    id INT PRIMARY KEY AUTO_INCREMENT,
    numero_da VARCHAR(20) NOT NULL,
    code_article VARCHAR(20) NOT NULL,
    designation_article TEXT,
    quantite DECIMAL(10,2) NOT NULL,
    unite VARCHAR(10),
    marque_souhaitee VARCHAR(100),
    date_creation_da DATETIME NOT NULL,
    date_besoin DATETIME,
    statut ENUM('nouveau', 'en_cours', 'cotations_recues', 'commande_creee', 'annule') DEFAULT 'nouveau',
    priorite ENUM('basse', 'normale', 'haute', 'urgente') DEFAULT 'normale',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_numero_da (numero_da),
    INDEX idx_article (code_article),
    INDEX idx_statut (statut),
    INDEX idx_date_creation (date_creation_da)
) ENGINE=InnoDB COMMENT='Historique des demandes d''achat provenant de Sage X3';

-- ════════════════════════════════════════════════════════════
-- MODULE 2 : GESTION FOURNISSEURS
-- ════════════════════════════════════════════════════════════

CREATE TABLE fournisseurs (
    id INT PRIMARY KEY AUTO_INCREMENT,
    code_fournisseur VARCHAR(20) UNIQUE NOT NULL,
    nom_fournisseur VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    telephone VARCHAR(20),
    fax VARCHAR(20),
    adresse TEXT,
    pays VARCHAR(50) DEFAULT 'Maroc',
    ville VARCHAR(100),
    blacklist BOOLEAN DEFAULT FALSE,
    motif_blacklist TEXT,
    date_blacklist DATETIME,
    statut ENUM('actif', 'inactif', 'suspendu') DEFAULT 'actif',
    note_performance DECIMAL(3,2) DEFAULT 0.00 COMMENT 'Note sur 5.00',
    nb_total_rfq INT DEFAULT 0 COMMENT 'Nombre total de RFQ envoyées',
    nb_reponses INT DEFAULT 0 COMMENT 'Nombre de réponses reçues',
    taux_reponse DECIMAL(5,2) DEFAULT 0.00 COMMENT 'Pourcentage de réponse',
    delai_moyen_reponse_heures INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_code (code_fournisseur),
    INDEX idx_blacklist (blacklist),
    INDEX idx_statut (statut),
    INDEX idx_email (email)
) ENGINE=InnoDB COMMENT='Référentiel des fournisseurs';

-- ════════════════════════════════════════════════════════════
-- MODULE 3 : DEMANDES DE COTATION (RFQ - Request For Quote)
-- ════════════════════════════════════════════════════════════

CREATE TABLE demandes_cotation (
    id INT PRIMARY KEY AUTO_INCREMENT,
    uuid VARCHAR(36) UNIQUE NOT NULL COMMENT 'Identifiant unique pour lien formulaire',
    numero_rfq VARCHAR(30) UNIQUE NOT NULL COMMENT 'Format: RFQ-YYYY-NNNN',
    code_fournisseur VARCHAR(20) NOT NULL,
    date_envoi DATETIME NOT NULL,
    date_limite_reponse DATETIME COMMENT 'Optionnel: deadline pour répondre',
    statut ENUM('envoye', 'vu', 'repondu', 'rejete', 'expire', 'relance_1', 'relance_2', 'relance_3') DEFAULT 'envoye',
    nb_relances INT DEFAULT 0,
    date_derniere_relance DATETIME,
    date_ouverture_email DATETIME COMMENT 'Tracking pixel',
    date_clic_formulaire DATETIME,
    date_reponse DATETIME,
    ip_ouverture VARCHAR(45),
    ip_reponse VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (code_fournisseur) REFERENCES fournisseurs(code_fournisseur) ON UPDATE CASCADE,
    INDEX idx_uuid (uuid),
    INDEX idx_numero_rfq (numero_rfq),
    INDEX idx_statut (statut),
    INDEX idx_fournisseur (code_fournisseur),
    INDEX idx_date_envoi (date_envoi)
) ENGINE=InnoDB COMMENT='Demandes de cotation envoyées aux fournisseurs';

-- ════════════════════════════════════════════════════════════
-- MODULE 4 : LIGNES DE COTATION (Articles demandés par RFQ)
-- ════════════════════════════════════════════════════════════

CREATE TABLE lignes_cotation (
    id INT PRIMARY KEY AUTO_INCREMENT,
    rfq_uuid VARCHAR(36) NOT NULL,
    numero_da VARCHAR(20) NOT NULL,
    code_article VARCHAR(20) NOT NULL,
    designation_article TEXT,
    quantite_demandee DECIMAL(10,2) NOT NULL,
    unite VARCHAR(10),
    marque_souhaitee VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (rfq_uuid) REFERENCES demandes_cotation(uuid) ON DELETE CASCADE,
    INDEX idx_rfq (rfq_uuid),
    INDEX idx_da (numero_da),
    INDEX idx_article (code_article)
) ENGINE=InnoDB COMMENT='Articles demandés dans chaque RFQ';

-- ════════════════════════════════════════════════════════════
-- MODULE 5 : RÉPONSES FOURNISSEURS
-- ════════════════════════════════════════════════════════════

-- 1. Suppression de l'ancienne table unique
DROP TABLE IF EXISTS reponses_fournisseurs;

-- 2. Création de la table Entête (Header)
-- Cette table contient les informations globales de la réponse du fournisseur
CREATE TABLE reponses_fournisseurs_entete (
    id INT PRIMARY KEY AUTO_INCREMENT,
    rfq_uuid VARCHAR(36) NOT NULL,
    reference_fournisseur VARCHAR(50) COMMENT 'Référence interne fournisseur',
    
    -- "Devise va être une insertion de fichier" -> On stocke l'URL/Chemin du fichier
    fichier_devis_url VARCHAR(500) COMMENT 'URL du fichier de devis global (ex: PDF scan)',
    devise VARCHAR(3) DEFAULT 'MAD',
    methodes_paiement VARCHAR(255) COMMENT 'Méthodes de paiement acceptées',
    
    date_reponse DATETIME NOT NULL,
    commentaire TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Clés étrangères et Index
    FOREIGN KEY (rfq_uuid) REFERENCES demandes_cotation(uuid) ON DELETE CASCADE,
    INDEX idx_rfq_entete (rfq_uuid)
) ENGINE=InnoDB COMMENT='Entête des réponses fournisseurs (Global)';

-- 3. Création de la table Détail (Lignes)
-- Cette table contient les prix et détails pour chaque article
CREATE TABLE reponses_fournisseurs_detail (
    id INT PRIMARY KEY AUTO_INCREMENT,
    
    -- Lien vers l'entête (Obligatoire pour lier le détail à la réponse globale)
    reponse_entete_id INT NOT NULL,
    
    -- Liens vers la demande originale (redondant mais demandé pour performance/intégrité)
    rfq_uuid VARCHAR(36) NOT NULL,
    ligne_cotation_id INT NOT NULL,
    
    code_article VARCHAR(20) NOT NULL,
    
    -- Informations de prix et logistique
    prix_unitaire_ht DECIMAL(10,4) COMMENT 'Prix Hors Taxe par unité',
    date_livraison DATETIME COMMENT 'Date prévue de livraison',
    quantite_disponible DECIMAL(10,2) COMMENT 'Si disponibilité partielle',
    
    -- Conformité technique
    marque_conforme BOOLEAN COMMENT 'TRUE si marque demandée disponible',
    marque_proposee VARCHAR(100),
    fichier_joint_url VARCHAR(500) COMMENT 'URL document technique/fiche article spécifique',
    commentaire_article TEXT,
    
    -- Clés étrangères
    FOREIGN KEY (reponse_entete_id) REFERENCES reponses_fournisseurs_entete(id) ON DELETE CASCADE,
    FOREIGN KEY (rfq_uuid) REFERENCES demandes_cotation(uuid) ON DELETE CASCADE,
    FOREIGN KEY (ligne_cotation_id) REFERENCES lignes_cotation(id) ON DELETE CASCADE,
    
    -- Index pour la performance
    INDEX idx_entete (reponse_entete_id),
    INDEX idx_article (code_article),
    INDEX idx_ligne (ligne_cotation_id)
) ENGINE=InnoDB COMMENT='Détail des lignes de la réponse fournisseur';

-- ════════════════════════════════════════════════════════════
-- MODULE 6 : REJETS FOURNISSEURS
-- ════════════════════════════════════════════════════════════

CREATE TABLE rejets_fournisseurs (
    id INT PRIMARY KEY AUTO_INCREMENT,
    rfq_uuid VARCHAR(36) NOT NULL,
    motif_rejet TEXT,
    type_rejet ENUM('email', 'formulaire') DEFAULT 'formulaire',
    date_rejet DATETIME NOT NULL,
    ip_rejet VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (rfq_uuid) REFERENCES demandes_cotation(uuid) ON DELETE CASCADE,
    INDEX idx_rfq (rfq_uuid),
    INDEX idx_date (date_rejet)
) ENGINE=InnoDB COMMENT='Rejets explicites des fournisseurs';

-- ════════════════════════════════════════════════════════════
-- MODULE 7 : COMPARAISON ET ANALYSE
-- ════════════════════════════════════════════════════════════

CREATE TABLE comparaisons (
    id INT PRIMARY KEY AUTO_INCREMENT,
    numero_da VARCHAR(20) NOT NULL,
    code_article VARCHAR(20) NOT NULL,
    nb_rfq_envoyees INT DEFAULT 0,
    nb_reponses_recues INT DEFAULT 0,
    nb_rejets INT DEFAULT 0,
    
    -- Meilleur prix
    meilleur_prix_ht DECIMAL(10,4),
    fournisseur_meilleur_prix VARCHAR(20),
    
    -- Meilleur délai
    meilleur_delai_jours INT,
    fournisseur_meilleur_delai VARCHAR(20),
    
    -- Recommandation (basé sur score global)
    fournisseur_recommande VARCHAR(20),
    score_fournisseur_recommande DECIMAL(3,2),
    justification_recommandation TEXT,
    
    -- Prix moyen du marché
    prix_moyen_ht DECIMAL(10,4),
    prix_min_ht DECIMAL(10,4),
    prix_max_ht DECIMAL(10,4),
    
    -- Dates analyse
    date_analyse DATETIME,
    statut_decision ENUM('en_attente', 'valide', 'refuse') DEFAULT 'en_attente',
    validee_par VARCHAR(100) COMMENT 'Username utilisateur',
    date_validation DATETIME,
    commentaire_decision TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_da (numero_da),
    INDEX idx_article (code_article),
    INDEX idx_statut (statut_decision)
) ENGINE=InnoDB COMMENT='Analyses comparatives des offres reçues';

-- ════════════════════════════════════════════════════════════
-- MODULE 8 : COMMANDES GÉNÉRÉES
-- ════════════════════════════════════════════════════════════

CREATE TABLE commandes (
    id INT PRIMARY KEY AUTO_INCREMENT,
    numero_commande VARCHAR(30) UNIQUE NOT NULL COMMENT 'Format: CMD-YYYY-NNNN',
    numero_da VARCHAR(20) NOT NULL,
    code_fournisseur VARCHAR(20) NOT NULL,
    nom_fournisseur VARCHAR(255),
    email_fournisseur VARCHAR(255),
    
    -- Montants
    montant_total_ht DECIMAL(10,2) NOT NULL,
    tva_pourcent DECIMAL(5,2) DEFAULT 20.00,
    montant_tva DECIMAL(10,2),
    montant_total_ttc DECIMAL(10,2) NOT NULL,
    devise VARCHAR(3) DEFAULT 'MAD',
    
    -- Délais
    delai_livraison_jours INT,
    date_commande DATETIME NOT NULL,
    date_livraison_prevue DATETIME,
    date_livraison_reelle DATETIME,
    
    -- Workflow
    statut ENUM('brouillon', 'validee', 'envoyee', 'confirmee', 'livree', 'annulee') DEFAULT 'brouillon',
    validee_par VARCHAR(100) COMMENT 'Username utilisateur',
    date_validation DATETIME,
    envoyee_par VARCHAR(100),
    date_envoi DATETIME,
    
    -- Traçabilité
    commentaire_interne TEXT,
    fichier_commande_url VARCHAR(500) COMMENT 'URL PDF généré',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (code_fournisseur) REFERENCES fournisseurs(code_fournisseur) ON UPDATE CASCADE,
    INDEX idx_numero (numero_commande),
    INDEX idx_da (numero_da),
    INDEX idx_fournisseur (code_fournisseur),
    INDEX idx_statut (statut),
    INDEX idx_date_commande (date_commande)
) ENGINE=InnoDB COMMENT='Commandes générées suite aux comparaisons';

CREATE TABLE lignes_commande (
    id INT PRIMARY KEY AUTO_INCREMENT,
    numero_commande VARCHAR(30) NOT NULL,
    ligne_numero INT NOT NULL COMMENT 'Numéro de ligne dans la commande',
    code_article VARCHAR(20) NOT NULL,
    designation TEXT,
    quantite DECIMAL(10,2) NOT NULL,
    unite VARCHAR(10),
    prix_unitaire_ht DECIMAL(10,4) NOT NULL,
    montant_ligne_ht DECIMAL(10,2) NOT NULL,
    tva_pourcent DECIMAL(5,2) DEFAULT 20.00,
    montant_tva_ligne DECIMAL(10,2),
    montant_ligne_ttc DECIMAL(10,2) NOT NULL,
    marque VARCHAR(100),
    reference_fournisseur VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (numero_commande) REFERENCES commandes(numero_commande) ON DELETE CASCADE,
    INDEX idx_commande (numero_commande),
    INDEX idx_article (code_article)
) ENGINE=InnoDB COMMENT='Lignes de détail des commandes';

-- ════════════════════════════════════════════════════════════
-- MODULE 9 : LOGS ET TRAÇABILITÉ
-- ════════════════════════════════════════════════════════════

CREATE TABLE logs_emails (
    id INT PRIMARY KEY AUTO_INCREMENT,
    rfq_uuid VARCHAR(36),
    email_destinataire VARCHAR(255) NOT NULL,
    nom_destinataire VARCHAR(255),
    type_email ENUM('cotation', 'relance', 'confirmation', 'notification', 'alerte') DEFAULT 'cotation',
    type_log ENUM('envoi', 'ouverture', 'clic', 'bounce', 'erreur', 'spam') DEFAULT 'envoi',
    sujet_email VARCHAR(500),
    message TEXT COMMENT 'Message erreur si applicable',
    ip_address VARCHAR(45),
    user_agent TEXT,
    date_log DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_rfq (rfq_uuid),
    INDEX idx_type_email (type_email),
    INDEX idx_type_log (type_log),
    INDEX idx_date (date_log)
) ENGINE=InnoDB COMMENT='Logs des emails envoyés et interactions';

CREATE TABLE logs_systeme (
    id INT PRIMARY KEY AUTO_INCREMENT,
    niveau ENUM('info', 'warning', 'error', 'critical') DEFAULT 'info',
    module VARCHAR(50) COMMENT 'Ex: n8n_workflow, formulaire_php, api_fastapi, angular_app',
    action VARCHAR(100) COMMENT 'Ex: envoi_rfq, calcul_score, generation_commande',
    message TEXT NOT NULL,
    donnees_json JSON COMMENT 'Données contextuelles en JSON',
    user_id INT COMMENT 'ID utilisateur si action manuelle',
    ip_address VARCHAR(45),
    date_log DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_niveau (niveau),
    INDEX idx_module (module),
    INDEX idx_action (action),
    INDEX idx_date (date_log)
) ENGINE=InnoDB COMMENT='Logs système pour debug et audit';

-- ════════════════════════════════════════════════════════════
-- MODULE 10 : UTILISATEURS ET AUTHENTIFICATION
-- ════════════════════════════════════════════════════════════

CREATE TABLE utilisateurs (
    id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL COMMENT 'Hash bcrypt ou argon2',
    nom VARCHAR(100),
    prenom VARCHAR(100),
    role ENUM('acheteur', 'responsable_achat', 'admin') DEFAULT 'acheteur',
    actif BOOLEAN DEFAULT TRUE,
    force_change_password BOOLEAN DEFAULT FALSE,
    derniere_connexion DATETIME,
    tentatives_connexion_echouees INT DEFAULT 0,
    compte_verrouille BOOLEAN DEFAULT FALSE,
    date_verrouillage DATETIME,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_username (username),
    INDEX idx_email (email),
    INDEX idx_role (role),
    INDEX idx_actif (actif)
) ENGINE=InnoDB COMMENT='Utilisateurs du portail achat';

CREATE TABLE sessions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    token VARCHAR(255) UNIQUE NOT NULL COMMENT 'JWT token',
    ip_address VARCHAR(45),
    user_agent TEXT,
    date_creation DATETIME NOT NULL,
    date_expiration DATETIME NOT NULL,
    date_derniere_activite DATETIME,
    actif BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES utilisateurs(id) ON DELETE CASCADE,
    INDEX idx_token (token),
    INDEX idx_user (user_id),
    INDEX idx_expiration (date_expiration),
    INDEX idx_actif (actif)
) ENGINE=InnoDB COMMENT='Sessions utilisateurs actives';

-- ════════════════════════════════════════════════════════════
-- MODULE 11 : HISTORIQUE PRIX (Analyse tendances)
-- ════════════════════════════════════════════════════════════

CREATE TABLE historique_prix (
    id INT PRIMARY KEY AUTO_INCREMENT,
    code_article VARCHAR(20) NOT NULL,
    designation_article TEXT,
    code_fournisseur VARCHAR(20) NOT NULL,
    nom_fournisseur VARCHAR(255),
    prix_unitaire_ht DECIMAL(10,4) NOT NULL,
    quantite DECIMAL(10,2),
    unite VARCHAR(10),
    devise VARCHAR(3) DEFAULT 'MAD',
    date_prix DATETIME NOT NULL,
    source ENUM('cotation', 'commande', 'manuel', 'import') DEFAULT 'cotation',
    numero_reference VARCHAR(50) COMMENT 'N° RFQ ou N° Commande',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_article (code_article),
    INDEX idx_fournisseur (code_fournisseur),
    INDEX idx_date (date_prix),
    INDEX idx_source (source)
) ENGINE=InnoDB COMMENT='Historique des prix pour analyse tendances';

-- ════════════════════════════════════════════════════════════
-- MODULE 12 : PARAMÈTRES SYSTÈME
-- ════════════════════════════════════════════════════════════

CREATE TABLE parametres_systeme (
    id INT PRIMARY KEY AUTO_INCREMENT,
    cle VARCHAR(100) UNIQUE NOT NULL,
    valeur TEXT,
    type_donnee ENUM('string', 'int', 'float', 'boolean', 'json') DEFAULT 'string',
    categorie VARCHAR(50) COMMENT 'Ex: email, relance, scoring, general',
    description TEXT,
    modifiable BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(100) COMMENT 'Username',
    
    INDEX idx_cle (cle),
    INDEX idx_categorie (categorie)
) ENGINE=InnoDB COMMENT='Paramètres configurables du système';

-- ════════════════════════════════════════════════════════════
-- MODULE 13 : NOTIFICATIONS
-- ════════════════════════════════════════════════════════════

CREATE TABLE notifications (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT,
    titre VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    type_notification ENUM('info', 'succes', 'avertissement', 'erreur') DEFAULT 'info',
    priorite ENUM('basse', 'normale', 'haute') DEFAULT 'normale',
    lue BOOLEAN DEFAULT FALSE,
    date_lecture DATETIME,
    lien_action VARCHAR(500) COMMENT 'URL vers page concernée',
    donnees_json JSON COMMENT 'Données contextuelles',
    date_notification DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES utilisateurs(id) ON DELETE CASCADE,
    INDEX idx_user (user_id),
    INDEX idx_lue (lue),
    INDEX idx_date (date_notification)
) ENGINE=InnoDB COMMENT='Notifications utilisateurs dans le dashboard';

-- ════════════════════════════════════════════════════════════
-- INSERTION DES DONNÉES PAR DÉFAUT
-- ════════════════════════════════════════════════════════════

-- ┌─────────────────────────────────────────────────────────┐
-- │ PARAMÈTRES SYSTÈME                                       │
-- └─────────────────────────────────────────────────────────┘

INSERT INTO parametres_systeme (cle, valeur, type_donnee, categorie, description, modifiable) VALUES
-- Paramètres relance
('delai_relance_jours', '2', 'int', 'relance', 'Délai en jours avant première relance', TRUE),
('nb_max_relances', '3', 'int', 'relance', 'Nombre maximum de relances autorisées', TRUE),
('delai_inactif_jours', '15', 'int', 'relance', 'Délai pour marquer un fournisseur comme inactif', TRUE),
('delai_entre_relances_jours', '2', 'int', 'relance', 'Délai entre chaque relance', TRUE),

-- Paramètres email
('email_responsable_achat', 'achat@votresociete.com', 'string', 'email', 'Email du responsable achat pour notifications', TRUE),
('email_expediteur', 'noreply@votresociete.com', 'string', 'email', 'Email expéditeur des RFQ', TRUE),
('email_expediteur_nom', 'Service Achats', 'string', 'email', 'Nom affiché expéditeur', TRUE),
('smtp_host', 'smtp.votredomaine.com', 'string', 'email', 'Serveur SMTP', TRUE),
('smtp_port', '587', 'int', 'email', 'Port SMTP', TRUE),
('smtp_secure', 'tls', 'string', 'email', 'Sécurité SMTP (tls/ssl)', TRUE),

-- Paramètres scoring
('poids_score_prix', '0.40', 'float', 'scoring', 'Poids du score prix (0-1)', TRUE),
('poids_score_delai', '0.35', 'float', 'scoring', 'Poids du score délai (0-1)', TRUE),
('poids_score_conformite', '0.25', 'float', 'scoring', 'Poids du score conformité (0-1)', TRUE),

-- Paramètres généraux
('tva_defaut_pourcent', '20.00', 'float', 'general', 'TVA par défaut au Maroc', TRUE),
('devise_defaut', 'MAD', 'string', 'general', 'Devise par défaut', TRUE),
('delai_expiration_rfq_jours', '30', 'int', 'general', 'Délai après lequel une RFQ expire', TRUE),
('url_formulaire_base', 'https://votre-domaine.com', 'string', 'general', 'URL de base pour formulaires PHP', TRUE),

-- Paramètres sécurité
('session_duree_heures', '8', 'int', 'securite', 'Durée validité session en heures', TRUE),
('max_tentatives_connexion', '5', 'int', 'securite', 'Nombre max tentatives connexion avant verrouillage', TRUE),
('duree_verrouillage_minutes', '30', 'int', 'securite', 'Durée verrouillage compte en minutes', TRUE);

-- ┌─────────────────────────────────────────────────────────┐
-- │ UTILISATEUR ADMIN PAR DÉFAUT                            │
-- └─────────────────────────────────────────────────────────┘
-- Mot de passe : Admin@2026 (hash bcrypt)
-- ⚠️ À CHANGER EN PRODUCTION !

INSERT INTO utilisateurs (username, email, password_hash, nom, prenom, role, actif) VALUES
('admin', 'admin@votresociete.com', '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi', 'Administrateur', 'Système', 'admin', TRUE);

-- ════════════════════════════════════════════════════════════
-- VUES UTILES POUR REPORTING
-- ════════════════════════════════════════════════════════════

-- ┌─────────────────────────────────────────────────────────┐
-- │ VUE : Statistiques globales dashboard                   │
-- └─────────────────────────────────────────────────────────┘

CREATE VIEW vue_stats_dashboard AS
SELECT 
    (SELECT COUNT(*) FROM demandes_achat WHERE statut != 'annule') AS total_da_actives,
    (SELECT COUNT(*) FROM demandes_cotation WHERE statut IN ('envoye', 'relance_1', 'relance_2', 'relance_3')) AS rfq_en_attente,
    (SELECT COUNT(*) FROM demandes_cotation WHERE statut = 'repondu') AS rfq_repondues,
    (SELECT COUNT(*) FROM demandes_cotation WHERE statut = 'rejete') AS rfq_rejetees,
    (SELECT COUNT(*) FROM fournisseurs WHERE statut = 'actif' AND blacklist = FALSE) AS fournisseurs_actifs,
    (SELECT COUNT(*) FROM fournisseurs WHERE blacklist = TRUE) AS fournisseurs_blacklistes,
    (SELECT COUNT(*) FROM commandes WHERE statut IN ('validee', 'envoyee')) AS commandes_en_cours,
    (SELECT ROUND(AVG(taux_reponse), 2) FROM fournisseurs WHERE nb_total_rfq > 0) AS taux_reponse_moyen;

-- ┌─────────────────────────────────────────────────────────┐
-- │ VUE : Performance fournisseurs                          │
-- └─────────────────────────────────────────────────────────┘

CREATE VIEW vue_performance_fournisseurs AS
SELECT 
    f.code_fournisseur,
    f.nom_fournisseur,
    f.email,
    f.statut,
    f.blacklist,
    f.nb_total_rfq,
    f.nb_reponses,
    f.taux_reponse,
    f.note_performance,
    COUNT(DISTINCT rf.id) AS nb_reponses_details,
    AVG(rf.score_global) AS score_moyen_global,
    AVG(rf.prix_unitaire_ht) AS prix_moyen_offres,
    AVG(rf.delai_livraison_jours) AS delai_moyen_propose
FROM fournisseurs f
LEFT JOIN demandes_cotation dc ON f.code_fournisseur = dc.code_fournisseur
LEFT JOIN reponses_fournisseurs rf ON dc.uuid = rf.rfq_uuid
GROUP BY f.id, f.code_fournisseur, f.nom_fournisseur, f.email, f.statut, 
         f.blacklist, f.nb_total_rfq, f.nb_reponses, f.taux_reponse, f.note_performance;

-- ┌─────────────────────────────────────────────────────────┐
-- │ VUE : RFQ avec détails complets                         │
-- └─────────────────────────────────────────────────────────┘

CREATE VIEW vue_rfq_details AS
SELECT 
    dc.id,
    dc.uuid,
    dc.numero_rfq,
    dc.code_fournisseur,
    f.nom_fournisseur,
    f.email,
    dc.statut,
    dc.date_envoi,
    dc.date_reponse,
    dc.nb_relances,
    DATEDIFF(NOW(), dc.date_envoi) AS jours_depuis_envoi,
    CASE 
        WHEN dc.date_reponse IS NOT NULL THEN TIMESTAMPDIFF(HOUR, dc.date_envoi, dc.date_reponse)
        ELSE NULL 
    END AS delai_reponse_heures,
    COUNT(DISTINCT lc.id) AS nb_articles_demandes,
    COUNT(DISTINCT rf.id) AS nb_articles_repondus,
    GROUP_CONCAT(DISTINCT lc.code_article ORDER BY lc.code_article SEPARATOR ', ') AS articles
FROM demandes_cotation dc
JOIN fournisseurs f ON dc.code_fournisseur = f.code_fournisseur
LEFT JOIN lignes_cotation lc ON dc.uuid = lc.rfq_uuid
LEFT JOIN reponses_fournisseurs rf ON dc.uuid = rf.rfq_uuid
GROUP BY dc.id, dc.uuid, dc.numero_rfq, dc.code_fournisseur, f.nom_fournisseur,
f.email, dc.statut, dc.date_envoi, dc.date_reponse, dc.nb_relances;