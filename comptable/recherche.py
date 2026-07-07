"""
Recherche globale dans les données comptables.

Parcourt écritures, factures, notes de frais, comptes auxiliaires
et plan comptable pour une recherche plein-texte.
"""

import sqlite3
from typing import Optional

from .db import get_db


def rechercher_global(
    exercice_id: int,
    q: str,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """
    Cherche `q` dans toutes les entités :
    écritures, factures, notes de frais, comptes auxiliaires, plan comptable.
    Retourne [{type, id, label, detail, url}, ...].
    """
    if not q or not q.strip():
        return []

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    ql = f"%{q}%"
    results = []

    # Écritures
    for r in conn.execute(
        """SELECT id, journal, date, libelle, piece, reference
           FROM ecritures WHERE exercice_id = ?
           AND (libelle LIKE ? OR piece LIKE ? OR reference LIKE ?)
           ORDER BY date DESC LIMIT 20""",
        (exercice_id, ql, ql, ql),
    ):
        results.append({
            "type": "ecriture",
            "id": r["id"],
            "label": f"{r['journal']} — {r['libelle']}",
            "detail": f"{r['date']} | Pièce: {r['piece'] or '-'} | Réf: {r['reference'] or '-'}",
            "url": f"/ecritures/{r['id']}",
        })

    # Factures
    for r in conn.execute(
        """SELECT id, numero, client_nom, date, total_ttc, statut, notes
           FROM factures WHERE exercice_id = ?
           AND (numero LIKE ? OR client_nom LIKE ? OR notes LIKE ?)
           ORDER BY date DESC LIMIT 20""",
        (exercice_id, ql, ql, ql),
    ):
        results.append({
            "type": "facture",
            "id": r["id"],
            "label": f"{r['numero']} — {r['client_nom'] or '?'}",
            "detail": f"{r['date']} | {r['total_ttc']:.2f}€ | {r['statut']}",
            "url": f"/factures/{r['id']}",
        })

    # Notes de frais
    for r in conn.execute(
        """SELECT id, employe, date, description, montant_ttc, categorie, statut
           FROM notes_frais WHERE exercice_id = ?
           AND (description LIKE ? OR employe LIKE ?)
           ORDER BY date DESC LIMIT 20""",
        (exercice_id, ql, ql),
    ):
        results.append({
            "type": "note_frais",
            "id": r["id"],
            "label": f"{r['employe']} — {r['description']}",
            "detail": f"{r['date']} | {r['montant_ttc']:.2f}€ | {r['categorie']}",
            "url": f"/notes-frais/{r['id']}",
        })

    # Comptes auxiliaires
    for r in conn.execute(
        """SELECT id, code, type, nom
           FROM comptes_aux
           WHERE nom LIKE ? OR code LIKE ?
           ORDER BY nom LIMIT 10""",
        (ql, ql),
    ):
        results.append({
            "type": "compte_aux",
            "id": r["id"],
            "label": f"{r['code']} — {r['nom']}",
            "detail": r["type"],
            "url": f"/tiers/{r['id']}",
        })

    # Plan comptable — import du module plan_comptable
    try:
        from .plan_comptable import rechercher_compte
        comptes = rechercher_compte(q)
        for c in comptes[:10]:
            results.append({
                "type": "compte_pcg",
                "id": c.numero,
                "label": f"{c.numero} — {c.libelle}",
                "detail": f"Classe {c.classe}",
                "url": f"/plan-comptable/{c.numero}",
            })
    except Exception:
        pass  # plan_comptable peut ne pas avoir rechercher_compte avec cette signature

    if doit_fermer:
        conn.close()

    return results


def rechercher_ecritures(
    exercice_id: int,
    q: str,
    limite: int = 20,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Recherche plein-texte dans les écritures."""
    if not q:
        return []

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    ql = f"%{q}%"
    rows = conn.execute(
        """SELECT e.id, e.journal, e.date, e.libelle, e.piece, e.reference,
                  e.created_at
           FROM ecritures e
           WHERE e.exercice_id = ?
           AND (e.libelle LIKE ? OR e.piece LIKE ? OR e.reference LIKE ?
                OR e.id IN (
                  SELECT DISTINCT ecriture_id FROM lignes_ecriture
                  WHERE compte LIKE ? OR libelle LIKE ?
                ))
           ORDER BY e.date DESC
           LIMIT ?""",
        (exercice_id, ql, ql, ql, ql, ql, limite),
    ).fetchall()

    if doit_fermer:
        conn.close()
    return [dict(r) for r in rows]


def rechercher_factures(
    exercice_id: int,
    q: str,
    limite: int = 20,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Recherche plein-texte dans les factures."""
    if not q:
        return []

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    ql = f"%{q}%"
    rows = conn.execute(
        """SELECT id, type, numero, date, client_nom, total_ttc, statut, notes
           FROM factures WHERE exercice_id = ?
           AND (numero LIKE ? OR client_nom LIKE ? OR notes LIKE ?)
           ORDER BY date DESC
           LIMIT ?""",
        (exercice_id, ql, ql, ql, limite),
    ).fetchall()

    if doit_fermer:
        conn.close()
    return [dict(r) for r in rows]


def indexer(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Retourne un résumé de l'index : nb d'entités par type."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    nb_ecritures = conn.execute(
        "SELECT COUNT(*) AS n FROM ecritures WHERE exercice_id = ?",
        (exercice_id,),
    ).fetchone()["n"] or 0

    nb_factures = conn.execute(
        "SELECT COUNT(*) AS n FROM factures WHERE exercice_id = ?",
        (exercice_id,),
    ).fetchone()["n"] or 0

    nb_notes = conn.execute(
        "SELECT COUNT(*) AS n FROM notes_frais WHERE exercice_id = ?",
        (exercice_id,),
    ).fetchone()["n"] or 0

    nb_comptes = conn.execute(
        "SELECT COUNT(*) AS n FROM comptes_aux",
    ).fetchone()["n"] or 0

    if doit_fermer:
        conn.close()

    return {
        "exercice_id": exercice_id,
        "nb_ecritures": nb_ecritures,
        "nb_factures": nb_factures,
        "nb_notes": nb_notes,
        "nb_comptes_aux": nb_comptes,
    }
