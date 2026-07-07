"""
Notes de frais : création, validation, génération d'écritures comptables.
Statuts : brouillon → soumis → valide → rembourse.
"""

import sqlite3
from datetime import date, datetime
from typing import Optional

from .db import get_db


def creer_note(
    exercice_id: int,
    date_str: str,
    description: str,
    categorie: str = "divers",
    montant_ht: float = 0,
    tva_taux: float = 0,
    employe: str = "Moi",
    justificatif: Optional[str] = None,
    compte_debit: str = "625",
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Crée une note de frais et retourne son ID. Calcule montant_ttc automatiquement."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    montant_ttc = round(montant_ht * (1 + tva_taux / 100), 2)

    cur = conn.execute(
        """INSERT INTO notes_frais
           (exercice_id, employe, date, description, categorie,
            montant_ht, tva_taux, montant_ttc, justificatif, compte_debit)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (exercice_id, employe, date_str, description, categorie,
         montant_ht, tva_taux, montant_ttc, justificatif, compte_debit),
    )
    nid = cur.lastrowid

    if doit_fermer:
        conn.commit()
        conn.close()
    return nid


def lister_notes(
    exercice_id: int,
    statut: Optional[str] = None,
    categorie: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Liste les notes de frais avec filtres optionnels."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    query = "SELECT * FROM notes_frais WHERE exercice_id = ?"
    params = [exercice_id]
    if statut:
        query += " AND statut = ?"
        params.append(statut)
    if categorie:
        query += " AND categorie = ?"
        params.append(categorie)
    query += " ORDER BY date DESC, id DESC"

    rows = conn.execute(query, params).fetchall()

    if doit_fermer:
        conn.close()
    return [dict(r) for r in rows]


def valider_note(
    note_id: int,
    conn: Optional[sqlite3.Connection] = None,
):
    """Passe une note de frais en statut 'valide'."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    conn.execute(
        "UPDATE notes_frais SET statut = 'valide' WHERE id = ?",
        (note_id,),
    )

    if doit_fermer:
        conn.commit()
        conn.close()

    from .audit import log_action
    log_action("note_frais", note_id, "changement_statut",
               {"ancien": "soumis", "nouveau": "valide"})


def generer_ecriture_note(
    note_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    Génère l'écriture comptable correspondant à une note de frais validée.
    - Débit compte_debit (ex: 625) pour le montant HT
    - Débit 4456 pour la TVA récupérable
    - Crédit 421 (compte employé) pour le montant TTC
    Change le statut en 'rembourse' et lie l'écriture.
    Retourne l'ID de l'écriture créée.
    """
    from .ecritures import saisir_ecriture

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    row = conn.execute(
        "SELECT * FROM notes_frais WHERE id = ?", (note_id,)
    ).fetchone()
    if not row:
        if doit_fermer:
            conn.close()
        raise ValueError(f"Note de frais {note_id} introuvable")
    note = dict(row)

    if note["ecriture_id"]:
        if doit_fermer:
            conn.close()
        raise ValueError("Une écriture existe déjà pour cette note")

    if note["statut"] not in ("valide", "soumis"):
        if doit_fermer:
            conn.close()
        raise ValueError(f"La note doit être au statut 'valide' (actuel : {note['statut']})")

    ecriture_lignes = []

    # Débit compte de charge (HT)
    ecriture_lignes.append({
        "compte": note["compte_debit"],
        "debit": round(note["montant_ht"], 2),
        "credit": 0,
        "libelle": f"Note de frais — {note['description'][:60]}",
    })

    # Débit TVA si applicable
    if note["tva_taux"] and note["tva_taux"] > 0:
        tva_montant = round(note["montant_ttc"] - note["montant_ht"], 2)
        if tva_montant > 0:
            ecriture_lignes.append({
                "compte": "4456",
                "debit": tva_montant,
                "credit": 0,
                "libelle": f"TVA déductible {note['tva_taux']}% — Note {note_id}",
            })

    # Crédit compte employé (TTC)
    ecriture_lignes.append({
        "compte": "421",
        "debit": 0,
        "credit": round(note["montant_ttc"], 2),
        "libelle": f"Remboursement — {note['employe']}",
    })

    eid = saisir_ecriture(
        note["exercice_id"],
        "OD",
        note["date"],
        f"Note de frais #{note_id} — {note['employe']} — {note['description'][:80]}",
        ecriture_lignes,
        piece=f"NDF-{note_id}",
        reference=f"NDF-{note_id}",
        conn=conn,
    )

    conn.execute(
        "UPDATE notes_frais SET ecriture_id = ?, statut = 'rembourse' WHERE id = ?",
        (eid, note_id),
    )

    if doit_fermer:
        conn.commit()
        conn.close()

    from .audit import log_action
    log_action("note_frais", note_id, "generation_ecriture",
               {"ecriture_id": eid, "note_id": note_id})
    return eid


def stats_notes(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Statistiques des notes de frais : total, par catégorie, par mois."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    total_row = conn.execute(
        "SELECT SUM(montant_ttc) as total FROM notes_frais WHERE exercice_id = ?",
        (exercice_id,),
    ).fetchone()
    total = round(total_row["total"] or 0, 2)

    cat_rows = conn.execute(
        """SELECT categorie, SUM(montant_ttc) as total, COUNT(*) as nb
           FROM notes_frais WHERE exercice_id = ?
           GROUP BY categorie ORDER BY total DESC""",
        (exercice_id,),
    ).fetchall()
    par_categorie = [{"categorie": r["categorie"], "total": round(r["total"] or 0, 2), "nb": r["nb"]} for r in cat_rows]

    mois_rows = conn.execute(
        """SELECT substr(date, 1, 7) as mois, SUM(montant_ttc) as total, COUNT(*) as nb
           FROM notes_frais WHERE exercice_id = ?
           GROUP BY mois ORDER BY mois""",
        (exercice_id,),
    ).fetchall()
    par_mois = [{"mois": r["mois"], "total": round(r["total"] or 0, 2), "nb": r["nb"]} for r in mois_rows]

    if doit_fermer:
        conn.close()

    return {
        "total": total,
        "par_categorie": par_categorie,
        "par_mois": par_mois,
    }
