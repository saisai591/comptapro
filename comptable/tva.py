"""
TVA : calcul des déclarations CA3/CA12 depuis les écritures comptables.
Stdlib uniquement.
"""

import sqlite3
from datetime import date, datetime
from typing import Optional

from .db import get_db


TAUX_MAPPING = {
    20.0: "taux_20",
    10.0: "taux_10",
    5.5:  "taux_5_5",
    0.0:  "taux_0",
}
TAUX_VALEURS = {20.0, 10.0, 5.5, 0.0}


def _estimer_taux(compte_tva: str, base_ht: float, montant_tva: float) -> float:
    """Estime le taux de TVA depuis le ratio TVA/HT."""
    if base_ht == 0 or montant_tva == 0:
        return 0.0
    ratio = abs(montant_tva / base_ht)
    # Cherche le taux le plus proche
    taux_possibles = sorted(TAUX_VALEURS, key=lambda t: abs(t / 100 - ratio))
    return taux_possibles[0]


def calculer_tva_periode(
    exercice_id: int,
    date_debut: str,
    date_fin: str,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Calcule la TVA due sur une période donnée.
    Parcourt les comptes 4457 (TVA collectée) et 4456 (TVA déductible).
    Estime le taux par ratio TVA/HT.
    Retourne {taux_20, taux_10, taux_5_5, taux_0, total_tva_due}.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    # TVA collectée (4457xx) : lignes au crédit = TVA due sur ventes
    tva_collectee_rows = conn.execute(
        """SELECT l.compte, SUM(l.credit - l.debit) as montant
           FROM lignes_ecriture l
           JOIN ecritures e ON e.id = l.ecriture_id
           WHERE e.exercice_id = ? AND e.date BETWEEN ? AND ?
           AND l.compte LIKE '4457%'
           GROUP BY l.compte""",
        (exercice_id, date_debut, date_fin),
    ).fetchall()

    # TVA déductible (4456xx) : lignes au débit = TVA récupérable sur achats
    tva_deductible_rows = conn.execute(
        """SELECT l.compte, SUM(l.debit - l.credit) as montant
           FROM lignes_ecriture l
           JOIN ecritures e ON e.id = l.ecriture_id
           WHERE e.exercice_id = ? AND e.date BETWEEN ? AND ?
           AND l.compte LIKE '4456%'
           GROUP BY l.compte""",
        (exercice_id, date_debut, date_fin),
    ).fetchall()

    # Base HT : comptes de produits (7xx) pour ventes, charges (6xx) pour achats
    # On estime le taux en cherchant les écritures avec TVA
    # Pour chaque écriture, on corrèle la ligne de TVA avec les lignes de charge/produit

    # Approche simplifiée : somme des TVA par compte, on devine le taux
    tva_collectee_par_taux = {}
    for row in tva_collectee_rows:
        compte = row["compte"]
        montant = row["montant"] or 0
        # 44571 = TVA 20%, 44572 = TVA 10%, etc. (convention PCG simplifiée)
        if "44571" in compte:
            tva_collectee_par_taux[20.0] = tva_collectee_par_taux.get(20.0, 0) + montant
        elif "44572" in compte:
            tva_collectee_par_taux[10.0] = tva_collectee_par_taux.get(10.0, 0) + montant
        elif "44573" in compte:
            tva_collectee_par_taux[5.5] = tva_collectee_par_taux.get(5.5, 0) + montant
        elif "44580" in compte:
            pass  # TVA sur encaissements, on met dans 20% par défaut
        else:
            tva_collectee_par_taux[20.0] = tva_collectee_par_taux.get(20.0, 0) + montant

    tva_deductible_par_taux = {}
    for row in tva_deductible_rows:
        compte = row["compte"]
        montant = row["montant"] or 0
        if "44561" in compte or "44566" in compte:
            tva_deductible_par_taux[20.0] = tva_deductible_par_taux.get(20.0, 0) + montant
        elif "44562" in compte:
            tva_deductible_par_taux[10.0] = tva_deductible_par_taux.get(10.0, 0) + montant
        elif "44563" in compte:
            tva_deductible_par_taux[5.5] = tva_deductible_par_taux.get(5.5, 0) + montant
        else:
            tva_deductible_par_taux[20.0] = tva_deductible_par_taux.get(20.0, 0) + montant

    # Base HT estimée depuis le taux
    result = {}
    total_tva_due = 0.0
    for taux in [20.0, 10.0, 5.5, 0.0]:
        collectee = round(tva_collectee_par_taux.get(taux, 0), 2)
        deductible = round(tva_deductible_par_taux.get(taux, 0), 2)
        base_ht = round(collectee * 100 / taux, 2) if taux > 0 and collectee != 0 else 0
        tva_nette = round(collectee - deductible, 2)
        key = TAUX_MAPPING.get(taux, f"taux_{taux}")
        result[key] = {
            "base_ht": base_ht,
            "tva_collectee": collectee,
            "tva_deductible": deductible,
            "tva_nette": tva_nette,
        }
        total_tva_due += tva_nette

    result["total_tva_due"] = round(total_tva_due, 2)

    if doit_fermer:
        conn.close()
    return result


def declaration_ca3(
    exercice_id: int,
    periode_debut: str,
    periode_fin: str,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Génère une déclaration CA3 au format structuré.
    """
    tva = calculer_tva_periode(exercice_id, periode_debut, periode_fin, conn=conn)

    ca_ht = sum(
        tva.get(t, {}).get("base_ht", 0)
        for t in ["taux_20", "taux_10", "taux_5_5", "taux_0"]
    )
    tva_collectee = sum(
        tva.get(t, {}).get("tva_collectee", 0)
        for t in ["taux_20", "taux_10", "taux_5_5", "taux_0"]
    )
    tva_deductible = sum(
        tva.get(t, {}).get("tva_deductible", 0)
        for t in ["taux_20", "taux_10", "taux_5_5", "taux_0"]
    )
    tva_due = tva_collectee - tva_deductible

    # Crédit TVA reporté (solde du compte 44567 ou 4458)
    doit_fermer = conn is None
    if doit_fermer:
        conn = get_db()
    credit_row = conn.execute(
        """SELECT COALESCE(SUM(debit - credit), 0) as credit_tva
           FROM lignes_ecriture l
           JOIN ecritures e ON e.id = l.ecriture_id
           WHERE e.exercice_id = ? AND e.date <= ?
           AND (l.compte = '44567' OR l.compte = '4458')""",
        (exercice_id, periode_fin),
    ).fetchone()
    credit_tva = max(0, credit_row["credit_tva"] or 0)

    tva_a_payer = max(0, tva_due - credit_tva)

    result = {
        "periode": f"{periode_debut} → {periode_fin}",
        "ca_ht_total": round(ca_ht, 2),
        "tva_collectee": round(tva_collectee, 2),
        "tva_deductible": round(tva_deductible, 2),
        "tva_due": round(tva_due, 2),
        "credit_tva_reporte": round(credit_tva, 2),
        "tva_a_payer": round(tva_a_payer, 2),
        "detail_taux": {k: v for k, v in tva.items() if k not in ("total_tva_due",)},
        "texte": _formater_texte_ca3(tva, credit_tva, tva_a_payer, periode_debut, periode_fin),
    }

    if doit_fermer:
        conn.close()
    return result


def _formater_texte_ca3(
    tva: dict,
    credit_tva: float,
    tva_a_payer: float,
    debut: str,
    fin: str,
) -> str:
    """Formate la déclaration CA3 en texte lisible."""
    lines = [
        "═" * 60,
        f"  DÉCLARATION CA3 — Période : {debut} → {fin}",
        "═" * 60,
        "",
        "  RUBRIQUE                          │ MONTANT (€)",
        "  ──────────────────────────────────┼─────────────",
    ]
    for taux, label in [(20.0, "TVA 20%"), (10.0, "TVA 10%"), (5.5, "TVA 5.5%"), (0.0, "TVA 0%")]:
        key = TAUX_MAPPING.get(taux, "")
        d = tva.get(key, {})
        if d.get("base_ht") or d.get("tva_collectee"):
            lines.append(f"  CA HT {label:<27s}│ {d.get('base_ht', 0):>10.2f}")
            lines.append(f"  TVA collectée {label:<20s}│ {d.get('tva_collectee', 0):>10.2f}")
            lines.append(f"  TVA déductible {label:<19s}│ {d.get('tva_deductible', 0):>10.2f}")
    lines.extend([
        "",
        f"  TVA DUE (avant crédit)            │ {tva.get('total_tva_due', 0):>10.2f}",
        f"  Crédit TVA reporté                 │ {credit_tva:>10.2f}",
        f"  ──────────────────────────────────┼─────────────",
        f"  TVA À PAYER                        │ {tva_a_payer:>10.2f}",
        "═" * 60,
    ])
    return "\n".join(lines)


def declaration_ca12(
    exercice_id: int,
    annee: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Cumul annuel pour la déclaration CA12."""
    return declaration_ca3(exercice_id, f"{annee}-01-01", f"{annee}-12-31", conn=conn)


def historique_tva(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """
    Historique des périodes de TVA : découpe l'exercice en trimestres/mois
    et calcule la TVA pour chaque période.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    # Récupère les dates de l'exercice
    ex = conn.execute(
        "SELECT date_debut, date_fin FROM exercices WHERE id = ?",
        (exercice_id,),
    ).fetchone()
    if not ex:
        if doit_fermer:
            conn.close()
        return []

    try:
        start = datetime.strptime(ex["date_debut"], "%Y-%m-%d")
        end = datetime.strptime(ex["date_fin"], "%Y-%m-%d")
    except (ValueError, TypeError):
        if doit_fermer:
            conn.close()
        return []

    # Découpe par mois
    from calendar import monthrange
    historique = []
    current = start
    while current <= end:
        fin_mois = current.replace(
            day=monthrange(current.year, current.month)[1]
        )
        periode_debut = current.strftime("%Y-%m-%d")
        periode_fin = min(fin_mois, end).strftime("%Y-%m-%d")

        tva = calculer_tva_periode(exercice_id, periode_debut, periode_fin, conn=conn)
        historique.append({
            "periode": f"{current.year}-{current.month:02d}",
            "debut": periode_debut,
            "fin": periode_fin,
            "tva_collectee": sum(
                tva.get(t, {}).get("tva_collectee", 0)
                for t in TAUX_MAPPING.values()
            ),
            "tva_deductible": sum(
                tva.get(t, {}).get("tva_deductible", 0)
                for t in TAUX_MAPPING.values()
            ),
            "tva_due": tva.get("total_tva_due", 0),
        })

        # Mois suivant
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    if doit_fermer:
        conn.close()
    return historique


def acomptes_tva(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """
    Calcule les acomptes de TVA (méthode simplifiée).
    80% de la TVA due N-1 / 4, ou estimation depuis le trimestre précédent.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    ex = conn.execute(
        "SELECT date_debut, date_fin FROM exercices WHERE id = ?",
        (exercice_id,),
    ).fetchone()
    if not ex:
        if doit_fermer:
            conn.close()
        return {"error": "Exercice introuvable"}

    try:
        start = datetime.strptime(ex["date_debut"], "%Y-%m-%d")
    except (ValueError, TypeError):
        if doit_fermer:
            conn.close()
        return {"error": "Date début invalide"}

    # On calcule la TVA due sur tout l'exercice, puis 80%
    tva_annuelle = calculer_tva_periode(
        exercice_id,
        ex["date_debut"],
        ex["date_fin"],
        conn=conn,
    )
    tva_due = tva_annuelle.get("total_tva_due", 0)
    acompte_trimestriel = tva_due * 0.8 / 4

    # Découpage en trimestres
    trimestres = []
    for t in range(4):
        debut = datetime(start.year, max(1, t * 3 + 1), 1)
        fin = datetime(start.year, min(12, t * 3 + 3), 1)
        # Dernier jour du mois fin
        from calendar import monthrange
        fin = fin.replace(day=monthrange(fin.year, fin.month)[1])
        trimestres.append({
            "trimestre": f"T{t + 1}",
            "periode": f"{debut.strftime('%Y-%m-%d')} → {fin.strftime('%Y-%m-%d')}",
            "acompte_estime": round(acompte_trimestriel, 2),
        })

    if doit_fermer:
        conn.close()

    return {
        "tva_annuelle_estimee": round(tva_due, 2),
        "pourcentage_acompte": 80,
        "acompte_trimestriel": round(acompte_trimestriel, 2),
        "trimestres": trimestres,
    }
