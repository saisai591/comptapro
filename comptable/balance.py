"""
Balance comptable et comptes de résultat.

Produit :
  - Balance générale (tous les comptes mouvementés)
  - Balance par classe
  - Compte de résultat (charges 6 / produits 7)
  - Bilan synthétique
"""

import sqlite3
from collections import defaultdict
from typing import Optional


def balance_generale(
    exercice_id: int,
    date_fin: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """
    Calcule la balance générale : pour chaque compte mouvementé,
    total débit, total crédit, et solde.
    """
    from .db import get_db

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    query = """
        SELECT l.compte,
               SUM(l.debit)  AS total_debit,
               SUM(l.credit) AS total_credit
        FROM lignes_ecriture l
        JOIN ecritures e ON e.id = l.ecriture_id
        WHERE e.exercice_id = ?
    """
    params = [exercice_id]

    if date_fin:
        query += " AND e.date <= ?"
        params.append(date_fin)

    query += " GROUP BY l.compte ORDER BY CAST(l.compte AS INTEGER)"

    rows = conn.execute(query, params).fetchall()

    result = []
    for r in rows:
        total_debit = r["total_debit"] or 0
        total_credit = r["total_credit"] or 0
        solde_debit = round(total_debit - total_credit, 2)
        solde_credit = round(total_credit - total_debit, 2)
        result.append({
            "compte": r["compte"],
            "total_debit": round(total_debit, 2),
            "total_credit": round(total_credit, 2),
            "solde_debit": solde_debit if solde_debit > 0 else 0,
            "solde_credit": solde_credit if solde_credit > 0 else 0,
        })

    if doit_fermer:
        conn.close()
    return result


def balance_par_classe(exercice_id: int, conn: Optional[sqlite3.Connection] = None) -> dict[int, list[dict]]:
    """Balance regroupée par classe de compte (1 à 7)."""
    balance = balance_generale(exercice_id, conn=conn)
    par_classe = defaultdict(list)
    for ligne in balance:
        classe = int(ligne["compte"][0])
        par_classe[classe].append(ligne)
    return dict(sorted(par_classe.items()))


def compte_resultat(
    exercice_id: int,
    date_fin: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Compte de résultat simplifié.
    Total charges (classe 6) et total produits (classe 7) → résultat net.
    """
    balance = balance_generale(exercice_id, date_fin, conn=conn)

    charges = [l for l in balance if l["compte"].startswith("6")]
    produits = [l for l in balance if l["compte"].startswith("7")]

    total_charges = sum(l["solde_debit"] for l in charges)
    total_produits = sum(l["solde_credit"] for l in produits)
    resultat_net = round(total_produits - total_charges, 2)

    return {
        "charges": charges,
        "total_charges": round(total_charges, 2),
        "produits": produits,
        "total_produits": round(total_produits, 2),
        "resultat_net": resultat_net,
        "benefice": resultat_net > 0,
    }


def bilan_synthetique(
    exercice_id: int,
    date_fin: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Bilan synthétique actif/passif.
    Actif = classes 2+3+4(débiteurs)+5 (emplois)
    Passif = classes 1+4(créditeurs) (ressources)
    Inclut le résultat de l'exercice au passif.
    """
    balance = balance_generale(exercice_id, date_fin, conn=conn)
    cr = compte_resultat(exercice_id, date_fin, conn=conn)

    actif = []
    passif_lines = []
    total_actif = 0.0
    total_passif = 0.0

    for l in balance:
        compte = l["compte"]
        solde_d = l["solde_debit"]
        solde_c = l["solde_credit"]

        if compte.startswith(("2", "3", "5")):
            if solde_d > 0:
                actif.append({**l, "poste": "actif"})
                total_actif += solde_d
            if solde_c > 0:
                passif_lines.append({**l, "poste": "passif"})
                total_passif += solde_c

        elif compte.startswith("4"):
            if solde_d > 0:
                actif.append({**l, "poste": "actif"})
                total_actif += solde_d
            if solde_c > 0:
                passif_lines.append({**l, "poste": "passif"})
                total_passif += solde_c

        elif compte.startswith("1"):
            if solde_d > 0:
                actif.append({**l, "poste": "actif"})
                total_actif += solde_d
            if solde_c > 0:
                passif_lines.append({**l, "poste": "passif"})
                total_passif += solde_c

    # Résultat de l'exercice au passif (bénéfice) ou actif (perte)
    if cr["benefice"]:
        passif_lines.append({
            "compte": "120",
            "total_debit": 0,
            "total_credit": cr["resultat_net"],
            "solde_debit": 0,
            "solde_credit": cr["resultat_net"],
            "poste": "passif",
            "libelle": "Résultat de l'exercice (bénéfice)",
        })
        total_passif += cr["resultat_net"]
    elif cr["resultat_net"] < 0:
        actif.append({
            "compte": "129",
            "total_debit": abs(cr["resultat_net"]),
            "total_credit": 0,
            "solde_debit": abs(cr["resultat_net"]),
            "solde_credit": 0,
            "poste": "actif",
            "libelle": "Résultat de l'exercice (perte)",
        })
        total_actif += abs(cr["resultat_net"])

    return {
        "actif": actif,
        "total_actif": round(total_actif, 2),
        "passif": passif_lines,
        "total_passif": round(total_passif, 2),
        "equilibre": abs(total_actif - total_passif) < 0.01,
    }
