"""
Gestion des emprunts.
Stdlib uniquement. Pattern conn optionnel + doit_fermer.

Tables : emprunts, echeances_emprunt.
"""

import calendar
from datetime import datetime
from typing import Optional

from comptable.db import get_db


# ── CRUD emprunts ───────────────────────────────────────────────────

def ajouter_emprunt(
    exercice_id: int,
    designation: str,
    date_debut: str,
    montant: float,
    taux_annuel: float,
    duree_mois: int,
    periodicite: str = "mensuelle",
    type_amortissement: str = "constant",
    frais_dossier: float = 0.0,
    assurance: float = 0.0,
) -> int:
    """Ajoute un emprunt. Calcule date_fin automatiquement. Retourne l'id."""
    # Calcul date_fin
    dt = datetime.strptime(date_debut, "%Y-%m-%d")
    dt_fin = _ajouter_mois(dt, duree_mois)
    date_fin = dt_fin.strftime("%Y-%m-%d")

    conn = get_db()
    cur = conn.execute(
        """INSERT INTO emprunts
           (exercice_id, designation, date_debut, montant, taux_annuel,
            duree_mois, periodicite, type_amortissement, frais_dossier,
            assurance, date_fin)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (exercice_id, designation, date_debut, montant, taux_annuel,
         duree_mois, periodicite, type_amortissement, frais_dossier,
         assurance, date_fin),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def lister_emprunts(exercice_id: int, actif: Optional[bool] = None) -> list[dict]:
    """Liste les emprunts, filtrable par actif."""
    conn = get_db()
    q = "SELECT * FROM emprunts WHERE exercice_id = ?"
    params = [exercice_id]
    if actif is not None:
        q += " AND actif = ?"
        params.append(1 if actif else 0)
    q += " ORDER BY date_debut DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Helpers ────────────────────────────────────────────────────────

def _ajouter_mois(dt: datetime, nb_mois: int) -> datetime:
    """Ajoute nb_mois mois à une date (stdlib uniquement)."""
    total_mois = dt.year * 12 + (dt.month - 1) + nb_mois
    annee = total_mois // 12
    mois = (total_mois % 12) + 1
    max_jour = calendar.monthrange(annee, mois)[1]
    jour = min(dt.day, max_jour)
    return dt.replace(year=annee, month=mois, day=jour)


# ── Tableau d'amortissement emprunt ─────────────────────────────────


def generer_tableau_amortissement(emprunt_id: int) -> list[dict]:
    """Calcule toutes les échéances et les stocke dans echeances_emprunt.
    - type 'constant' : capital constant, intérêts dégressifs
    - type 'annuite_constante' : annuité constante (formule PMT)
    Retourne le tableau complet.
    """
    conn = get_db()
    emp = conn.execute(
        "SELECT * FROM emprunts WHERE id = ?", (emprunt_id,)
    ).fetchone()
    if not emp:
        conn.close()
        raise ValueError(f"Emprunt {emprunt_id} introuvable")

    # Nettoyer les échéances existantes
    conn.execute("DELETE FROM echeances_emprunt WHERE emprunt_id = ?", (emprunt_id,))

    montant = emp["montant"]
    taux_annuel = emp["taux_annuel"]
    duree_mois = emp["duree_mois"]
    periodicite = emp["periodicite"]
    type_amort = emp["type_amortissement"]
    assurance_mensuelle = emp["assurance"] or 0

    date_debut = datetime.strptime(emp["date_debut"], "%Y-%m-%d")

    # Nombre d'échéances
    if periodicite == "trimestrielle":
        nb_echeances = duree_mois // 3
        pas_mois = 3
        # Taux périodique trimestriel
        tx_periodique = (taux_annuel / 100.0) * 3 / 12
        assurance_unitaire = assurance_mensuelle * 3
    else:
        nb_echeances = duree_mois
        pas_mois = 1
        tx_periodique = (taux_annuel / 100.0) / 12.0
        assurance_unitaire = assurance_mensuelle

    tableau = []
    capital_restant = montant

    if type_amort == "constant":
        # Amortissement constant du capital
        capital_par_echeance = round(montant / nb_echeances, 2)
        # Ajustement dernière échéance pour arrondis
        total_capital = 0.0

        for n in range(1, nb_echeances + 1):
            interets = round(capital_restant * tx_periodique, 2)
            if n == nb_echeances:
                capital_remb = round(montant - total_capital, 2)
            else:
                capital_remb = capital_par_echeance
            total_capital += capital_remb
            mensualite = round(capital_remb + interets + assurance_unitaire, 2)

            date_echeance = _ajouter_mois(date_debut, pas_mois * n)

            capital_restant_avant = round(capital_restant, 2)
            capital_restant = round(capital_restant - capital_remb, 2)

            conn.execute(
                """INSERT INTO echeances_emprunt
                   (emprunt_id, numero, date_echeance, capital_restant_avant,
                    mensualite, interets, capital_rembourse, assurance,
                    capital_restant_apres)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (emprunt_id, n, date_echeance.strftime("%Y-%m-%d"),
                 capital_restant_avant, mensualite, interets, capital_remb,
                 assurance_unitaire, capital_restant),
            )
            tableau.append({
                "numero": n,
                "date_echeance": date_echeance.strftime("%Y-%m-%d"),
                "capital_restant_avant": capital_restant_avant,
                "mensualite": mensualite,
                "interets": interets,
                "capital_rembourse": capital_remb,
                "assurance": assurance_unitaire,
                "capital_restant_apres": capital_restant,
            })

    elif type_amort == "annuite_constante":
        # Annuité constante = (C × t) / (1 - (1+t)^-n)
        if tx_periodique == 0:
            annuite = montant / nb_echeances
        else:
            annuite = (montant * tx_periodique) / (1 - (1 + tx_periodique) ** -nb_echeances)
        annuite = round(annuite, 2)

        total_capital = 0.0

        for n in range(1, nb_echeances + 1):
            interets = round(capital_restant * tx_periodique, 2)
            capital_remb = round(annuite - interets, 2)

            # Dernière échéance : ajuster pour arriver exactement à 0
            if n == nb_echeances:
                capital_remb = round(montant - total_capital, 2)
                annuite = round(capital_remb + interets + assurance_unitaire, 2)

            total_capital += capital_remb
            mensualite = round(capital_remb + interets + assurance_unitaire, 2)

            date_echeance = _ajouter_mois(date_debut, pas_mois * n)

            capital_restant_avant = round(capital_restant, 2)
            capital_restant = round(capital_restant - capital_remb, 2)

            conn.execute(
                """INSERT INTO echeances_emprunt
                   (emprunt_id, numero, date_echeance, capital_restant_avant,
                    mensualite, interets, capital_rembourse, assurance,
                    capital_restant_apres)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (emprunt_id, n, date_echeance.strftime("%Y-%m-%d"),
                 capital_restant_avant, mensualite, interets, capital_remb,
                 assurance_unitaire, capital_restant),
            )
            tableau.append({
                "numero": n,
                "date_echeance": date_echeance.strftime("%Y-%m-%d"),
                "capital_restant_avant": capital_restant_avant,
                "mensualite": mensualite,
                "interets": interets,
                "capital_rembourse": capital_remb,
                "assurance": assurance_unitaire,
                "capital_restant_apres": capital_restant,
            })

    conn.commit()
    conn.close()
    return tableau


def tableau_amortissement(emprunt_id: int) -> dict:
    """Lit les échéances déjà calculées pour un emprunt."""
    conn = get_db()
    emp = conn.execute(
        "SELECT * FROM emprunts WHERE id = ?", (emprunt_id,)
    ).fetchone()
    if not emp:
        conn.close()
        raise ValueError(f"Emprunt {emprunt_id} introuvable")

    echeances = conn.execute(
        """SELECT * FROM echeances_emprunt
           WHERE emprunt_id = ? ORDER BY numero""",
        (emprunt_id,),
    ).fetchall()

    conn.close()
    return {
        "emprunt_id": emp["id"],
        "designation": emp["designation"],
        "date_debut": emp["date_debut"],
        "montant": emp["montant"],
        "taux_annuel": emp["taux_annuel"],
        "duree_mois": emp["duree_mois"],
        "periodicite": emp["periodicite"],
        "type_amortissement": emp["type_amortissement"],
        "date_fin": emp["date_fin"],
        "echeances": [dict(e) for e in echeances],
    }


def generer_ecriture_echeance(emprunt_id: int, numero_echeance: int) -> dict:
    """Crée une écriture OD pour une échéance.
    Débit 164 (capital), débit 661 (intérêts), débit 616 (assurance),
    crédit 512 (banque). Lie l'écriture dans echeances_emprunt.
    """
    conn = get_db()
    ech = conn.execute(
        """SELECT * FROM echeances_emprunt
           WHERE emprunt_id = ? AND numero = ?""",
        (emprunt_id, numero_echeance),
    ).fetchone()
    if not ech:
        conn.close()
        raise ValueError(f"Échéance {numero_echeance} introuvable pour emprunt {emprunt_id}")

    emp = conn.execute(
        "SELECT * FROM emprunts WHERE id = ?", (emprunt_id,)
    ).fetchone()
    ex_id = emp["exercice_id"]

    # Créer l'écriture
    cur = conn.execute(
        """INSERT INTO ecritures (exercice_id, journal, date, libelle)
           VALUES (?, 'OD', ?, ?)""",
        (ex_id, ech["date_echeance"],
         f"Échéance {numero_echeance} - {emp['designation']}"),
    )
    ecriture_id = cur.lastrowid

    # Ligne crédit 512 (sortie banque, total)
    total_sortie = ech["capital_rembourse"] + ech["interets"] + (ech["assurance"] or 0)
    conn.execute(
        """INSERT INTO lignes_ecriture (ecriture_id, compte, debit, credit, libelle)
           VALUES (?, '512', 0, ?, ?)""",
        (ecriture_id, total_sortie,
         f"Échéance {numero_echeance} {emp['designation']}"),
    )
    # Ligne débit 164 - capital remboursé
    conn.execute(
        """INSERT INTO lignes_ecriture (ecriture_id, compte, debit, credit, libelle)
           VALUES (?, '164', ?, 0, ?)""",
        (ecriture_id, ech["capital_rembourse"],
         f"Capital remboursé éch. {numero_echeance}"),
    )
    # Ligne débit 661 - intérêts
    if ech["interets"] > 0:
        conn.execute(
            """INSERT INTO lignes_ecriture (ecriture_id, compte, debit, credit, libelle)
               VALUES (?, '661', ?, 0, ?)""",
            (ecriture_id, ech["interets"],
             f"Intérêts éch. {numero_echeance}"),
        )
    # Ligne débit 616 - assurance
    if ech["assurance"] and ech["assurance"] > 0:
        conn.execute(
            """INSERT INTO lignes_ecriture (ecriture_id, compte, debit, credit, libelle)
               VALUES (?, '616', ?, 0, ?)""",
            (ecriture_id, ech["assurance"],
             f"Assurance éch. {numero_echeance}"),
        )

    # Lier l'écriture
    conn.execute(
        "UPDATE echeances_emprunt SET ecriture_id = ? WHERE id = ?",
        (ecriture_id, ech["id"]),
    )

    conn.commit()
    conn.close()
    return {"ecriture_id": ecriture_id, "ok": True}


def resume_emprunts(exercice_id: int) -> dict:
    """Résumé global des emprunts d'un exercice."""
    conn = get_db()
    emps = conn.execute(
        "SELECT * FROM emprunts WHERE exercice_id = ?", (exercice_id,)
    ).fetchall()

    total_capital_du = 0.0
    total_interets_restants = 0.0
    nb_actifs = 0
    prochaine_echeance = None
    aujourdhui = datetime.now()

    for emp in emps:
        if emp["actif"]:
            nb_actifs += 1
        # Dernière échéance non payée (sans ecriture_id)
        derniere = conn.execute(
            """SELECT * FROM echeances_emprunt
               WHERE emprunt_id = ? AND ecriture_id IS NULL
               ORDER BY numero LIMIT 1""",
            (emp["id"],),
        ).fetchone()
        if derniere:
            total_capital_du += derniere["capital_restant_avant"]
            # Intérêts restants = somme des intérêts non payés
            inter = conn.execute(
                """SELECT SUM(interets) as total
                   FROM echeances_emprunt
                   WHERE emprunt_id = ? AND ecriture_id IS NULL""",
                (emp["id"],),
            ).fetchone()
            total_interets_restants += inter["total"] or 0

            # Prochaine échéance : la plus proche dans le temps
            date_ech = datetime.strptime(derniere["date_echeance"], "%Y-%m-%d")
            if prochaine_echeance is None or (
                prochaine_echeance["date"] is None or
                (derniere["date_echeance"] < prochaine_echeance["date"])
            ):
                prochaine_echeance = {
                    "emprunt": emp["designation"],
                    "date": derniere["date_echeance"],
                    "numero": derniere["numero"],
                    "mensualite": derniere["mensualite"],
                }

    conn.close()
    return {
        "total_capital_du": round(total_capital_du, 2),
        "total_interets_restants": round(total_interets_restants, 2),
        "nb_actifs": nb_actifs,
        "prochaine_echeance": prochaine_echeance,
    }


def cloturer_emprunt(emprunt_id: int) -> dict:
    """Passe un emprunt en inactif."""
    conn = get_db()
    conn.execute("UPDATE emprunts SET actif = 0 WHERE id = ?", (emprunt_id,))
    conn.commit()
    conn.close()
    return {"ok": True}
