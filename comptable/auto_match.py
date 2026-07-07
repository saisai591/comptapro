"""
Rapprochement bancaire automatique.
Utilise les tables existantes ecritures + lignes_releve sans table supplémentaire.
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from .db import get_db


def _chercher_ecriture_bancaire(
    conn: sqlite3.Connection,
    exercice_id: int,
    montant: float,
    date_ref: str,
    tolerance_jours: int = 3,
    tolerance_montant: float = 0.01,
) -> Optional[dict]:
    """Cherche une écriture bancaire (journal BQ) proche en montant et date."""
    date_dt = datetime.strptime(date_ref, "%Y-%m-%d")
    debut = (date_dt - timedelta(days=tolerance_jours)).strftime("%Y-%m-%d")
    fin = (date_dt + timedelta(days=tolerance_jours)).strftime("%Y-%m-%d")
    montant_abs = abs(montant)
    montant_min = montant_abs - tolerance_montant
    montant_max = montant_abs + tolerance_montant

    row = conn.execute(
        """
        SELECT le.ecriture_id, le.id AS ligne_id, le.compte,
               le.debit, le.credit, le.libelle,
               e.date, e.libelle AS ecriture_libelle
        FROM lignes_ecriture le
        JOIN ecritures e ON e.id = le.ecriture_id
        WHERE e.exercice_id = ?
          AND e.journal = 'BQ'
          AND e.date BETWEEN ? AND ?
          AND (
              (le.debit BETWEEN ? AND ?)
              OR (le.credit BETWEEN ? AND ?)
          )
          AND le.ecriture_id NOT IN (
              SELECT lr.ecriture_id FROM lignes_releve lr
              JOIN releves_bancaires rb ON rb.id = lr.releve_id
              WHERE rb.exercice_id = ? AND lr.ecriture_id IS NOT NULL
          )
        ORDER BY ABS(julianday(e.date) - julianday(?)) ASC,
                 ABS(MAX(le.debit, le.credit) - ?) ASC
        LIMIT 1
        """,
        (
            exercice_id, debut, fin,
            montant_min, montant_max,
            montant_min, montant_max,
            exercice_id, date_ref, montant_abs,
        ),
    ).fetchone()

    if row:
        return dict(row)
    return None


def auto_rapprocher(
    exercice_id: int,
    tolerance_jours: int = 3,
    tolerance_montant: float = 0.01,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Rapprochement automatique :
    1. Lignes de relevé non rapprochées
    2. Cherche écriture BQ avec même montant (± tolerance) et date proche
    3. Rapproche si trouvé
    Retourne {nb_rapproches, nb_restants, details}.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    lignes = conn.execute(
        """
        SELECT lr.id, lr.date, lr.montant, lr.description, lr.reference
        FROM lignes_releve lr
        JOIN releves_bancaires rb ON rb.id = lr.releve_id
        WHERE rb.exercice_id = ? AND lr.rapproche = 0
        ORDER BY lr.date
        """,
        (exercice_id,),
    ).fetchall()

    nb_rapproches = 0
    details = []

    for lig in lignes:
        ecriture = _chercher_ecriture_bancaire(
            conn, exercice_id, lig["montant"], lig["date"],
            tolerance_jours, tolerance_montant,
        )
        if ecriture:
            conn.execute(
                "UPDATE lignes_releve SET rapproche = 1, ecriture_id = ? WHERE id = ?",
                (ecriture["ecriture_id"], lig["id"]),
            )
            nb_rapproches += 1
            details.append({
                "ligne_id": lig["id"],
                "ecriture_id": ecriture["ecriture_id"],
                "montant": lig["montant"],
                "date": lig["date"],
            })

    conn.commit()
    nb_total = len(lignes)

    if doit_fermer:
        conn.close()

    return {
        "nb_rapproches": nb_rapproches,
        "nb_restants": nb_total - nb_rapproches,
        "details": details,
    }


def auto_rapprocher_factures(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Match les lignes de relevé avec les factures payées
    (montant TTC + nom client dans le libellé)."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    lignes = conn.execute(
        """
        SELECT lr.id, lr.date, lr.montant, lr.description, lr.reference
        FROM lignes_releve lr
        JOIN releves_bancaires rb ON rb.id = lr.releve_id
        WHERE rb.exercice_id = ? AND lr.rapproche = 0
        ORDER BY lr.date
        """,
        (exercice_id,),
    ).fetchall()

    nb_rapproches = 0
    details = []

    for lig in lignes:
        montant = abs(lig["montant"])
        desc = lig["description"] or ""
        ref = lig["reference"] or ""

        row = conn.execute(
            """
            SELECT f.id, f.client_nom, f.total_ttc, f.numero
            FROM factures f
            WHERE f.exercice_id = ?
              AND ABS(f.total_ttc - ?) < 0.05
              AND f.client_nom != ''
              AND f.client_nom IS NOT NULL
              AND (
                  ? LIKE '%' || f.client_nom || '%'
                  OR f.numero LIKE '%' || ? || '%'
              )
            LIMIT 1
            """,
            (exercice_id, montant, desc, ref),
        )

        facture = row.fetchone() if row else None
        if facture:
            conn.execute(
                "UPDATE lignes_releve SET rapproche = 1 WHERE id = ?",
                (lig["id"],),
            )
            nb_rapproches += 1
            details.append({
                "ligne_id": lig["id"],
                "facture_id": facture["id"],
                "montant": lig["montant"],
                "client": facture["client_nom"],
            })

    conn.commit()
    nb_total = len(lignes)

    if doit_fermer:
        conn.close()

    return {
        "nb_rapproches": nb_rapproches,
        "nb_restants": nb_total - nb_rapproches,
        "details": details,
    }


def etat_rapprochement_auto(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """État global du rapprochement auto : total, rapprochées, par compte."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    total = conn.execute(
        """
        SELECT COUNT(*) AS n FROM lignes_releve lr
        JOIN releves_bancaires rb ON rb.id = lr.releve_id
        WHERE rb.exercice_id = ?
        """,
        (exercice_id,),
    ).fetchone()["n"]

    rapprochees = conn.execute(
        """
        SELECT COUNT(*) AS n FROM lignes_releve lr
        JOIN releves_bancaires rb ON rb.id = lr.releve_id
        WHERE rb.exercice_id = ? AND lr.rapproche = 1
        """,
        (exercice_id,),
    ).fetchone()["n"]

    non_rapprochees = total - rapprochees
    pct = round(rapprochees / total * 100, 1) if total > 0 else 0.0

    par_compte = conn.execute(
        """
        SELECT rb.compte_bancaire AS compte,
               COUNT(*) AS nb,
               SUM(CASE WHEN lr.rapproche = 1 THEN 1 ELSE 0 END) AS nb_ok
        FROM lignes_releve lr
        JOIN releves_bancaires rb ON rb.id = lr.releve_id
        WHERE rb.exercice_id = ?
        GROUP BY rb.compte_bancaire
        ORDER BY rb.compte_bancaire
        """,
        (exercice_id,),
    ).fetchall()

    par_compte_result = []
    for pc in par_compte:
        pct_pc = round(pc["nb_ok"] / pc["nb"] * 100, 1) if pc["nb"] > 0 else 0.0
        par_compte_result.append({
            "compte": pc["compte"],
            "nb": pc["nb"],
            "pct": pct_pc,
        })

    if doit_fermer:
        conn.close()

    return {
        "total_lignes": total,
        "lignes_rapprochees": rapprochees,
        "lignes_non_rapprochees": non_rapprochees,
        "pct_rapproche": pct,
        "par_compte": par_compte_result,
    }
