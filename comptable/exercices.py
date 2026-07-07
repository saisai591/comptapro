"""
Gestion des exercices comptables.
"""

import sqlite3
from datetime import date
from typing import Optional

from .db import get_db


def creer_exercice(libelle: str, date_debut: str, date_fin: str,
                   conn: Optional[sqlite3.Connection] = None) -> int:
    """Crée un nouvel exercice comptable."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    cur = conn.execute(
        "INSERT INTO exercices (libelle, date_debut, date_fin) VALUES (?, ?, ?)",
        (libelle, date_debut, date_fin),
    )
    if doit_fermer:
        conn.commit()
        conn.close()
    return cur.lastrowid


def lister_exercices(conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    """Liste tous les exercices."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    rows = conn.execute(
        "SELECT * FROM exercices ORDER BY date_debut DESC"
    ).fetchall()

    if doit_fermer:
        conn.close()
    return [dict(r) for r in rows]


def exercice_actif(conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    """Retourne le dernier exercice non clôturé."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    row = conn.execute(
        "SELECT * FROM exercices WHERE cloture = 0 ORDER BY date_debut DESC LIMIT 1"
    ).fetchone()

    if doit_fermer:
        conn.close()
    return dict(row) if row else None


def cloturer_exercice(exercice_id: int, conn: Optional[sqlite3.Connection] = None):
    """Clôture un exercice."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    conn.execute("UPDATE exercices SET cloture = 1 WHERE id = ?", (exercice_id,))

    if doit_fermer:
        conn.commit()
        conn.close()
