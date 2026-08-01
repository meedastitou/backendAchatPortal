-- ════════════════════════════════════════════════════════════
-- Table pour Selections Articles (Pre-Bon de Commande)
-- ════════════════════════════════════════════════════════════

-- Table des selections d'articles par fournisseur
CREATE TABLE IF NOT EXISTS selections_articles (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Article et DA
    code_article VARCHAR(100) NOT NULL,
    designation VARCHAR(500) NULL,
    numero_da VARCHAR(50) NOT NULL,
    quantite DECIMAL(15, 3) NOT NULL,
    unite VARCHAR(50) NULL,

    -- Fournisseur selectionne
    code_fournisseur VARCHAR(50) NOT NULL,
    detail_id INT NOT NULL,  -- FK vers reponses_fournisseurs_detail

    -- Prix et marque
    prix_selectionne DECIMAL(15, 4) NOT NULL,
    devise VARCHAR(10) NOT NULL DEFAULT 'MAD',
    marque_proposee VARCHAR(255) NULL,
    marque_conforme BOOLEAN NULL,

    -- Date livraison
    date_livraison DATE NULL,
    delai_livraison INT NULL,

    -- Traçabilite de la selection
    selection_auto BOOLEAN NOT NULL DEFAULT TRUE,
    modifie_par VARCHAR(100) NULL,
    date_selection DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_modification DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,

    -- Statut: selectionne, en_attente_bc, bc_genere
    statut VARCHAR(30) NOT NULL DEFAULT 'selectionne',
    numero_bc VARCHAR(50) NULL,  -- Reference au BC une fois genere

    -- Index
    INDEX idx_sel_article (code_article),
    INDEX idx_sel_da (numero_da),
    INDEX idx_sel_fournisseur (code_fournisseur),
    INDEX idx_sel_statut (statut),
    INDEX idx_sel_detail (detail_id),

    -- Contrainte d'unicite: un seul fournisseur selectionne par article/DA
    UNIQUE KEY uk_article_da (code_article, numero_da),

    -- Cles etrangeres
    FOREIGN KEY (code_fournisseur) REFERENCES fournisseurs(code_fournisseur),
    FOREIGN KEY (detail_id) REFERENCES reponses_fournisseurs_detail(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ════════════════════════════════════════════════════════════
-- Notes:
-- ════════════════════════════════════════════════════════════
-- Cette table stocke les selections de fournisseurs par article
-- avant la generation du bon de commande.
--
-- Flux:
-- 1. Comparaison: selection auto (meilleur prix) ou manuelle
-- 2. Pre-BC: vue groupee par fournisseur, validation
-- 3. BC: generation du bon de commande -> statut = 'bc_genere'
--
-- La contrainte UNIQUE sur (code_article, numero_da) garantit
-- qu'un seul fournisseur peut etre selectionne par article/DA
