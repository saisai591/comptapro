"""
Clôture d'exercice assistée.
Vérifications pré-clôture, génération d'à-nouveaux, clôture, réouverture.
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from .db import get_db
from .ecritures import saisir_ecriture


def verifications_cloture(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Checklist pré-clôture :
    partie double, journaux équilibrés, écritures non lettrées,
    comptes tiers à soldes anormaux, suggestions d'écritures.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    # 1. Partie double sur toutes les écritures
    deseq = conn.execute(
        """
        SELECT e.id, e.libelle, e.date,
               SUM(le.debit) AS total_debit,
               SUM(le.credit) AS total_credit
        FROM ecritures e
        JOIN lignes_ecriture le ON le.ecriture_id = e.id
        WHERE e.exercice_id = ?
        GROUP BY e.id
        HAVING ABS(SUM(le.debit) - SUM(le.credit)) > 0.005
        """,
        (exercice_id,),
    ).fetchall()
    partie_double_ok = len(deseq) == 0

    # 2. Journaux équilibrés
    jrn_deseq = conn.execute(
        """
        SELECT e.journal,
               SUM(le.debit) AS total_debit,
               SUM(le.credit) AS total_credit
        FROM ecritures e
        JOIN lignes_ecriture le ON le.ecriture_id = e.id
        WHERE e.exercice_id = ?
        GROUP BY e.journal
        HAVING ABS(SUM(le.debit) - SUM(le.credit)) > 0.005
        """,
        (exercice_id,),
    ).fetchall()
    tous_journaux_equilibres = len(jrn_deseq) == 0

    # 3. Écritures non lettrées (comptes 401, 411)
    nb_non_lettrees = conn.execute(
        """
        SELECT COUNT(DISTINCT le.ecriture_id) AS n
        FROM lignes_ecriture le
        JOIN ecritures e ON e.id = le.ecriture_id
        WHERE e.exercice_id = ?
          AND (le.compte LIKE '401%' OR le.compte LIKE '411%')
          AND le.ecriture_id NOT IN (
              SELECT DISTINCT ll.ecriture_id FROM lignes_lettrage ll
          )
        """,
        (exercice_id,),
    ).fetchone()["n"]

    # 4. Comptes tiers avec soldes non nuls
    soldes_anormaux = conn.execute(
        """
        SELECT le.compte, ca.nom,
               SUM(le.debit) AS total_debit,
               SUM(le.credit) AS total_credit,
               SUM(le.debit) - SUM(le.credit) AS solde
        FROM lignes_ecriture le
        JOIN ecritures e ON e.id = le.ecriture_id
        LEFT JOIN comptes_aux ca ON le.auxiliaire_id = ca.id
        WHERE e.exercice_id = ?
          AND (le.compte LIKE '401%' OR le.compte LIKE '411%')
        GROUP BY le.compte, ca.nom
        HAVING solde != 0
        """,
        (exercice_id,),
    ).fetchall()

    comptes_anormaux = [
        {
            "compte": s["compte"],
            "nom": s["nom"] or "",
            "solde": round(s["solde"], 2),
        }
        for s in soldes_anormaux
    ]

    # 5. Suggestions d'écritures de clôture
    suggestions = _suggerer_ecritures_cloture(conn, exercice_id)

    if doit_fermer:
        conn.close()

    return {
        "partie_double_ok": partie_double_ok,
        "ecritures_desequilibrees": [dict(e) for e in deseq],
        "tous_journaux_equilibres": tous_journaux_equilibres,
        "journaux_desequilibres": [dict(j) for j in jrn_deseq],
        "nb_ecritures_non_lettrees": nb_non_lettrees,
        "comptes_tiers_soldes_anormaux": comptes_anormaux,
        "suggestion_ecritures": suggestions,
    }


def _suggerer_ecritures_cloture(
    conn: sqlite3.Connection,
    exercice_id: int,
) -> list[dict]:
    """Suggère les écritures de clôture nécessaires (provisions, amortissements)."""
    suggestions = []

    # Provisions pour créances douteuses (factures > 365j non payées)
    anciens = conn.execute(
        """
        SELECT f.id, f.client_nom, f.total_ttc, f.date
        FROM factures f
        WHERE f.exercice_id = ?
          AND f.statut IN ('envoyee', 'en_retard')
          AND f.type = 'facture'
          AND julianday(date('now')) - julianday(f.date) > 365
        """,
        (exercice_id,),
    ).fetchall()

    for a in anciens:
        suggestions.append({
            "type": "provision",
            "libelle": f"Dépréciation créance {a['client_nom']} du {a['date']}",
            "lignes": [
                {
                    "compte": "6817",
                    "libelle": "Dotation dépréciation actif circulant",
                    "debit": a["total_ttc"],
                    "credit": 0,
                },
                {
                    "compte": "491",
                    "libelle": "Dépréciation comptes clients",
                    "debit": 0,
                    "credit": a["total_ttc"],
                },
            ],
        })

    # Rappel amortissements
    has_28 = conn.execute(
        """
        SELECT COUNT(*) AS n FROM lignes_ecriture le
        JOIN ecritures e ON e.id = le.ecriture_id
        WHERE e.exercice_id = ? AND le.compte LIKE '28%'
        """,
        (exercice_id,),
    ).fetchone()["n"]

    if has_28 == 0:
        suggestions.append({
            "type": "info",
            "libelle": "Pensez à calculer les dotations aux amortissements (6811/28...)",
            "lignes": [],
        })

    return suggestions


def generer_anouveaux(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Génère les écritures d'à-nouveaux dans l'exercice suivant.
    Comptes de bilan (1-5) : reprise du solde.
    Comptes de gestion (6-7) : solde → compte 120 (résultat).
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    ex_actuel = conn.execute(
        "SELECT * FROM exercices WHERE id = ?", (exercice_id,)
    ).fetchone()
    if not ex_actuel:
        raise ValueError(f"Exercice {exercice_id} introuvable")

    date_fin = ex_actuel["date_fin"]
    date_fin_dt = datetime.strptime(date_fin, "%Y-%m-%d")
    date_debut_suivant = (date_fin_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    date_fin_suivant = (date_fin_dt + timedelta(days=365)).strftime("%Y-%m-%d")
    libelle_suivant = f"{ex_actuel['libelle']} (N+1)"

    # Créer ou récupérer l'exercice suivant
    ex_suivant = conn.execute(
        "SELECT * FROM exercices WHERE libelle = ? AND date_debut = ?",
        (libelle_suivant, date_debut_suivant),
    ).fetchone()

    if not ex_suivant:
        conn.execute(
            "INSERT INTO exercices (libelle, date_debut, date_fin) VALUES (?, ?, ?)",
            (libelle_suivant, date_debut_suivant, date_fin_suivant),
        )
        conn.commit()
        ex_suivant_id = conn.execute(
            "SELECT id FROM exercices WHERE libelle = ? AND date_debut = ?",
            (libelle_suivant, date_debut_suivant),
        ).fetchone()["id"]
    else:
        ex_suivant_id = ex_suivant["id"]

    # Calculer les soldes par compte
    soldes = conn.execute(
        """
        SELECT le.compte,
               SUM(le.debit) AS total_debit,
               SUM(le.credit) AS total_credit
        FROM lignes_ecriture le
        JOIN ecritures e ON e.id = le.ecriture_id
        WHERE e.exercice_id = ?
        GROUP BY le.compte
        ORDER BY le.compte
        """,
        (exercice_id,),
    ).fetchall()

    lignes_anouv = []
    resultat = 0.0

    for s in soldes:
        solde = round(s["total_debit"] - s["total_credit"], 2)
        if abs(solde) < 0.005:
            continue

        compte = s["compte"]
        classe = compte[0] if compte else ""

        if classe in ("1", "2", "3", "4", "5"):
            if solde > 0:
                lignes_anouv.append({
                    "compte": compte,
                    "debit": solde,
                    "credit": 0,
                    "libelle": f"À-nouveau {compte}",
                })
            else:
                lignes_anouv.append({
                    "compte": compte,
                    "debit": 0,
                    "credit": -solde,
                    "libelle": f"À-nouveau {compte}",
                })
        elif classe in ("6", "7"):
            # Comptes de gestion → résultat
            # Classe 6 = charge (débit > crédit → perte)
            # Classe 7 = produit (crédit > débit → gain)
            resultat += solde

    # Ajouter le résultat en compte 120
    if abs(resultat) >= 0.005:
        if resultat > 0:
            # Bénéfice : 120 créditeur
            lignes_anouv.append({
                "compte": "120",
                "debit": 0,
                "credit": resultat,
                "libelle": "À-nouveau — Résultat (bénéfice)",
            })
        else:
            # Perte : 120 débiteur
            lignes_anouv.append({
                "compte": "120",
                "debit": -resultat,
                "credit": 0,
                "libelle": "À-nouveau — Résultat (perte)",
            })

    nb_ecritures = 0
    ecart = 0.0
    if lignes_anouv:
        total_d = round(sum(l["debit"] for l in lignes_anouv), 2)
        total_c = round(sum(l["credit"] for l in lignes_anouv), 2)
        ecart = round(total_d - total_c, 2)

        # Équilibrer si nécessaire
        if abs(ecart) > 0.005:
            if ecart > 0:
                lignes_anouv.append({
                    "compte": "120",
                    "debit": 0,
                    "credit": ecart,
                    "libelle": "Équilibrage à-nouveaux",
                })
            else:
                lignes_anouv.append({
                    "compte": "120",
                    "debit": -ecart,
                    "credit": 0,
                    "libelle": "Équilibrage à-nouveaux",
                })

        saisir_ecriture(
            ex_suivant_id, "ANOUV", date_debut_suivant,
            f"À-nouveaux — exercice {exercice_id}",
            lignes_anouv,
            conn=conn,
        )
        nb_ecritures = 1

    detail = [
        {
            "compte": s["compte"],
            "solde_debit": round(s["total_debit"], 2),
            "solde_credit": round(s["total_credit"], 2),
        }
        for s in soldes
        if abs(round(s["total_debit"] - s["total_credit"], 2)) >= 0.005
    ]

    if doit_fermer:
        conn.close()

    return {
        "nb_ecritures": nb_ecritures,
        "exercice_suivant_id": ex_suivant_id,
        "detail": detail,
        "resultat": round(resultat, 2),
        "ecart_equilibrage": round(ecart, 2),
    }


def cloturer_exercice(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Vérifications + à-nouveaux + marquage clôture. Rapport complet."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    verifs = verifications_cloture(exercice_id, conn=conn)

    if not verifs["partie_double_ok"]:
        if doit_fermer:
            conn.close()
        return {
            "ok": False,
            "error": "Partie double non équilibrée sur certaines écritures. "
                     "Corrigez avant de clôturer.",
            "verifications": verifs,
        }

    # Générer les à-nouveaux
    anouv = generer_anouveaux(exercice_id, conn=conn)

    # Marquer comme clôturé
    conn.execute(
        "UPDATE exercices SET cloture = 1 WHERE id = ?", (exercice_id,)
    )
    conn.commit()

    if doit_fermer:
        conn.close()

    return {
        "ok": True,
        "exercice_id": exercice_id,
        "cloture": True,
        "verifications": verifs,
        "a_nouveaux": anouv,
    }


def simuler_cloture(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Simule la clôture : rapport de ce qui serait fait, sans rien modifier."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    verifs = verifications_cloture(exercice_id, conn=conn)

    # Compter ce qui serait repris sans créer
    soldes = conn.execute(
        """
        SELECT le.compte,
               SUM(le.debit) AS total_debit,
               SUM(le.credit) AS total_credit
        FROM lignes_ecriture le
        JOIN ecritures e ON e.id = le.ecriture_id
        WHERE e.exercice_id = ?
        GROUP BY le.compte
        ORDER BY le.compte
        """,
        (exercice_id,),
    ).fetchall()

    nb_bilan = 0
    nb_gestion = 0
    total_bilan = 0.0

    for s in soldes:
        solde = round(s["total_debit"] - s["total_credit"], 2)
        if abs(solde) < 0.005:
            continue
        classe = s["compte"][0] if s["compte"] else ""
        if classe in ("1", "2", "3", "4", "5"):
            nb_bilan += 1
            total_bilan += abs(solde)
        elif classe in ("6", "7"):
            nb_gestion += 1

    if doit_fermer:
        conn.close()

    return {
        "exercice_id": exercice_id,
        "peut_cloturer": verifs["partie_double_ok"],
        "verifications": verifs,
        "resume_a_nouveaux": {
            "nb_comptes_bilan": nb_bilan,
            "nb_comptes_gestion": nb_gestion,
            "total_mouvements_bilan": round(total_bilan, 2),
        },
    }


def reouvrir_exercice(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Annule la clôture : réouvre l'exercice, supprime les ANOUV associés."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    ex = conn.execute(
        "SELECT * FROM exercices WHERE id = ?", (exercice_id,)
    ).fetchone()
    if not ex:
        raise ValueError(f"Exercice {exercice_id} introuvable")
    if not ex["cloture"]:
        raise ValueError(f"Exercice {exercice_id} n'est pas clôturé")

    # Supprimer les ANOUV dans l'exercice suivant
    date_fin_dt = datetime.strptime(ex["date_fin"], "%Y-%m-%d")
    date_debut_suivant = (date_fin_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    libelle_suivant = f"{ex['libelle']} (N+1)"

    ex_suivant = conn.execute(
        "SELECT id FROM exercices WHERE libelle = ? AND date_debut = ?",
        (libelle_suivant, date_debut_suivant),
    ).fetchone()

    if ex_suivant:
        ex_suiv_id = ex_suivant["id"]
        anouv_ids = conn.execute(
            "SELECT id FROM ecritures WHERE exercice_id = ? AND journal = 'ANOUV'",
            (ex_suiv_id,),
        ).fetchall()
        for a in anouv_ids:
            conn.execute(
                "DELETE FROM lignes_ecriture WHERE ecriture_id = ?", (a["id"],)
            )
            conn.execute("DELETE FROM ecritures WHERE id = ?", (a["id"],))

    # Réouvrir
    conn.execute(
        "UPDATE exercices SET cloture = 0 WHERE id = ?", (exercice_id,)
    )
    conn.commit()

    if doit_fermer:
        conn.close()
