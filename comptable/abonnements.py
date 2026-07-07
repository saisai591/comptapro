"""
Abonnements & factures récurrentes.

Gère les abonnements clients : création, liste, exécution périodique,
génération automatique de factures.
"""

import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

from .db import get_db


# ── helpers calendrier ──────────────────────────────────────────────

def _mois_suivant(d: date) -> date:
    """Prochain mois, même jour (cap au 28 si nécessaire)."""
    y, m = d.year, d.month
    if m == 12:
        y, m = y + 1, 1
    else:
        m += 1
    max_day = 28  # sécurité : éviter les problèmes 29/30/31
    jour = min(d.day, max_day)
    return date(y, m, min(jour, max_day))


def _trimestre_suivant(d: date) -> date:
    """Prochain trimestre, même jour (cap au 28)."""
    y, m = d.year, d.month
    m += 3
    if m > 12:
        y += 1
        m -= 12
    return date(y, m, min(d.day, 28))


def _annee_suivante(d: date) -> date:
    """Prochaine année, même jour (cap au 28)."""
    return date(d.year + 1, d.month, min(d.day, 28))


def _prochaine_date(date_ref: date, periodicite: str) -> date:
    """Calcule la prochaine occurrence selon la périodicité."""
    if periodicite == "mensuel":
        return _mois_suivant(date_ref)
    elif periodicite == "trimestriel":
        return _trimestre_suivant(date_ref)
    else:  # annuel
        return _annee_suivante(date_ref)


# ── schéma ───────────────────────────────────────────────────────────

def init_abonnements(conn: Optional[sqlite3.Connection] = None):
    """Crée la table abonnements si elle n'existe pas."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    conn.execute("""
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
        )
    """)

    if doit_fermer:
        conn.commit()
        conn.close()


# ── CRUD ─────────────────────────────────────────────────────────────

def creer_abonnement(
    exercice_id: int,
    client_nom: str,
    description: str,
    montant_ht: float,
    periodicite: str,
    tva_taux: float = 20.0,
    jour_facturation: int = 1,
    date_debut: Optional[str] = None,
    date_fin: Optional[str] = None,
    compte_produit: str = "706",
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Crée un abonnement et retourne son ID."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    prochaine = date_debut or date.today().isoformat()

    cur = conn.execute(
        """INSERT INTO abonnements (client_nom, exercice_id, description, montant_ht,
           tva_taux, compte_produit, periodicite, jour_facturation,
           prochaine_date, date_fin, actif)
           VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
        (client_nom, exercice_id, description, round(montant_ht, 2),
         tva_taux, compte_produit, periodicite, jour_facturation,
         prochaine, date_fin),
    )
    aid = cur.lastrowid

    if doit_fermer:
        conn.commit()
        conn.close()
    return aid


