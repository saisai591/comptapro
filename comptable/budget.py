"""
Suivi budgétaire : définition de budgets mensuels par compte,
import CSV, et comparaison budget vs réel (balance).
"""

import csv
import sqlite3
from datetime import date, datetime
from typing import Optional

from .db import get_db
from .balance import balance_generale


def definir_budget(
    exercice_id: int,
    compte: str,
    mois: int,
    montant: float,
    notes: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
):
    """Upsert un budget mensuel pour un compte donné (INSERT OR REPLACE)."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    conn.execute(
        """INSERT OR REPLACE INTO budgets (exercice_id, compte, mois, montant, notes)
           VALUES (?, ?, ?, ?, ?)""",
        (exercice_id, compte, mois, montant, notes),
    )

    if doit_fermer:
        conn.commit()
        conn.close()


def importer_budget_csv(
    exercice_id: int,
    chemin_fichier: str,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    Lit un fichier CSV (compte, mois, montant) et fait upsert.
    Retourne le nombre de lignes importées.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    nb = 0
    with open(chemin_fichier, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            compte = row.get("compte", "").strip()
            mois = int(row.get("mois", "1").strip())
            montant = float(row.get("montant", "0").strip())
            notes = row.get("notes", None)
            if compte and 1 <= mois <= 12:
                conn.execute(
                    """INSERT OR REPLACE INTO budgets (exercice_id, compte, mois, montant, notes)
                       VALUES (?, ?, ?, ?, ?)""",
                    (exercice_id, compte, mois, montant, notes),
                )
                nb += 1

    if doit_fermer:
        conn.commit()
        conn.close()
    return nb


def lister_budgets(
    exercice_id: int,
    mois: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Liste les budgets d'un exercice, filtrés par mois optionnellement."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    if mois:
        rows = conn.execute(
            "SELECT * FROM budgets WHERE exercice_id = ? AND mois = ? ORDER BY compte",
            (exercice_id, mois),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM budgets WHERE exercice_id = ? ORDER BY mois, compte",
            (exercice_id,),
        ).fetchall()

    if doit_fermer:
        conn.close()
    return [dict(r) for r in rows]


def comparaison_budget(
    exercice_id: int,
    mois: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """
    Pour chaque compte budgété : compare le budget au réel (balance).
    Le "reel" vient de balance_generale filtré par compte.
    Si mois est fourni, on filtre les écritures sur ce mois.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    # Récupère les budgets
    if mois:
        budgets = conn.execute(
            "SELECT compte, mois, montant FROM budgets WHERE exercice_id = ? AND mois = ?",
            (exercice_id, mois),
        ).fetchall()
    else:
        budgets = conn.execute(
            "SELECT compte, mois, montant FROM budgets WHERE exercice_id = ?",
            (exercice_id,),
        ).fetchall()

    # Détermine la date de fin pour le filtre
    date_fin = None
    if mois:
        # Prend l'année en cours (ou celle de l'exercice)
        ex = conn.execute(
            "SELECT date_debut FROM exercices WHERE id = ?", (exercice_id,)
        ).fetchone()
        annee = date.today().year
        if ex:
            try:
                annee = int(ex["date_debut"][:4])
            except (ValueError, IndexError):
                pass
        date_fin = f"{annee}-{mois:02d}-28"  # fin du mois approx

    balance = balance_generale(exercice_id, date_fin, conn=conn)

    # Index balance par compte
    balance_map = {b["compte"]: b for b in balance}

    # Regroupe les budgets par compte (somme si plusieurs mois)
    budget_par_compte = {}
    for b in budgets:
        c = b["compte"]
        if c not in budget_par_compte:
            budget_par_compte[c] = 0
        budget_par_compte[c] += b["montant"]

    result = []
    for compte, budget_total in sorted(budget_par_compte.items()):
        reel_row = balance_map.get(compte, {})
        # Le "réel" pour les charges (6) = solde_debit, pour les produits (7) = solde_credit
        if compte.startswith("6"):
            reel = reel_row.get("solde_debit", 0)
        elif compte.startswith("7"):
            reel = reel_row.get("solde_credit", 0)
        else:
            reel = abs(reel_row.get("solde_debit", 0) - reel_row.get("solde_credit", 0))

        ecart = round(budget_total - reel, 2)
        pct = round((reel / budget_total * 100), 1) if budget_total != 0 else 0

        result.append({
            "compte": compte,
            "budget": budget_total,
            "reel": reel,
            "ecart": ecart,
            "pct_consomme": pct,
        })

    if doit_fermer:
        conn.close()
    return result


def resume_budgetaire(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Résumé budgétaire global : total budget vs réel,
    top dépassements, et ventilation par mois.
    """
    comparaison = comparaison_budget(exercice_id, conn=conn)

    total_budget = sum(c["budget"] for c in comparaison)
    total_reel = sum(c["reel"] for c in comparaison)

    # Top dépassements (écart négatif = dépassement, donc reel > budget)
    depassements = sorted(
        [c for c in comparaison if c["pct_consomme"] > 100],
        key=lambda x: x["pct_consomme"],
        reverse=True,
    )[:5]
    top_dep = [
        {
            "compte": d["compte"],
            "budget": d["budget"],
            "reel": d["reel"],
            "ecart_pct": d["pct_consomme"],
        }
        for d in depassements
    ]

    # Par mois (on refait la comparaison mois par mois)
    par_mois = []
    for m in range(1, 13):
        comp_mois = comparaison_budget(exercice_id, mois=m, conn=conn)
        b_mois = sum(c["budget"] for c in comp_mois)
        r_mois = sum(c["reel"] for c in comp_mois)
        if b_mois > 0 or r_mois > 0:
            par_mois.append({
                "mois": m,
                "budget": b_mois,
                "reel": r_mois,
            })

    return {
        "total_budget": total_budget,
        "total_reel": total_reel,
        "ecart_global": round(total_budget - total_reel, 2),
        "top_depassements": top_dep,
        "par_mois": par_mois,
    }
