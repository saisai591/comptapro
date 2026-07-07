"""
Couche base de données SQLite pour la comptabilité.

Tables :
  - ecritures       : journal des écritures comptables (partie double)
  - lignes_ecriture : lignes d'écriture (compte, débit, crédit, libellé)
  - exercices       : exercices comptables
  - comptes_aux     : comptes auxiliaires (clients, fournisseurs, salariés…)
  - factures        : factures, devis, avoirs
  - lignes_facture  : lignes de facture
  - piste_audit     : piste d'audit (traçabilité)
  - lettrages       : lettrages comptables
  - lignes_lettrage : lignes de lettrage
  - releves_bancaires : imports de relevés bancaires
  - lignes_releve   : lignes de relevé bancaire
  - parametres      : configuration clé-valeur
  - previsions      : prévisionnel de trésorerie
  - validations_achat : circuit validation achats
  - abonnements      : abonnements & factures récurrentes
"""

import sqlite3
import os
from datetime import date, datetime
from typing import Optional

DB_PATH = os.environ.get("COMPTAPRO_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "comptabilite.db"))


def get_db() -> sqlite3.Connection:
    """Retourne une connexion à la base avec row_factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: Optional[sqlite3.Connection] = None):
    """Initialise le schéma complet de la base de données."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS exercices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            libelle     TEXT NOT NULL,
            date_debut  TEXT NOT NULL,
            date_fin    TEXT NOT NULL,
            cloture     INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS comptes_aux (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT NOT NULL UNIQUE,
            type        TEXT NOT NULL CHECK(type IN ('client','fournisseur','salarie','autre')),
            nom         TEXT NOT NULL,
            adresse     TEXT,
            siret       TEXT,
            email       TEXT,
            telephone   TEXT
        );

        CREATE TABLE IF NOT EXISTS ecritures (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            exercice_id INTEGER NOT NULL REFERENCES exercices(id),
            journal     TEXT NOT NULL DEFAULT 'OD',
            date        TEXT NOT NULL,
            piece       TEXT,
            reference   TEXT,
            libelle     TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (exercice_id) REFERENCES exercices(id)
        );

        CREATE TABLE IF NOT EXISTS lignes_ecriture (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ecriture_id     INTEGER NOT NULL REFERENCES ecritures(id) ON DELETE CASCADE,
            compte          TEXT NOT NULL,
            auxiliaire_id   INTEGER REFERENCES comptes_aux(id),
            debit           REAL NOT NULL DEFAULT 0,
            credit          REAL NOT NULL DEFAULT 0,
            libelle         TEXT,
            FOREIGN KEY (ecriture_id) REFERENCES ecritures(id) ON DELETE CASCADE,
            FOREIGN KEY (auxiliaire_id) REFERENCES comptes_aux(id)
        );

        -- Factures & devis
        CREATE TABLE IF NOT EXISTS factures (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            exercice_id     INTEGER NOT NULL REFERENCES exercices(id),
            type            TEXT NOT NULL CHECK(type IN ('devis','facture','avoir')),
            numero          TEXT NOT NULL,
            date            TEXT NOT NULL,
            echeance        TEXT,
            client_id       INTEGER REFERENCES comptes_aux(id),
            client_nom      TEXT,
            client_adresse  TEXT,
            client_email    TEXT,
            client_siret    TEXT,
            statut          TEXT NOT NULL DEFAULT 'brouillon'
                             CHECK(statut IN ('brouillon','envoyee','payee','annulee','en_retard')),
            total_ht        REAL NOT NULL DEFAULT 0,
            total_tva       REAL NOT NULL DEFAULT 0,
            total_ttc       REAL NOT NULL DEFAULT 0,
            notes           TEXT,
            ecriture_id     INTEGER REFERENCES ecritures(id),
            created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (exercice_id) REFERENCES exercices(id),
            FOREIGN KEY (client_id) REFERENCES comptes_aux(id),
            FOREIGN KEY (ecriture_id) REFERENCES ecritures(id)
        );

        CREATE TABLE IF NOT EXISTS lignes_facture (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            facture_id   INTEGER NOT NULL REFERENCES factures(id) ON DELETE CASCADE,
            description  TEXT NOT NULL,
            quantite     REAL NOT NULL DEFAULT 1,
            prix_unitaire REAL NOT NULL DEFAULT 0,
            tva_taux     REAL NOT NULL DEFAULT 20.0,
            FOREIGN KEY (facture_id) REFERENCES factures(id) ON DELETE CASCADE
        );

        -- Relevés bancaires
        CREATE TABLE IF NOT EXISTS releves_bancaires (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            exercice_id      INTEGER NOT NULL REFERENCES exercices(id),
            compte_bancaire  TEXT NOT NULL DEFAULT '512',
            date_import      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            fichier_original TEXT,
            solde_initial    REAL,
            solde_final      REAL,
            FOREIGN KEY (exercice_id) REFERENCES exercices(id)
        );

        CREATE TABLE IF NOT EXISTS lignes_releve (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            releve_id       INTEGER NOT NULL REFERENCES releves_bancaires(id) ON DELETE CASCADE,
            date            TEXT NOT NULL,
            description     TEXT NOT NULL,
            reference       TEXT,
            montant         REAL NOT NULL,
            compte_suggere  TEXT,
            ecriture_id     INTEGER REFERENCES ecritures(id),
            rapproche       INTEGER DEFAULT 0,
            FOREIGN KEY (releve_id) REFERENCES releves_bancaires(id) ON DELETE CASCADE,
            FOREIGN KEY (ecriture_id) REFERENCES ecritures(id)
        );

        -- Paramètres
        CREATE TABLE IF NOT EXISTS parametres (
            cle     TEXT PRIMARY KEY,
            valeur  TEXT
        );

        -- Relances impayés
        CREATE TABLE IF NOT EXISTS scenarios_relance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            actif INTEGER DEFAULT 1,
            conditions_json TEXT NOT NULL,
            modele_email TEXT NOT NULL,
            delai_jours INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS historique_relances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            facture_id INTEGER NOT NULL REFERENCES factures(id),
            scenario_id INTEGER REFERENCES scenarios_relance(id),
            date_envoi TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            statut TEXT DEFAULT 'envoye',
            message TEXT
        );

        -- Suivi budgétaire
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exercice_id INTEGER NOT NULL REFERENCES exercices(id),
            compte TEXT NOT NULL,
            mois INTEGER NOT NULL CHECK(mois BETWEEN 1 AND 12),
            montant REAL NOT NULL,
            notes TEXT,
            FOREIGN KEY (exercice_id) REFERENCES exercices(id)
        );

        -- Notes de frais
        CREATE TABLE IF NOT EXISTS notes_frais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exercice_id INTEGER NOT NULL REFERENCES exercices(id),
            employe TEXT NOT NULL DEFAULT 'Moi',
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            categorie TEXT NOT NULL DEFAULT 'divers',
            montant_ht REAL NOT NULL,
            tva_taux REAL DEFAULT 0,
            montant_ttc REAL NOT NULL,
            justificatif TEXT,
            statut TEXT DEFAULT 'brouillon' CHECK(statut IN ('brouillon','soumis','valide','rembourse')),
            compte_debit TEXT NOT NULL DEFAULT '625',
            ecriture_id INTEGER REFERENCES ecritures(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (exercice_id) REFERENCES exercices(id)
        );

        -- Piste d'audit
        CREATE TABLE IF NOT EXISTS piste_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entite_type TEXT NOT NULL,
            entite_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            utilisateur TEXT DEFAULT 'systeme',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        -- Lettrages
        CREATE TABLE IF NOT EXISTS lettrages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            date_creation TEXT DEFAULT (datetime('now','localtime')),
            exercice_id INTEGER NOT NULL REFERENCES exercices(id)
        );

        CREATE TABLE IF NOT EXISTS lignes_lettrage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lettrage_id INTEGER NOT NULL REFERENCES lettrages(id) ON DELETE CASCADE,
            ecriture_id INTEGER NOT NULL REFERENCES ecritures(id),
            ligne_id INTEGER NOT NULL,
            compte TEXT NOT NULL,
            montant REAL NOT NULL,
            sens TEXT NOT NULL CHECK(sens IN ('D','C'))
        );

        -- Prévisionnel
        CREATE TABLE IF NOT EXISTS previsions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exercice_id INTEGER NOT NULL REFERENCES exercices(id),
            mois INTEGER NOT NULL CHECK(mois BETWEEN 1 AND 12),
            categorie TEXT NOT NULL CHECK(categorie IN ('encaissement','decaissement')),
            compte TEXT NOT NULL,
            libelle TEXT NOT NULL,
            montant REAL NOT NULL,
            probabilite REAL DEFAULT 1.0,
            recurrence TEXT DEFAULT 'ponctuel',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (exercice_id) REFERENCES exercices(id)
        );

        -- Validation achats
        CREATE TABLE IF NOT EXISTS validations_achat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exercice_id INTEGER NOT NULL REFERENCES exercices(id),
            fournisseur TEXT NOT NULL,
            date_facture TEXT NOT NULL,
            numero_facture TEXT,
            description TEXT NOT NULL,
            montant_ttc REAL NOT NULL,
            compte_charge TEXT NOT NULL DEFAULT '607',
            tva_taux REAL DEFAULT 20.0,
            statut TEXT DEFAULT 'a_valider' CHECK(statut IN ('a_valider','valide','rejete','paye')),
            valide_par TEXT,
            valide_le TEXT,
            commentaire TEXT,
            ecriture_id INTEGER REFERENCES ecritures(id),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (exercice_id) REFERENCES exercices(id)
        );

        -- Index
        CREATE INDEX IF NOT EXISTS idx_lignes_ecriture ON lignes_ecriture(ecriture_id);
        CREATE INDEX IF NOT EXISTS idx_lignes_compte ON lignes_ecriture(compte);
        CREATE INDEX IF NOT EXISTS idx_ecritures_date ON ecritures(date);
        CREATE INDEX IF NOT EXISTS idx_ecritures_exercice ON ecritures(exercice_id);
        CREATE INDEX IF NOT EXISTS idx_factures_exercice ON factures(exercice_id);
        CREATE INDEX IF NOT EXISTS idx_factures_statut ON factures(statut);
        CREATE INDEX IF NOT EXISTS idx_lignes_releve_releve ON lignes_releve(releve_id);
        CREATE INDEX IF NOT EXISTS idx_previsions_exercice ON previsions(exercice_id);
        CREATE INDEX IF NOT EXISTS idx_validations_achat_exercice ON validations_achat(exercice_id);
        CREATE INDEX IF NOT EXISTS idx_validations_achat_statut ON validations_achat(statut);

        -- Abonnements
        CREATE TABLE IF NOT EXISTS abonnements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_nom TEXT NOT NULL,
            exercice_id INTEGER NOT NULL REFERENCES exercices(id),
            description TEXT NOT NULL,
            montant_ht REAL NOT NULL,
            tva_taux REAL DEFAULT 20.0,
            compte_produit TEXT NOT NULL DEFAULT '706',
            periodicite TEXT NOT NULL CHECK(periodicite IN ('mensuel','trimestriel','annuel')),
            jour_facturation INTEGER NOT NULL DEFAULT 1,
            prochaine_date TEXT NOT NULL,
            date_fin TEXT,
            actif INTEGER DEFAULT 1,
            derniere_execution TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (exercice_id) REFERENCES exercices(id)
        );

        CREATE INDEX IF NOT EXISTS idx_abonnements_exercice ON abonnements(exercice_id);
        CREATE INDEX IF NOT EXISTS idx_abonnements_prochaine ON abonnements(prochaine_date);

        -- Immobilisations
        CREATE TABLE IF NOT EXISTS immobilisations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exercice_id INTEGER NOT NULL REFERENCES exercices(id),
            compte_immo TEXT NOT NULL,
            compte_amort TEXT NOT NULL,
            designation TEXT NOT NULL,
            date_acquisition TEXT NOT NULL,
            valeur_acquisition REAL NOT NULL,
            duree_annees INTEGER NOT NULL,
            mode TEXT NOT NULL DEFAULT 'lineaire' CHECK(mode IN ('lineaire','degressif')),
            coefficient_degressif REAL DEFAULT 1.75,
            valeur_residuelle REAL DEFAULT 0,
            date_cession TEXT,
            prix_cession REAL,
            actif INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (exercice_id) REFERENCES exercices(id)
        );

        CREATE TABLE IF NOT EXISTS dotations_amortissement (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            immo_id INTEGER NOT NULL REFERENCES immobilisations(id) ON DELETE CASCADE,
            exercice_id INTEGER NOT NULL,
            annee INTEGER NOT NULL,
            dotation REAL NOT NULL,
            cumul REAL NOT NULL,
            vnc REAL NOT NULL,
            ecriture_id INTEGER REFERENCES ecritures(id),
            FOREIGN KEY (immo_id) REFERENCES immobilisations(id) ON DELETE CASCADE
        );

        -- Emprunts
        CREATE TABLE IF NOT EXISTS emprunts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exercice_id INTEGER NOT NULL REFERENCES exercices(id),
            designation TEXT NOT NULL,
            date_debut TEXT NOT NULL,
            montant REAL NOT NULL,
            taux_annuel REAL NOT NULL,
            duree_mois INTEGER NOT NULL,
            periodicite TEXT DEFAULT 'mensuelle' CHECK(periodicite IN ('mensuelle','trimestrielle')),
            type_amortissement TEXT DEFAULT 'constant' CHECK(type_amortissement IN ('constant','annuite_constante')),
            frais_dossier REAL DEFAULT 0,
            assurance REAL DEFAULT 0,
            date_fin TEXT,
            actif INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (exercice_id) REFERENCES exercices(id)
        );

        CREATE TABLE IF NOT EXISTS echeances_emprunt (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emprunt_id INTEGER NOT NULL REFERENCES emprunts(id) ON DELETE CASCADE,
            numero INTEGER NOT NULL,
            date_echeance TEXT NOT NULL,
            capital_restant_avant REAL NOT NULL,
            mensualite REAL NOT NULL,
            interets REAL NOT NULL,
            capital_rembourse REAL NOT NULL,
            assurance REAL NOT NULL DEFAULT 0,
            capital_restant_apres REAL NOT NULL,
            ecriture_id INTEGER REFERENCES ecritures(id),
            FOREIGN KEY (emprunt_id) REFERENCES emprunts(id) ON DELETE CASCADE
        );

        -- Catégories
        CREATE TABLE IF NOT EXISTS regles_categorisation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_cible TEXT NOT NULL,
            champ_recherche TEXT NOT NULL DEFAULT 'libelle',
            mot_cle TEXT NOT NULL,
            priorite INTEGER DEFAULT 0,
            actif INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_immobilisations_exercice ON immobilisations(exercice_id);
        CREATE INDEX IF NOT EXISTS idx_emprunts_exercice ON emprunts(exercice_id);
    """)

    # Extension : sous_type pour bons de commande/livraison/pro-forma
    try:
        conn.execute("ALTER TABLE factures ADD COLUMN sous_type TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass  # colonne déjà existante

    if doit_fermer:
        conn.close()
