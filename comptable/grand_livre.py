"""
Grand-livre : détail des mouvements par compte.

Pour chaque compte, liste chronologique des écritures avec
cumul progressif du solde.
"""

import sqlite3
from typing import Optional


def grand_livre_compte(
    compte: str,
    exercice_id: int,
    date_debut: Optional[str] = None,
    date_fin: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Grand-livre d'un compte : toutes les lignes le concernant,
    avec solde progressif.
    """
    from .db import get_db

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    query = """
        SELECT e.id AS ecriture_id, e.journal, e.date, e.libelle AS ecriture_libelle,
               e.piece, l.compte, l.debit, l.credit, l.libelle AS ligne_libelle
        FROM lignes_ecriture l
        JOIN ecritures e ON e.id = l.ecriture_id
        WHERE e.exercice_id = ? AND l.compte = ?
    """
    params = [exercice_id, compte]

    if date_debut:
        query += " AND e.date >= ?"
        params.append(date_debut)
    if date_fin:
        query += " AND e.date <= ?"
        params.append(date_fin)

    query += " ORDER BY e.date, e.id"

    rows = conn.execute(query, params).fetchall()

    # Calcul du solde d'ouverture (écritures avant date_debut)
    solde_debit = 0.0
    solde_credit = 0.0

    if date_debut:
        opening = conn.execute(
            """
            SELECT SUM(l.debit) AS total_debit, SUM(l.credit) AS total_credit
            FROM lignes_ecriture l
            JOIN ecritures e ON e.id = l.ecriture_id
            WHERE e.exercice_id = ? AND l.compte = ? AND e.date < ?
            """,
            [exercice_id, compte, date_debut],
        ).fetchone()
        solde_debit = opening["total_debit"] or 0
        solde_credit = opening["total_credit"] or 0

    solde_cumul = round(solde_debit - solde_credit, 2)
    mouvements = []

    for r in rows:
        debit = r["debit"] or 0
        credit = r["credit"] or 0
        solde_cumul = round(solde_cumul + debit - credit, 2)
        mouvements.append({
            "ecriture_id": r["ecriture_id"],
            "date": r["date"],
            "journal": r["journal"],
            "piece": r["piece"],
            "libelle": r["ligne_libelle"] or r["ecriture_libelle"],
            "debit": round(debit, 2),
            "credit": round(credit, 2),
            "solde_cumul": solde_cumul,
        })

    total_debit = round(sum(m["debit"] for m in mouvements), 2)
    total_credit = round(sum(m["credit"] for m in mouvements), 2)

    if doit_fermer:
        conn.close()

    return {
        "compte": compte,
        "solde_ouverture": round(solde_debit - solde_credit, 2),
        "mouvements": mouvements,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "solde_final": solde_cumul,
    }


def grand_livre(
    exercice_id: int,
    comptes: Optional[list[str]] = None,
    date_debut: Optional[str] = None,
    date_fin: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """
    Grand-livre multi-comptes. Si `comptes` est None, tous les comptes mouvementés.
    """
    from .db import get_db

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    if comptes is None:
        rows = conn.execute(
            """
            SELECT DISTINCT l.compte
            FROM lignes_ecriture l
            JOIN ecritures e ON e.id = l.ecriture_id
            WHERE e.exercice_id = ?
            ORDER BY CAST(l.compte AS INTEGER)
            """,
            [exercice_id],
        ).fetchall()
        comptes = [r["compte"] for r in rows]

    if doit_fermer:
        conn.close()

    return [
        grand_livre_compte(c, exercice_id, date_debut, date_fin)
        for c in comptes
    ]
