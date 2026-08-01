-- ════════════════════════════════════════════════════════════
-- Tables pour Bon de Commande (Multi-DA par Fournisseur)
-- ════════════════════════════════════════════════════════════

-- Table des bons de commande
CREATE TABLE IF NOT EXISTS bons_commande (
    id INT AUTO_INCREMENT PRIMARY KEY,
    numero_bc VARCHAR(50) NOT NULL UNIQUE,
    code_fournisseur VARCHAR(50) NOT NULL,

    -- Dates
    date_creation DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_validation DATETIME NULL,
    validee_par VARCHAR(100) NULL,

    -- Montants
    montant_total_ht DECIMAL(15, 2) NOT NULL DEFAULT 0,
    montant_tva DECIMAL(15, 2) NOT NULL DEFAULT 0,
    montant_total_ttc DECIMAL(15, 2) NOT NULL DEFAULT 0,
    devise VARCHAR(10) NOT NULL DEFAULT 'MAD',

    -- Statut: brouillon, valide, envoye, livre, annule
    statut VARCHAR(20) NOT NULL DEFAULT 'brouillon',

    -- Conditions
    conditions_paiement VARCHAR(255) NULL,
    lieu_livraison VARCHAR(255) NULL,
    commentaire TEXT NULL,

    -- Traçabilité
    creee_par VARCHAR(100) NULL,

    -- Index
    INDEX idx_bc_fournisseur (code_fournisseur),
    INDEX idx_bc_statut (statut),
    INDEX idx_bc_date (date_creation),

    -- Clé étrangère
    FOREIGN KEY (code_fournisseur) REFERENCES fournisseurs(code_fournisseur)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- Table des lignes de bon de commande
CREATE TABLE IF NOT EXISTS lignes_bon_commande (
    id INT AUTO_INCREMENT PRIMARY KEY,
    numero_bc VARCHAR(50) NOT NULL,

    -- Traçabilité source (pour savoir d'où vient la ligne)
    ligne_source_id INT NULL,  -- ID dans reponses_fournisseurs_detail
    reponse_id INT NULL,       -- ID de la réponse entête
    numero_da VARCHAR(50) NULL,
    numero_rfq VARCHAR(50) NULL,

    -- Article
    code_article VARCHAR(100) NOT NULL,
    designation VARCHAR(500) NULL,
    quantite DECIMAL(15, 3) NOT NULL,
    unite VARCHAR(50) NULL,

    -- Prix
    prix_unitaire_ht DECIMAL(15, 4) NOT NULL,
    montant_ligne_ht DECIMAL(15, 2) NOT NULL,
    tva_pourcent DECIMAL(5, 2) NOT NULL DEFAULT 20.00,
    montant_ligne_ttc DECIMAL(15, 2) NOT NULL,

    -- Livraison
    date_livraison_prevue DATE NULL,

    -- Commentaire
    commentaire TEXT NULL,

    -- Index
    INDEX idx_lbc_bc (numero_bc),
    INDEX idx_lbc_article (code_article),
    INDEX idx_lbc_source (ligne_source_id),
    INDEX idx_lbc_da (numero_da),

    -- Clé étrangère
    FOREIGN KEY (numero_bc) REFERENCES bons_commande(numero_bc) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ════════════════════════════════════════════════════════════
-- Notes:
-- ════════════════════════════════════════════════════════════
-- Un BC peut contenir des lignes de plusieurs DA différentes
-- La colonne ligne_source_id permet de tracer la ligne originale
-- dans reponses_fournisseurs_detail (pour éviter les doublons)
-- Ajout colonne delai_livraison dans reponses_fournisseurs_detail (si pas déjà présente)
  ALTER TABLE reponses_fournisseurs_detail
  ADD COLUMN IF NOT EXISTS delai_livraison INT NULL COMMENT 'Délai livraison en jours'
  AFTER date_livraison;