def lister_abonnements(
    exercice_id: int,
    actif: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Liste les abonnements d'un exercice. Filtre actif=1/0 si fourni."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    query = "SELECT * FROM abonnements WHERE exercice_id = ?"
    params = [exercice_id]
    if actif is not None:
        query += " AND actif = ?"
        params.append(actif)
    query += " ORDER BY prochaine_date ASC"

    rows = conn.execute(query, params).fetchall()

    if doit_fermer:
        conn.close()
    return [dict(r) for r in rows]


def desactiver_abonnement(aid: int, conn: Optional[sqlite3.Connection] = None):
    """Désactive un abonnement."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    conn.execute("UPDATE abonnements SET actif = 0 WHERE id = ?", (aid,))

    if doit_fermer:
        conn.commit()
        conn.close()


# ── exécution ────────────────────────────────────────────────────────

def executer_abonnements(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Exécute tous les abonnements actifs arrivant à échéance.
    Pour chacun : crée une facture, met à jour prochaine_date,
    enregistre derniere_execution.
    """
    from .facturation import creer_facture

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    today_str = date.today().isoformat()

    abos = conn.execute(
        """SELECT * FROM abonnements
           WHERE exercice_id = ? AND actif = 1 AND prochaine_date <= ?""",
        (exercice_id, today_str),
    ).fetchall()

    details = []

    for a in abos:
        a = dict(a)
        montant_tva = round(a["montant_ht"] * a["tva_taux"] / 100, 2)
        montant_ttc = round(a["montant_ht"] + montant_tva, 2)

        lignes = [{
            "description": a["description"],
            "quantite": 1,
            "prix_unitaire": a["montant_ht"],
            "tva_taux": a["tva_taux"],
        }]

        # Déterminer si on est déjà dans un exercice compatible
        try:
            fid = creer_facture(
                exercice_id, "facture", today_str, lignes,
                client_nom=a["client_nom"],
                notes=f"Abonnement — {a['description']}",
                statut="brouillon",
                conn=conn,
            )
        except Exception as e:
            details.append({
                "abonnement_id": a["id"],
                "client": a["client_nom"],
                "montant": montant_ttc,
                "erreur": str(e),
            })
            continue

        # Prochaine occurrence
        ref_date = datetime.strptime(a["prochaine_date"], "%Y-%m-%d").date()
        # Si la date de fin est dépassée, désactiver
        if a["date_fin"]:
            date_fin_d = datetime.strptime(a["date_fin"], "%Y-%m-%d").date()
            if ref_date >= date_fin_d:
                conn.execute("UPDATE abonnements SET actif = 0 WHERE id = ?", (a["id"],))
                details.append({
                    "abonnement_id": a["id"],
                    "facture_id": fid,
                    "client": a["client_nom"],
                    "montant": montant_ttc,
                    "termine": True,
                })
                continue

        next_date = _prochaine_date(ref_date, a["periodicite"])
        conn.execute(
            """UPDATE abonnements SET prochaine_date = ?, derniere_execution = ?
               WHERE id = ?""",
            (next_date.isoformat(), today_str, a["id"]),
        )

        details.append({
            "abonnement_id": a["id"],
            "facture_id": fid,
            "client": a["client_nom"],
            "montant": montant_ttc,
        })

    if doit_fermer:
        conn.commit()
        conn.close()

    return {"nb_factures_generees": len(details), "details": details}


def prochains_abonnements(
    exercice_id: int,
    nb_jours: int = 30,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Liste les abonnements actifs arrivant à échéance dans les N prochains jours."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    today = date.today()
    deadline = (today + timedelta(days=nb_jours)).isoformat()
    today_str = today.isoformat()

    rows = conn.execute(
        """SELECT * FROM abonnements
           WHERE exercice_id = ? AND actif = 1
           AND prochaine_date >= ? AND prochaine_date <= ?
           ORDER BY prochaine_date ASC""",
        (exercice_id, today_str, deadline),
    ).fetchall()

    if doit_fermer:
        conn.close()
    return [dict(r) for r in rows]


def resume_abonnements(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Résumé des abonnements : nb actifs/inactifs, totaux, prochaines échéances."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    actifs = conn.execute(
        "SELECT COUNT(*) AS n FROM abonnements WHERE exercice_id = ? AND actif = 1",
        (exercice_id,),
    ).fetchone()["n"] or 0

    inactifs = conn.execute(
        "SELECT COUNT(*) AS n FROM abonnements WHERE exercice_id = ? AND actif = 0",
        (exercice_id,),
    ).fetchone()["n"] or 0

    totals = conn.execute(
        """SELECT periodicite, SUM(montant_ht) AS total
           FROM abonnements
           WHERE exercice_id = ? AND actif = 1
           GROUP BY periodicite""",
        (exercice_id,),
    ).fetchall()

    total_mensuel = 0.0
    total_annuel = 0.0
    for r in totals:
        ht = r["total"] or 0
        if r["periodicite"] == "mensuel":
            total_mensuel += ht
            total_annuel += ht * 12
        elif r["periodicite"] == "trimestriel":
            total_mensuel += ht / 3
            total_annuel += ht * 4
        else:  # annuel
            total_annuel += ht
            total_mensuel += ht / 12

    prochaines = conn.execute(
        """SELECT id AS abonnement_id, client_nom AS client, montant_ht,
                  prochaine_date, periodicite
           FROM abonnements
           WHERE exercice_id = ? AND actif = 1
           ORDER BY prochaine_date ASC
           LIMIT 10""",
        (exercice_id,),
    ).fetchall()

    if doit_fermer:
        conn.close()

    return {
        "actifs": actifs,
        "inactifs": inactifs,
        "total_mensuel": round(total_mensuel, 2),
        "total_annuel": round(total_annuel, 2),
        "prochaines_echeances": [dict(r) for r in prochaines],
    }
