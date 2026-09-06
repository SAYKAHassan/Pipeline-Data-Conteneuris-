CREATE DATABASE IF NOT EXISTS sfe_dwh
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE sfe_dwh;

-- ============================================================
-- 1. TABLES DE DIMENSIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS dim_entites (
    id_entite       INT AUTO_INCREMENT PRIMARY KEY,
    code_entite     VARCHAR(50)  NOT NULL UNIQUE        COMMENT 'Code court: JFC1, JFC2, EMAPHOS...',
    nom_entite      VARCHAR(255) NOT NULL               COMMENT 'Nom complet de l entité',
    date_creation   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_code (code_entite)
) ENGINE=InnoDB COMMENT='Dimension des entités OCP (usines, sites)';

CREATE TABLE IF NOT EXISTS dim_responsables (
    id_responsable  INT AUTO_INCREMENT PRIMARY KEY,
    nom_complet     VARCHAR(255) NOT NULL UNIQUE,
    email           VARCHAR(255),
    service         VARCHAR(100),
    est_actif       TINYINT DEFAULT 1,
    date_creation   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT chk_responsable_actif CHECK (est_actif IN (0, 1)),
    INDEX idx_nom (nom_complet),
    
    INDEX idx_email (email)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dim_statuts (
    id_statut           INT AUTO_INCREMENT PRIMARY KEY,
    code_statut         VARCHAR(50)  NOT NULL UNIQUE,
    libelle             VARCHAR(100) NOT NULL,

    ordre_avancement    DECIMAL(3,2) NOT NULL DEFAULT 0.00,
    CONSTRAINT chk_avancement CHECK (ordre_avancement BETWEEN 0.00 AND 1.00),
    INDEX idx_code (code_statut)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dim_priorites (
    id_priorite     INT AUTO_INCREMENT PRIMARY KEY,
    code_priorite   VARCHAR(50)  NOT NULL UNIQUE,
    libelle         VARCHAR(100) NOT NULL,
    -- AMÉLIORATION: Contrainte CHECK — ordre entre 0 et 10
    ordre           INT NOT NULL DEFAULT 0,
    CONSTRAINT chk_priorite_ordre CHECK (ordre BETWEEN 0 AND 10),
    INDEX idx_ordre (ordre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dim_source_types (
    id_source_type  INT AUTO_INCREMENT PRIMARY KEY,
    code_source     VARCHAR(50)  NOT NULL UNIQUE,
    libelle         VARCHAR(255) NOT NULL,
    categorie       VARCHAR(100),
    INDEX idx_code (code_source)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dim_dates (
    id_date         INT AUTO_INCREMENT PRIMARY KEY,
    date_full       DATE NOT NULL UNIQUE,
    annee           INT NOT NULL,
    trimestre       INT NOT NULL,
    mois_num        INT NOT NULL,
    mois_nom        VARCHAR(20) NOT NULL,
    mois_nom_court  VARCHAR(10),

    semaine_annee   INT,
    jour_semaine    INT NOT NULL,
    jour_nom        VARCHAR(20) NOT NULL,
    jour_num        INT NOT NULL,
    est_weekend     TINYINT NOT NULL DEFAULT 0,
    est_jour_ferie  TINYINT DEFAULT 0,
    est_fin_mois    TINYINT DEFAULT 0,

    CONSTRAINT chk_trimestre    CHECK (trimestre BETWEEN 1 AND 4),
    CONSTRAINT chk_mois_num     CHECK (mois_num  BETWEEN 1 AND 12),
    CONSTRAINT chk_jour_semaine CHECK (jour_semaine BETWEEN 1 AND 7),
    CONSTRAINT chk_jour_num     CHECK (jour_num  BETWEEN 1 AND 31),
    CONSTRAINT chk_est_weekend  CHECK (est_weekend IN (0, 1)),
    INDEX idx_date (date_full),
    INDEX idx_annee_mois (annee, mois_num)
) ENGINE=InnoDB;

-- ============================================================
-- 2. TABLE DE FAITS
-- ============================================================

CREATE TABLE IF NOT EXISTS fact_actions (
    id_action       INT AUTO_INCREMENT PRIMARY KEY,
    action_key      VARCHAR(64) NOT NULL               COMMENT 'Hash SHA256 pour déduplication SCD2',

    id_entite       INT NOT NULL,
    id_responsable  INT NOT NULL,
    id_statut       INT NOT NULL,
    id_priorite     INT NOT NULL,
    id_source_type  INT NOT NULL,
    id_date_echeance    INT,
    id_date_realisation INT,

    description_action  TEXT NOT NULL,
    localisation        VARCHAR(500),
    constat_original    TEXT,
    recommandation      TEXT,

    date_echeance       DATE,
    date_realisation    DATE,

    fichier_source      VARCHAR(255),
    sheet_source        VARCHAR(100),
    ligne_source        INT,

    date_debut_validite TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_fin_validite   TIMESTAMP NULL,
    -- AMÉLIORATION: Contrainte CHECK — est_actif = 0 ou 1 uniquement
    est_actif           TINYINT NOT NULL DEFAULT 1,
    CONSTRAINT chk_fact_actif CHECK (est_actif IN (0, 1)),

    date_import         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    import_batch_id     VARCHAR(36),

    FOREIGN KEY (id_entite)      REFERENCES dim_entites(id_entite),
    FOREIGN KEY (id_responsable) REFERENCES dim_responsables(id_responsable),
    FOREIGN KEY (id_statut)      REFERENCES dim_statuts(id_statut),
    FOREIGN KEY (id_priorite)    REFERENCES dim_priorites(id_priorite),
    FOREIGN KEY (id_source_type) REFERENCES dim_source_types(id_source_type),
    FOREIGN KEY (id_date_echeance)    REFERENCES dim_dates(id_date),
    FOREIGN KEY (id_date_realisation) REFERENCES dim_dates(id_date),

    INDEX idx_action_key  (action_key, est_actif),
    INDEX idx_batch       (import_batch_id),
    INDEX idx_statut      (id_statut, est_actif),
    INDEX idx_priorite    (id_priorite, est_actif),
    INDEX idx_echeance    (id_date_echeance, est_actif),
    INDEX idx_retard      (est_actif, id_priorite),
    INDEX idx_composite   (id_entite, id_statut, id_priorite)

) ENGINE=InnoDB COMMENT='Table de faits SCD Type 2 — actions de suivi SFE';

-- ============================================================
-- 3. DONNÉES DE RÉFÉRENCE
-- ============================================================

INSERT INTO dim_statuts (code_statut, libelle, ordre_avancement) VALUES
    ('FAIT',       'Fait',       1.00),
    ('EN_COURS',   'En cours',   0.50),
    ('PLANIFIE',   'Planifié',   0.10),
    ('NON_FAIT',   'Non fait',   0.00),
    ('NA',         'N.A',        0.00),
    ('NON_DEFINI', 'Non défini', 0.00)
ON DUPLICATE KEY UPDATE libelle = VALUES(libelle);

INSERT INTO dim_priorites (code_priorite, libelle, ordre) VALUES
    ('P4', 'P4 - Critique', 4),
    ('P3', 'P3 - Elevé',    3),
    ('P2', 'P2 - Moyen',    2),
    ('P1', 'P1 - Faible',   1),
    ('ND', 'Non défini',    0)
ON DUPLICATE KEY UPDATE libelle = VALUES(libelle);

INSERT INTO dim_source_types (code_source, libelle, categorie) VALUES
    ('PSM',        'Process Safety Management',    'Sécurité Process'),
    ('NH3',        'Ammoniac / NH3',               'Sécurité Chimique'),
    ('HT',         'Haute Tension',                'Sécurité Électrique'),
    ('FF',         'Fire Fighting',                'Sécurité Incendie'),
    ('Audit',      'Audit Général',                'Conformité'),
    ('Diagnostic', 'Diagnostic Technique',         'Maintenance'),
    ('Autre',      'Autre source',                 'Divers')
ON DUPLICATE KEY UPDATE libelle = VALUES(libelle);

DELIMITER //

CREATE PROCEDURE IF NOT EXISTS sp_generate_date_dim(
    IN p_start_year INT,
    IN p_end_year INT
)
BEGIN
    DECLARE v_date DATE;
    DECLARE v_end DATE;

    SET v_date = MAKEDATE(p_start_year, 1);
    SET v_end  = MAKEDATE(p_end_year, 1);

    WHILE v_date < v_end DO
        INSERT IGNORE INTO dim_dates (
            date_full, annee, trimestre, mois_num, mois_nom,
            mois_nom_court, semaine_annee, jour_semaine, jour_nom,
            jour_num, est_weekend, est_fin_mois
        ) VALUES (
            v_date,
            YEAR(v_date),
            QUARTER(v_date),
            MONTH(v_date),
            CASE MONTH(v_date)
                WHEN 1  THEN 'Janvier'   WHEN 2  THEN 'Février'   WHEN 3  THEN 'Mars'
                WHEN 4  THEN 'Avril'     WHEN 5  THEN 'Mai'       WHEN 6  THEN 'Juin'
                WHEN 7  THEN 'Juillet'   WHEN 8  THEN 'Août'      WHEN 9  THEN 'Septembre'
                WHEN 10 THEN 'Octobre'   WHEN 11 THEN 'Novembre'  WHEN 12 THEN 'Décembre'
            END,
            CASE MONTH(v_date)
                WHEN 1  THEN 'Jan' WHEN 2  THEN 'Fév' WHEN 3  THEN 'Mar'
                WHEN 4  THEN 'Avr' WHEN 5  THEN 'Mai' WHEN 6  THEN 'Jun'
                WHEN 7  THEN 'Jul' WHEN 8  THEN 'Aoû' WHEN 9  THEN 'Sep'
                WHEN 10 THEN 'Oct' WHEN 11 THEN 'Nov' WHEN 12 THEN 'Déc'
            END,
            WEEK(v_date, 3),
            WEEKDAY(v_date) + 1,
            CASE WEEKDAY(v_date)
                WHEN 0 THEN 'Lundi'    WHEN 1 THEN 'Mardi'    WHEN 2 THEN 'Mercredi'
                WHEN 3 THEN 'Jeudi'    WHEN 4 THEN 'Vendredi' WHEN 5 THEN 'Samedi'
                WHEN 6 THEN 'Dimanche'
            END,
            DAY(v_date),
            IF(WEEKDAY(v_date) >= 5, 1, 0),
            IF(LAST_DAY(v_date) = v_date, 1, 0)
        );
        SET v_date = DATE_ADD(v_date, INTERVAL 1 DAY);
    END WHILE;
END //

DELIMITER ;

CALL sp_generate_date_dim(2024, 2028);

-- ============================================================
-- 5. VUES ANALYTIQUES (Power BI)
-- ============================================================

CREATE OR REPLACE VIEW v_actions_current AS
SELECT
    f.id_action,
    f.action_key,
    f.description_action,
    f.localisation,
    f.constat_original,
    f.recommandation,
    e.code_entite           AS entite,
    e.nom_entite            AS entite_nom,
    r.nom_complet           AS responsable,
    r.service               AS responsable_service,
    s.code_statut           AS statut_code,
    s.libelle               AS statut,
    s.ordre_avancement      AS avancement_pct,
    p.code_priorite         AS priorite_code,
    p.libelle               AS priorite,
    p.ordre                 AS priorite_ordre,
    st.code_source          AS source_type,
    st.categorie            AS source_categorie,
    f.date_echeance,
    f.date_realisation,
    DATEDIFF(CURDATE(), f.date_echeance) AS jours_retard,
    CASE WHEN CURDATE() > f.date_echeance
         AND s.code_statut NOT IN ('FAIT', 'NA') THEN 1 ELSE 0 END AS est_en_retard,
    f.fichier_source,
    f.sheet_source,
    f.date_import
FROM fact_actions f
JOIN dim_entites      e  ON f.id_entite      = e.id_entite
JOIN dim_responsables r  ON f.id_responsable = r.id_responsable
JOIN dim_statuts      s  ON f.id_statut      = s.id_statut
JOIN dim_priorites    p  ON f.id_priorite    = p.id_priorite
JOIN dim_source_types st ON f.id_source_type = st.id_source_type
WHERE f.est_actif = 1;

CREATE OR REPLACE VIEW v_kpi_dashboard AS
SELECT
    COUNT(*) AS total_actions,
    SUM(CASE WHEN s.code_statut = 'FAIT'      THEN 1 ELSE 0 END) AS total_fait,
    SUM(CASE WHEN s.code_statut = 'EN_COURS'  THEN 1 ELSE 0 END) AS total_en_cours,
    SUM(CASE WHEN s.code_statut = 'PLANIFIE'  THEN 1 ELSE 0 END) AS total_planifie,
    SUM(CASE WHEN s.code_statut = 'NON_FAIT'  THEN 1 ELSE 0 END) AS total_non_fait,
    ROUND(SUM(CASE WHEN s.code_statut = 'FAIT' THEN 1 ELSE 0 END)
          * 100.0 / NULLIF(COUNT(*), 0), 1)                       AS taux_realisation_pct,
    SUM(CASE WHEN f.date_echeance IS NOT NULL
              AND s.code_statut NOT IN ('FAIT', 'NA')
              AND CURDATE() > f.date_echeance THEN 1 ELSE 0 END)  AS total_en_retard
FROM fact_actions f
JOIN dim_statuts s ON f.id_statut = s.id_statut
WHERE f.est_actif = 1;

CREATE OR REPLACE VIEW v_analyse_entite AS
SELECT
    e.code_entite AS entite,
    e.nom_entite,
    COUNT(*) AS total_actions,
    SUM(CASE WHEN s.code_statut = 'FAIT'     THEN 1 ELSE 0 END) AS nb_fait,
    SUM(CASE WHEN s.code_statut = 'EN_COURS' THEN 1 ELSE 0 END) AS nb_en_cours,
    SUM(CASE WHEN s.code_statut = 'PLANIFIE' THEN 1 ELSE 0 END) AS nb_planifie,
    SUM(CASE WHEN s.code_statut = 'NON_FAIT' THEN 1 ELSE 0 END) AS nb_non_fait,
    ROUND(SUM(CASE WHEN s.code_statut = 'FAIT' THEN 1 ELSE 0 END)
          * 100.0 / NULLIF(COUNT(*), 0), 1) AS taux_realisation_pct,
    SUM(CASE WHEN f.date_echeance IS NOT NULL
              AND s.code_statut NOT IN ('FAIT', 'NA')
              AND CURDATE() > f.date_echeance THEN 1 ELSE 0 END) AS nb_en_retard
FROM fact_actions f
JOIN dim_entites e ON f.id_entite = e.id_entite
JOIN dim_statuts s ON f.id_statut = s.id_statut
WHERE f.est_actif = 1
GROUP BY e.code_entite, e.nom_entite
ORDER BY nb_en_retard DESC;

CREATE OR REPLACE VIEW v_analyse_responsable AS
SELECT
    r.nom_complet AS responsable,
    r.service,
    COUNT(*) AS total_actions,
    SUM(CASE WHEN s.code_statut = 'FAIT'     THEN 1 ELSE 0 END) AS nb_fait,
    SUM(CASE WHEN s.code_statut = 'EN_COURS' THEN 1 ELSE 0 END) AS nb_en_cours,
    ROUND(SUM(CASE WHEN s.code_statut = 'FAIT' THEN 1 ELSE 0 END)
          * 100.0 / NULLIF(COUNT(*), 0), 1) AS taux_realisation_pct,
    SUM(CASE WHEN f.date_echeance IS NOT NULL
              AND s.code_statut NOT IN ('FAIT', 'NA')
              AND CURDATE() > f.date_echeance THEN 1 ELSE 0 END) AS nb_en_retard,
    SUM(CASE WHEN p.code_priorite IN ('P3', 'P4')
              AND s.code_statut != 'FAIT' THEN 1 ELSE 0 END) AS nb_critiques_ouvertes
FROM fact_actions f
JOIN dim_responsables r ON f.id_responsable = r.id_responsable
JOIN dim_statuts      s ON f.id_statut      = s.id_statut
JOIN dim_priorites    p ON f.id_priorite    = p.id_priorite
WHERE f.est_actif = 1
GROUP BY r.nom_complet, r.service
ORDER BY nb_en_retard DESC;

CREATE OR REPLACE VIEW v_alertes_critiques AS
SELECT
    f.id_action,
    f.action_key,
    f.description_action,
    e.code_entite   AS entite,
    r.nom_complet   AS responsable,
    p.code_priorite AS priorite,
    p.libelle       AS priorite_libelle,
    s.libelle       AS statut,
    f.date_echeance,
    DATEDIFF(CURDATE(), f.date_echeance) AS jours_retard,
    f.localisation,
    f.fichier_source,
    CASE
        WHEN p.code_priorite = 'P4' AND DATEDIFF(CURDATE(), f.date_echeance) > 30 THEN 'CRITIQUE'
        WHEN p.code_priorite = 'P4'                                                THEN 'URGENT'
        WHEN p.code_priorite = 'P3' AND DATEDIFF(CURDATE(), f.date_echeance) > 60 THEN 'URGENT'
        ELSE 'ATTENTION'
    END AS niveau_alerte
FROM fact_actions f
JOIN dim_entites      e ON f.id_entite      = e.id_entite
JOIN dim_responsables r ON f.id_responsable = r.id_responsable
JOIN dim_priorites    p ON f.id_priorite    = p.id_priorite
JOIN dim_statuts      s ON f.id_statut      = s.id_statut
WHERE f.est_actif = 1
  AND f.date_echeance IS NOT NULL
  AND CURDATE() > f.date_echeance
  AND p.code_priorite IN ('P3', 'P4')
  AND s.code_statut NOT IN ('FAIT', 'NA')
ORDER BY jours_retard DESC;

-- ============================================================
-- 6. INDEX ADDITIONNELS (Performance)
-- ============================================================

CREATE INDEX idx_fact_dates ON fact_actions(id_date_echeance, id_date_realisation, est_actif);
CREATE INDEX idx_fact_responsable ON fact_actions(id_responsable, est_actif);
CREATE INDEX idx_fact_composite_2 ON fact_actions(id_entite, id_source_type, est_actif);

-- ============================================================
-- 7. VÉRIFICATION
-- ============================================================

SELECT 'Tables créées:' AS info;
SHOW TABLES;

SELECT 'Vues créées:' AS info;
SHOW FULL TABLES WHERE Table_type = 'VIEW';

SELECT 'Nombre de dates générées:' AS info, COUNT(*) FROM dim_dates;
SELECT 'Nombre d actions importées:' AS info, COUNT(*) FROM fact_actions;