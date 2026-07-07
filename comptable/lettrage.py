"""
Lettrage comptable : association des lignes d'écriture débit/crédit
pour les comptes de tiers (401, 411, etc.).
Stdlib uniquement.
"""

from typing import Optional

from .db import get_db


def _prochain_code(conn) -> str:
    """Génère le prochain code de lettrage LET-NNNN."""
    row = conn.execute("SELECT MAX(id) as m FROM lettrages").fetchone()
    n = (row["m"] or 0) + 1
    return f"LET-{n:04d}"


def creer_lettrage(exercice_id: int) -> int:
    """Crée un nouveau lettrage et retourne son ID."""
    conn = get_db()
    code = _prochain_code(conn)
    cur = conn.execute(
        "INSERT INTO lettrages (code, exercice_id) VALUES (?, ?)",
        (code, exercice_id),
    )
    lid = cur.lastrowid
    conn.commit()
    conn.close()
    return lid


def ajouter_ligne_lettrage(
    lettrage_id: int,
    ecriture_id: int,
    ligne_id: int,
    compte: str,
    montant: float,
    sens: str,
):
    """Ajoute une ligne d'écriture au lettrage."""
    if sens not in ("D", "C"):
        raise ValueError(f"Sens invalide : {sens} (attendu D ou C)")

    conn = get_db()
    conn.execute(
        """INSERT INTO lignes_lettrage (lettrage_id, ecriture_id, ligne_id, compte, montant, sens)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (lettrage_id, ecriture_id, ligne_id, compte, montant, sens),
    )
    conn.commit()
    conn.close()


def lister_lettrages(exercice_id: int) -> list[dict]:
    """Liste les lettrages d'un exercice avec nb lignes et totaux."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM lettrages WHERE exercice_id = ? ORDER BY id DESC",
        (exercice_id,),
    ).fetchall()

    result = []
    for r in rows:
        totals = conn.execute(
            """SELECT COUNT(*) as nb,
                      SUM(CASE WHEN sens='D' THEN montant ELSE 0 END) as total_debit,
                      SUM(CASE WHEN sens='C' THEN montant ELSE 0 END) as total_credit
               FROM lignes_lettrage WHERE lettrage_id = ?""",
            (r["id"],),
        ).fetchone()
        d = dict(r)
        d["nb_lignes"] = totals["nb"] or 0
        d["total_debit"] = round(totals["total_debit"] or 0, 2)
        d["total_credit"] = round(totals["total_credit"] or 0, 2)
        result.append(d)

    conn.close()
    return result


def detail_lettrage(lettrage_id: int) -> Optional[dict]:
    """Détail d'un lettrage avec ses lignes et totaux."""
    conn = get_db()
    r = conn.execute("SELECT * FROM lettrages WHERE id = ?", (lettrage_id,)).fetchone()
    if not r:
        conn.close()
        return None

    lignes = conn.execute(
        """SELECT ll.*, e.date as ecriture_date, e.libelle as ecriture_libelle
           FROM lignes_lettrage ll
           JOIN ecritures e ON e.id = ll.ecriture_id
           WHERE ll.lettrage_id = ?
           ORDER BY ll.id""",
        (lettrage_id,),
    ).fetchall()

    total_debit = sum(l["montant"] for l in lignes if l["sens"] == "D")
    total_credit = sum(l["montant"] for l in lignes if l["sens"] == "C")

    conn.close()
    return {
        **dict(r),
        "lignes": [dict(l) for l in lignes],
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "equilibre": abs(total_debit - total_credit) < 0.005,
    }


def supprimer_lettrage(lettrage_id: int) -> dict:
    """Supprime un lettrage et ses lignes (CASCADE)."""
    conn = get_db()
    conn.execute("DELETE FROM lettrages WHERE id = ?", (lettrage_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "id": lettrage_id}


def suggerer_lettrage(compte: str) -> list[dict]:
    """Trouve les lignes non-lettrées pour un compte tiers
    et suggère des paires débit/crédit de même montant.
    """
    conn = get_db()

    # Lignes non-lettrées pour ce compte
    rows = conn.execute(
        """SELECT le.id as ligne_id, le.ecriture_id, le.compte, le.debit, le.credit, le.libelle,
                  e.date, e.libelle as ecriture_libelle, e.piece
           FROM lignes_ecriture le
           JOIN ecritures e ON e.id = le.ecriture_id
           WHERE le.compte = ?
             AND le.id NOT IN (SELECT ligne_id FROM lignes_lettrage)
           ORDER BY e.date, le.id""",
        (compte,),
    ).fetchall()

    conn.close()

    debits = [dict(r) for r in rows if r["debit"] > 0]
    credits = [dict(r) for r in rows if r["credit"] > 0]

    suggestions = []
    credits_copie = list(credits)

    for d_line in debits:
        montant = d_line["debit"]
        for c_line in credits_copie:
            if abs(c_line["credit"] - montant) < 0.005:
                suggestions.append({
                    "debit": {"ligne_id": d_line["ligne_id"],
                              "ecriture_id": d_line["ecriture_id"],
                              "montant": d_line["debit"],
                              "date": d_line["date"],
                              "libelle": d_line["libelle"] or d_line["ecriture_libelle"]},
                    "credit": {"ligne_id": c_line["ligne_id"],
                               "ecriture_id": c_line["ecriture_id"],
                               "montant": c_line["credit"],
                               "date": c_line["date"],
                               "libelle": c_line["libelle"] or c_line["ecriture_libelle"]},
                })
                credits_copie.remove(c_line)
                break

    return suggestions


def comptes_lettrables(exercice_id: int) -> list[dict]:
    """Liste les comptes de tiers (401, 411, etc.) avec soldes
    et nombre de lignes non-lettrées.
    """
    conn = get_db()

    rows = conn.execute(
        """SELECT le.compte,
                  SUM(le.debit) as total_debit,
                  SUM(le.credit) as total_credit,
                  COUNT(*) as nb_lignes,
                  COUNT(DISTINCT le.id) - COUNT(DISTINCT ll.ligne_id) as nb_non_lettrees
           FROM lignes_ecriture le
           JOIN ecritures e ON e.id = le.ecriture_id
           LEFT JOIN lignes_lettrage ll ON ll.ligne_id = le.id
           WHERE e.exercice_id = ?
             AND (le.compte LIKE '40%' OR le.compte LIKE '41%')
           GROUP BY le.compte
           HAVING nb_non_lettrees > 0
           ORDER BY le.compte""",
        (exercice_id,),
    ).fetchall()

    conn.close()
    return [{
        "compte": r["compte"],
        "total_debit": round(r["total_debit"] or 0, 2),
        "total_credit": round(r["total_credit"] or 0, 2),
        "solde": round((r["total_debit"] or 0) - (r["total_credit"] or 0), 2),
        "nb_lignes": r["nb_lignes"],
        "nb_non_lettrees": r["nb_non_lettrees"],
    } for r in rows]
