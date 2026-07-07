"""
Dashboard : KPIs, évolution CA, TVA, top clients/fournisseurs.
"""

import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional, Union

from .db import get_db


def kpi_tresorerie(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """KPIs de trésorerie : solde banque, créances clients, dettes fournisseurs, trésorerie nette."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    # Solde banque (comptes 512)
    solde = conn.execute(
        """SELECT SUM(l.credit) - SUM(l.debit) as solde
           FROM lignes_ecriture l
           JOIN ecritures e ON e.id = l.ecriture_id
           WHERE e.exercice_id = ? AND l.compte LIKE '51%'""",
        (exercice_id,),
    ).fetchone()
    solde_banque = round((solde["solde"] or 0) * -1, 2)  # inverser : crédit - débit → solde réel

    # Créances clients (411)
    clients = conn.execute(
        """SELECT SUM(l.debit) - SUM(l.credit) as solde
           FROM lignes_ecriture l
           JOIN ecritures e ON e.id = l.ecriture_id
           WHERE e.exercice_id = ? AND l.compte LIKE '41%'""",
        (exercice_id,),
    ).fetchone()
    creances_clients = max(round(clients["solde"] or 0, 2), 0)

    # Dettes fournisseurs (401)
    fournisseurs = conn.execute(
        """SELECT SUM(l.credit) - SUM(l.debit) as solde
           FROM lignes_ecriture l
           JOIN ecritures e ON e.id = l.ecriture_id
           WHERE e.exercice_id = ? AND l.compte LIKE '40%'""",
        (exercice_id,),
    ).fetchone()
    dettes_fournisseurs = max(round(fournisseurs["solde"] or 0, 2), 0)

    treso_nette = round(solde_banque + creances_clients - dettes_fournisseurs, 2)

    # Factures en retard
    fact_retard = conn.execute(
        """SELECT COUNT(*) as nb FROM factures
           WHERE exercice_id = ? AND statut = 'en_retard'""",
        (exercice_id,),
    ).fetchone()

    # Lignes non rapprochées
    non_rapp = conn.execute(
        """SELECT COUNT(*) as nb FROM lignes_releve lr
           JOIN releves_bancaires rb ON rb.id = lr.releve_id
           WHERE rb.exercice_id = ? AND lr.rapproche = 0""",
        (exercice_id,),
    ).fetchone()

    if doit_fermer:
        conn.close()

    return {
        "solde_banque": solde_banque,
        "creances_clients": creances_clients,
        "dettes_fournisseurs": dettes_fournisseurs,
        "treso_nette": treso_nette,
        "factures_retard": fact_retard["nb"] or 0 if fact_retard else 0,
        "non_rapprochees": non_rapp["nb"] or 0 if non_rapp else 0,
    }


def evolution_ca(
    exercice_id: int,
    nb_mois: int = 6,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Évolution mensuelle charges/produits/résultat sur les derniers mois."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    result = []
    aujourdhui = date.today()

    for i in range(nb_mois - 1, -1, -1):
        debut = (aujourdhui.replace(day=1) - timedelta(days=i * 31)).replace(day=1)
        if i == 0:
            fin = aujourdhui
        else:
            if debut.month == 12:
                fin = debut.replace(year=debut.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                fin = debut.replace(month=debut.month + 1, day=1) - timedelta(days=1)

        debut_str = debut.strftime("%Y-%m-%d")
        fin_str = fin.strftime("%Y-%m-%d")

        charges = conn.execute(
            """SELECT SUM(l.debit) - SUM(l.credit) as total
               FROM lignes_ecriture l
               JOIN ecritures e ON e.id = l.ecriture_id
               WHERE e.exercice_id = ? AND l.compte LIKE '6%'
               AND e.date >= ? AND e.date <= ?""",
            (exercice_id, debut_str, fin_str),
        ).fetchone()

        produits = conn.execute(
            """SELECT SUM(l.credit) - SUM(l.debit) as total
               FROM lignes_ecriture l
               JOIN ecritures e ON e.id = l.ecriture_id
               WHERE e.exercice_id = ? AND l.compte LIKE '7%'
               AND e.date >= ? AND e.date <= ?""",
            (exercice_id, debut_str, fin_str),
        ).fetchone()

        ch = round(charges["total"] or 0, 2)
        pr = round(produits["total"] or 0, 2)
        result.append({
            "mois": debut.strftime("%B %Y").capitalize(),
            "charges": ch,
            "produits": pr,
            "resultat": round(pr - ch, 2),
        })

    if doit_fermer:
        conn.close()
    return result


def tva_preview(
    exercice_id: int,
    date_fin: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Calcule la TVA collectée, déductible et à payer."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    params = [exercice_id]
    extra = ""
    if date_fin:
        extra = " AND e.date <= ?"
        params.append(date_fin)

    collectee = conn.execute(
        f"""SELECT SUM(l.credit) - SUM(l.debit) as total
            FROM lignes_ecriture l
            JOIN ecritures e ON e.id = l.ecriture_id
            WHERE e.exercice_id = ? AND l.compte = '4457'{extra}""",
        params,
    ).fetchone()

    deductible = conn.execute(
        f"""SELECT SUM(l.debit) - SUM(l.credit) as total
            FROM lignes_ecriture l
            JOIN ecritures e ON e.id = l.ecriture_id
            WHERE e.exercice_id = ? AND l.compte = '4456'{extra}""",
        params,
    ).fetchone()

    coll = max(round(collectee["total"] or 0, 2), 0)
    ded = max(round(deductible["total"] or 0, 2), 0)

    if doit_fermer:
        conn.close()

    return {
        "collectee": coll,
        "deductible": ded,
        "a_payer": round(coll - ded, 2),
    }


def top_clients(
    exercice_id: int,
    limite: int = 5,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Top clients par CA (compte 706, 707, 708 au crédit, croisé avec 411)."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    # Approche simplifiée : total produits (classe 7) par écriture
    rows = conn.execute(
        """SELECT e.libelle, SUM(l.credit) as ca
           FROM lignes_ecriture l
           JOIN ecritures e ON e.id = l.ecriture_id
           WHERE e.exercice_id = ? AND l.compte LIKE '7%'
             AND l.credit > 0
           GROUP BY e.libelle
           ORDER BY ca DESC
           LIMIT ?""",
        (exercice_id, limite),
    ).fetchall()

    if doit_fermer:
        conn.close()

    return [{"client": r["libelle"][:40], "ca": round(r["ca"] or 0, 2)} for r in rows]


def top_fournisseurs(
    exercice_id: int,
    limite: int = 5,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Top fournisseurs par montant acheté."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    rows = conn.execute(
        """SELECT e.libelle, SUM(l.debit) as montant
           FROM lignes_ecriture l
           JOIN ecritures e ON e.id = l.ecriture_id
           WHERE e.exercice_id = ? AND l.compte LIKE '6%'
             AND l.debit > 0
           GROUP BY e.libelle
           ORDER BY montant DESC
           LIMIT ?""",
        (exercice_id, limite),
    ).fetchall()

    if doit_fermer:
        conn.close()

    return [{"fournisseur": r["libelle"][:40], "montant": round(r["montant"] or 0, 2)} for r in rows]


def resume_jour(exercice_id: int, conn: Optional[sqlite3.Connection] = None) -> dict:
    """Résumé du jour : nb écritures, total débit/crédit."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    today = date.today().isoformat()
    nb = conn.execute(
        "SELECT COUNT(*) as c FROM ecritures WHERE exercice_id = ? AND date = ?",
        (exercice_id, today),
    ).fetchone()

    totals = conn.execute(
        """SELECT SUM(l.debit) as td, SUM(l.credit) as tc
           FROM lignes_ecriture l
           JOIN ecritures e ON e.id = l.ecriture_id
           WHERE e.exercice_id = ? AND e.date = ?""",
        (exercice_id, today),
    ).fetchone()

    if doit_fermer:
        conn.close()

    return {
        "date": today,
        "nb_ecritures": nb["c"] if nb else 0,
        "total_debit": round(totals["td"] or 0, 2) if totals else 0,
        "total_credit": round(totals["tc"] or 0, 2) if totals else 0,
    }
