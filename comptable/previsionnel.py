"""
Prévisionnel de trésorerie : projections, runway, alertes.
Stdlib uniquement.
"""

import sqlite3
from datetime import date, datetime
from typing import Optional

from .db import get_db


def ajouter_prevision(
    exercice_id: int,
    mois: int,
    categorie: str,
    compte: str,
    libelle: str,
    montant: float,
    probabilite: float = 1.0,
    recurrence: str = "ponctuel",
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Ajoute une prévision de trésorerie et retourne son ID."""
    if categorie not in ("encaissement", "decaissement"):
        raise ValueError("categorie doit être 'encaissement' ou 'decaissement'")
    if not (1 <= mois <= 12):
        raise ValueError("mois doit être entre 1 et 12")
    if recurrence not in ("ponctuel", "mensuel", "trimestriel"):
        raise ValueError("recurrence doit être 'ponctuel', 'mensuel' ou 'trimestriel'")

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    cur = conn.execute(
        """INSERT INTO previsions
           (exercice_id, mois, categorie, compte, libelle, montant, probabilite, recurrence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (exercice_id, mois, categorie, compte, libelle, montant, probabilite, recurrence),
    )
    pid = cur.lastrowid

    if doit_fermer:
        conn.commit()
        conn.close()
    return pid


def lister_previsions(
    exercice_id: int,
    mois: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Liste les prévisions, filtrées par mois si spécifié."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    query = "SELECT * FROM previsions WHERE exercice_id = ?"
    params = [exercice_id]
    if mois is not None:
        query += " AND mois = ?"
        params.append(mois)
    query += " ORDER BY mois, categorie, libelle"

    rows = conn.execute(query, params).fetchall()

    if doit_fermer:
        conn.close()
    return [dict(r) for r in rows]


def supprimer_prevision(
    id: int,
    conn: Optional[sqlite3.Connection] = None,
):
    """Supprime une prévision par ID."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    conn.execute("DELETE FROM previsions WHERE id = ?", (id,))

    if doit_fermer:
        conn.commit()
        conn.close()


def projection_tresorerie(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """
    Projette la trésorerie mois par mois.
    Inclut les prévisions + les factures non payées avec échéance dans le mois.
    Retourne [{mois, solde_initial, encaissements, decaissements, solde_final,
               encaissements_det, decaissements_det}].
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    # Solde bancaire actuel (somme des comptes 512*)
    solde_actuel_row = conn.execute(
        """SELECT COALESCE(SUM(debit - credit), 0) as solde
           FROM lignes_ecriture l
           JOIN ecritures e ON e.id = l.ecriture_id
           WHERE e.exercice_id = ? AND l.compte LIKE '512%'""",
        (exercice_id,),
    ).fetchone()
    solde_initial = round(solde_actuel_row["solde"] or 0, 2)

    # Prévisions groupées par mois
    previsions = conn.execute(
        """SELECT mois, categorie, compte, libelle, montant, probabilite, recurrence
           FROM previsions
           WHERE exercice_id = ?
           ORDER BY mois""",
        (exercice_id,),
    ).fetchall()

    # Factures clients non payées (encaissements futurs)
    factures_client = conn.execute(
        """SELECT f.id, f.numero, f.client_nom, f.total_ttc, f.echeance, f.statut
           FROM factures f
           WHERE f.exercice_id = ? AND f.type = 'facture'
           AND f.statut IN ('envoyee', 'en_retard')
           AND f.ecriture_id IS NULL""",
        (exercice_id,),
    ).fetchall()

    # Achats validés non payés (décaissements futurs) — si table existe
    achats_valides = []
    try:
        achats_valides = conn.execute(
            """SELECT id, fournisseur, description, montant_ttc, date_facture, numero_facture
               FROM validations_achat
               WHERE exercice_id = ? AND statut = 'valide'
               ORDER BY date_facture""",
            (exercice_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        pass  # Table pas encore créée

    # Construire la projection mois par mois
    result = []
    solde = solde_initial

    for mois in range(1, 13):
        encaissements = 0.0
        decaissements = 0.0
        encaissements_det = []
        decaissements_det = []

        # Prévisions pour ce mois
        for p in previsions:
            pmois = p["mois"]
            if p["recurrence"] == "mensuel" and pmois <= mois:
                pass  # tombe tous les mois
            elif p["recurrence"] == "trimestriel" and pmois <= mois and (mois - pmois) % 3 == 0:
                pass
            elif p["recurrence"] == "ponctuel" and pmois != mois:
                continue
            montant_pondere = p["montant"] * p["probabilite"]
            if p["categorie"] == "encaissement":
                encaissements += montant_pondere
                encaissements_det.append({
                    "libelle": p["libelle"],
                    "compte": p["compte"],
                    "montant": p["montant"],
                    "probabilite": p["probabilite"],
                })
            else:
                decaissements += montant_pondere
                decaissements_det.append({
                    "libelle": p["libelle"],
                    "compte": p["compte"],
                    "montant": p["montant"],
                    "probabilite": p["probabilite"],
                })

        # Factures clients échéant ce mois
        for f in factures_client:
            if f["echeance"]:
                try:
                    fdate = datetime.strptime(f["echeance"], "%Y-%m-%d")
                    if fdate.month == mois:
                        encaissements += f["total_ttc"]
                        encaissements_det.append({
                            "type": "facture",
                            "libelle": f"Facture {f['numero']} — {f['client_nom']}",
                            "montant": f["total_ttc"],
                            "probabilite": 1.0,
                        })
                except (ValueError, TypeError):
                    pass

        # Achats validés ce mois (échéance approximée = date facture + 30j)
        for a in achats_valides:
            try:
                adate = datetime.strptime(a["date_facture"], "%Y-%m-%d")
                echeance_mois = ((adate.month + 1) % 12) or 12  # +30 jours approx
                if echeance_mois == mois:
                    decaissements += a["montant_ttc"]
                    decaissements_det.append({
                        "type": "achat_valide",
                        "libelle": f"Achat {a['numero_facture'] or ''} — {a['fournisseur']}",
                        "montant": a["montant_ttc"],
                        "probabilite": 1.0,
                    })
            except (ValueError, TypeError):
                pass

        solde_final = round(solde + encaissements - decaissements, 2)

        result.append({
            "mois": mois,
            "solde_initial": round(solde, 2),
            "encaissements": round(encaissements, 2),
            "decaissements": round(decaissements, 2),
            "solde_final": solde_final,
            "encaissements_det": encaissements_det,
            "decaissements_det": decaissements_det,
        })

        solde = solde_final

    if doit_fermer:
        conn.close()
    return result


def runway(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    Retourne le nombre de mois avant trésorerie épuisée (scénario pessimiste).
    Le scénario pessimiste pondère les encaissements à 0.5 et les décaissements à 1.0.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    # Solde actuel
    solde_row = conn.execute(
        """SELECT COALESCE(SUM(debit - credit), 0) as solde
           FROM lignes_ecriture l
           JOIN ecritures e ON e.id = l.ecriture_id
           WHERE e.exercice_id = ? AND l.compte LIKE '512%'""",
        (exercice_id,),
    ).fetchone()
    solde = solde_row["solde"] or 0

    # Prévisions pessimistes
    for mois in range(1, 13):
        encaissements = conn.execute(
            """SELECT COALESCE(SUM(montant * 0.5), 0)
               FROM previsions
               WHERE exercice_id = ? AND mois = ? AND categorie = 'encaissement'""",
            (exercice_id, mois),
        ).fetchone()[0]

        decaissements = conn.execute(
            """SELECT COALESCE(SUM(montant * probabilite), 0)
               FROM previsions
               WHERE exercice_id = ? AND mois = ? AND categorie = 'decaissement'""",
            (exercice_id, mois),
        ).fetchone()[0]

        # Factures client (pessimiste: 50% de recouvrement)
        fact_enc_mois = conn.execute(
            """SELECT COALESCE(SUM(total_ttc * 0.5), 0)
               FROM factures
               WHERE exercice_id = ? AND type = 'facture'
               AND statut IN ('envoyee', 'en_retard')
               AND echeance LIKE ?
               AND ecriture_id IS NULL""",
            (exercice_id, f"%-{mois:02d}-%"),
        ).fetchone()[0]

        # Achats validés (100% décaissés)
        achat_dec_mois = conn.execute(
            """SELECT COALESCE(SUM(montant_ttc), 0)
               FROM validations_achat
               WHERE exercice_id = ? AND statut = 'valide'""",
            (exercice_id,),
        ).fetchone()[0] / 12  # lissé sur 12 mois

        solde += encaissements + fact_enc_mois - decaissements - achat_dec_mois

        if solde <= 0:
            if doit_fermer:
                conn.close()
            return mois - 1  # mois avant épuisement (0 = déjà négatif)

    if doit_fermer:
        conn.close()
    return 12  # Survit toute l'année


def alertes_tresorerie(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """
    Retourne les alertes de trésorerie : mois où le solde passe sous un seuil.
    """
    projection = projection_tresorerie(exercice_id, conn=conn)
    alertes = []
    for p in projection:
        if p["solde_final"] < 0:
            alertes.append({"mois": p["mois"], "type": "negatif", "solde": p["solde_final"]})
        elif p["solde_final"] < 1000:  # seuil bas arbitraire à 1000€
            alertes.append({"mois": p["mois"], "type": "seuil_bas", "solde": p["solde_final"]})
    return alertes
