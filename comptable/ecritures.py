"""
Saisie et gestion des écritures comptables.

Partie double obligatoire : total débit = total crédit.
"""

import sqlite3
from datetime import date
from typing import Optional

from .db import get_db, init_db


JOURNAUX = {
    "OD": "Opérations diverses",
    "ACH": "Achats",
    "VTE": "Ventes",
    "BQ": "Banque",
    "CAISSE": "Caisse",
    "ANOUV": "À-nouveaux",
    "CLOT": "Clôture",
}


class EcritureError(ValueError):
    """Erreur de validation d'écriture."""
    pass


def saisir_ecriture(
    exercice_id: int,
    journal: str,
    date_str: str,
    libelle: str,
    lignes: list[dict],
    piece: Optional[str] = None,
    reference: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    Saisit une écriture comptable complète.

    Paramètres
    ----------
    exercice_id : int
        ID de l'exercice comptable.
    journal : str
        Code journal (OD, ACH, VTE, BQ, CAISSE, ANOUV, CLOT).
    date_str : str
        Date au format ISO YYYY-MM-DD.
    libelle : str
        Libellé de l'écriture.
    lignes : list[dict]
        Liste de dicts {'compte': '601', 'debit': 100.0, 'credit': 0, 'libelle': '...', 'auxiliaire_id': None}.
    piece : str, optional
        N° de pièce justificative.
    reference : str, optional
        Référence externe (n° facture…).

    Retourne
    -------
    int : ID de l'écriture créée.

    Lève
    ----
    EcritureError si la partie double n'est pas équilibrée.
    """
    if journal not in JOURNAUX:
        raise EcritureError(f"Journal inconnu : {journal}. Journaux valides : {', '.join(JOURNAUX)}")

    total_debit = sum(l.get("debit", 0) or 0 for l in lignes)
    total_credit = sum(l.get("credit", 0) or 0 for l in lignes)

    if not lignes:
        raise EcritureError("Une écriture doit avoir au moins une ligne.")

    if abs(total_debit - total_credit) > 0.005:
        raise EcritureError(
            f"Partie double non équilibrée : débit={total_debit:.2f}, crédit={total_credit:.2f} "
            f"(écart={abs(total_debit - total_credit):.2f})"
        )

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    try:
        cur = conn.execute(
            "INSERT INTO ecritures (exercice_id, journal, date, libelle, piece, reference) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (exercice_id, journal, date_str, libelle, piece, reference),
        )
        ecriture_id = cur.lastrowid

        for ligne in lignes:
            conn.execute(
                "INSERT INTO lignes_ecriture (ecriture_id, compte, auxiliaire_id, debit, credit, libelle) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ecriture_id,
                    str(ligne["compte"]),
                    ligne.get("auxiliaire_id"),
                    ligne.get("debit", 0) or 0,
                    ligne.get("credit", 0) or 0,
                    ligne.get("libelle"),
                ),
            )

        if doit_fermer:
            conn.commit()
            conn.close()
        return ecriture_id
    except Exception:
        if doit_fermer:
            conn.rollback()
            conn.close()
        raise


def lire_ecriture(ecriture_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    """Lit une écriture et ses lignes."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    ecriture = conn.execute(
        "SELECT * FROM ecritures WHERE id = ?", (ecriture_id,)
    ).fetchone()

    if not ecriture:
        if doit_fermer:
            conn.close()
        return None

    lignes = conn.execute(
        "SELECT * FROM lignes_ecriture WHERE ecriture_id = ? ORDER BY id",
        (ecriture_id,),
    ).fetchall()

    result = dict(ecriture)
    result["lignes"] = [dict(l) for l in lignes]

    if doit_fermer:
        conn.close()
    return result


def ecritures_journal(
    exercice_id: int,
    journal: Optional[str] = None,
    date_debut: Optional[str] = None,
    date_fin: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Liste les écritures d'un exercice, filtrées par journal et date."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    query = "SELECT * FROM ecritures WHERE exercice_id = ?"
    params = [exercice_id]

    if journal:
        query += " AND journal = ?"
        params.append(journal)
    if date_debut:
        query += " AND date >= ?"
        params.append(date_debut)
    if date_fin:
        query += " AND date <= ?"
        params.append(date_fin)

    query += " ORDER BY date, id"
    rows = conn.execute(query, params).fetchall()

    if doit_fermer:
        conn.close()
    return [dict(r) for r in rows]


def supprimer_ecriture(ecriture_id: int, conn: Optional[sqlite3.Connection] = None):
    """Supprime une écriture et ses lignes (CASCADE)."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    conn.execute("DELETE FROM ecritures WHERE id = ?", (ecriture_id,))

    if doit_fermer:
        conn.commit()
        conn.close()
