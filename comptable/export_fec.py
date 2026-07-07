"""
Export FEC (Fichier des Écritures Comptables) — format réglementaire français.

Conforme à l'article A.47 A-1 du Livre des Procédures Fiscales.
"""

import csv
import sqlite3
from datetime import date
from io import StringIO
from typing import Optional

from .db import get_db


def exporter_fec(
    exercice_id: int,
    chemin_fichier: str,
    siren: str = "",
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    Exporte les écritures au format FEC (tabulation, encodage ISO-8859-1).

    Colonnes FEC :
      JournalCode | JournalLib | EcritureNum | EcritureDate | CompteNum |
      CompteLib | CompAuxNum | CompAuxLib | PieceRef | PieceDate |
      EcritureLib | Debit | Credit | EcritureLet | DateLet |
      ValidDate | Montantdevise | Idevise

    Retourne le nombre d'écritures exportées.
    """
    from .plan_comptable import compte_par_numero

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    from .ecritures import JOURNAUX

    rows = conn.execute(
        """
        SELECT e.id, e.journal, e.date, e.piece, e.libelle AS ecriture_libelle,
               l.compte, l.debit, l.credit, l.libelle AS ligne_libelle,
               l.auxiliaire_id
        FROM ecritures e
        JOIN lignes_ecriture l ON l.ecriture_id = e.id
        WHERE e.exercice_id = ?
        ORDER BY e.journal, e.date, e.id, l.id
        """,
        [exercice_id],
    ).fetchall()

    with open(chemin_fichier, "w", encoding="ISO-8859-1", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        # En-tête
        writer.writerow([
            "JournalCode", "JournalLib", "EcritureNum", "EcritureDate",
            "CompteNum", "CompteLib", "CompAuxNum", "CompAuxLib",
            "PieceRef", "PieceDate", "EcritureLib",
            "Debit", "Credit", "EcritureLet", "DateLet",
            "ValidDate", "Montantdevise", "Idevise",
        ])

        for r in rows:
            compte = compte_par_numero(r["compte"])
            compte_lib = compte.libelle if compte else ""
            journal_lib = JOURNAUX.get(r["journal"], "")

            aux_num = ""
            aux_lib = ""
            if r["auxiliaire_id"]:
                aux = conn.execute(
                    "SELECT code, nom FROM comptes_aux WHERE id = ?",
                    [r["auxiliaire_id"]],
                ).fetchone()
                if aux:
                    aux_num = aux["code"]
                    aux_lib = aux["nom"]

            writer.writerow([
                r["journal"],
                journal_lib,
                str(r["id"]),
                r["date"],
                r["compte"],
                compte_lib,
                aux_num,
                aux_lib,
                r["piece"] or "",
                r["date"],  # PieceDate = date de l'écriture par défaut
                (r["ligne_libelle"] or r["ecriture_libelle"] or ""),
                str(r["debit"] or 0).replace(".", ","),
                str(r["credit"] or 0).replace(".", ","),
                "",  # EcritureLet
                "",  # DateLet
                r["date"],  # ValidDate
                "",  # Montantdevise
                "",  # Idevise
            ])

    if doit_fermer:
        conn.close()

    return len(rows)
