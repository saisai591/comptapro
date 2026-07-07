"""
Immobilisations & Amortissements.
Stdlib uniquement. Pattern conn optionnel + doit_fermer.

Tables : immobilisations, dotations_amortissement.
"""

from datetime import date, datetime
from typing import Optional

from comptable.db import get_db


# ── CRUD immobilisations ────────────────────────────────────────────

def ajouter_immobilisation(
    exercice_id: int,
    compte_immo: str,
    compte_amort: str,
    designation: str,
    date_acquisition: str,
    valeur_acquisition: float,
    duree_annees: int,
    mode: str = "lineaire",
    coefficient_degressif: float = 1.75,
    valeur_residuelle: float = 0.0,
) -> int:
    """Ajoute une immobilisation. Retourne l'id créé."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO immobilisations
           (exercice_id, compte_immo, compte_amort, designation,
            date_acquisition, valeur_acquisition, duree_annees,
            mode, coefficient_degressif, valeur_residuelle)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (exercice_id, compte_immo, compte_amort, designation,
         date_acquisition, valeur_acquisition, duree_annees,
         mode, coefficient_degressif, valeur_residuelle),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def lister_immobilisations(exercice_id: int, actif: Optional[bool] = None) -> list[dict]:
    """Liste les immobilisations, filtrable par actif."""
    conn = get_db()
    q = "SELECT * FROM immobilisations WHERE exercice_id = ?"
    params = [exercice_id]
    if actif is not None:
        q += " AND actif = ?"
        params.append(1 if actif else 0)
    q += " ORDER BY date_acquisition DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def ceder_immobilisation(immo_id: int, date_cession: str, prix_cession: float) -> dict:
    """Marque une immo comme cédée et calcule la +/-value."""
    conn = get_db()
    immo = conn.execute(
        "SELECT * FROM immobilisations WHERE id = ?", (immo_id,)
    ).fetchone()
    if not immo:
        conn.close()
        raise ValueError(f"Immobilisation {immo_id} introuvable")

    # VNC actuelle = valeur_acquisition - cumul amortissements
    dota = conn.execute(
        "SELECT SUM(dotation) as total FROM dotations_amortissement WHERE immo_id = ?",
        (immo_id,),
    ).fetchone()
    cumul_amort = dota["total"] or 0
    vnc = immo["valeur_acquisition"] - cumul_amort
    plus_value = prix_cession - vnc

    conn.execute(
        """UPDATE immobilisations
           SET date_cession = ?, prix_cession = ?, actif = 0
           WHERE id = ?""",
        (date_cession, prix_cession, immo_id),
    )
    conn.commit()
    conn.close()
    return {
        "id": immo_id,
        "vnc": round(vnc, 2),
        "prix_cession": prix_cession,
        "plus_value": round(plus_value, 2),
        "ok": True,
    }


# ── Tableau d'amortissement ─────────────────────────────────────────

def _prorata_temporis(date_acq: str, fin_exercice: str) -> float:
    """Ratio 1ère année : jours restants / 360."""
    acq = datetime.strptime(date_acq, "%Y-%m-%d")
    fin = datetime.strptime(fin_exercice, "%Y-%m-%d")
    # Jours entre date d'acquisition et fin d'exercice
    jours = (fin - acq).days
    # Jours dans l'année ≈ 360 (usage comptable)
    return max(0, min(1, jours / 360.0))


def calculer_amortissements(
    exercice_id: int, immo_id: Optional[int] = None
) -> list[dict]:
    """Calcule le tableau complet d'amortissement.
    Si immo_id fourni, une seule immo; sinon toutes les actives.

    Retourne [{immo_id, designation, tableau: [{annee, dotation, cumul, vnc}]}]
    """
    conn = get_db()

    # Récupérer les dates de l'exercice
    ex = conn.execute(
        "SELECT date_debut, date_fin FROM exercices WHERE id = ?", (exercice_id,)
    ).fetchone()
    if not ex:
        conn.close()
        raise ValueError(f"Exercice {exercice_id} introuvable")
    date_debut = ex["date_debut"]
    date_fin = ex["date_fin"]

    # Sélectionner les immobilisations
    q = "SELECT * FROM immobilisations WHERE exercice_id = ? AND actif = 1"
    params = [exercice_id]
    if immo_id is not None:
        q += " AND id = ?"
        params.append(immo_id)
    immos = conn.execute(q, params).fetchall()

    result = []
    for immo in immos:
        duree = immo["duree_annees"]
        valeur = immo["valeur_acquisition"]
        vresid = immo["valeur_residuelle"] or 0
        mode = immo["mode"]
        coeff = immo["coefficient_degressif"]
        date_acq = immo["date_acquisition"]

        # Supprimer les dotations existantes pour cette immo (recalcul propre)
        conn.execute(
            "DELETE FROM dotations_amortissement WHERE immo_id = ?", (immo["id"],)
        )

        tableau = []
        cumul = 0.0
        vnc = valeur

        if mode == "lineaire":
            base = valeur - vresid
            dotation_annuelle = base / duree
            prorata = _prorata_temporis(date_acq, date_fin)

            for annee in range(1, duree + 1):
                if annee == 1:
                    dotation = round(dotation_annuelle * prorata, 2)
                elif annee == duree:
                    # Dernière année : le reste pour arriver exactement à la base amortissable
                    dotation = round(base - cumul, 2)
                else:
                    dotation = round(dotation_annuelle, 2)
                cumul = round(cumul + dotation, 2)
                vnc = round(valeur - cumul, 2)

                # Stocker dans la DB
                conn.execute(
                    """INSERT INTO dotations_amortissement
                       (immo_id, exercice_id, annee, dotation, cumul, vnc)
                       VALUES (?,?,?,?,?,?)""",
                    (immo["id"], exercice_id, annee, dotation, cumul, vnc),
                )
                tableau.append({"annee": annee, "dotation": dotation, "cumul": cumul, "vnc": vnc})

        elif mode == "degressif":
            taux_lineaire = 100.0 / duree
            taux_degressif = taux_lineaire * coeff
            vnc = valeur

            # Prorata temporis 1ère année
            prorata = _prorata_temporis(date_acq, date_fin)
            annee_restantes = duree

            for annee in range(1, duree + 1):
                if annee == 1:
                    dotation = round(vnc * (taux_degressif / 100.0) * prorata, 2)
                else:
                    if vnc <= vresid:
                        dotation = 0.0
                    else:
                        # Si taux dégressif < taux linéaire sur durée restante, basculer en linéaire
                        tl_restant = 100.0 / annee_restantes if annee_restantes > 0 else 100.0
                        tx = max(taux_degressif, tl_restant)
                        dotation = round(vnc * (tx / 100.0), 2)

                # Ne pas descendre sous la valeur résiduelle
                if vnc - dotation < vresid:
                    dotation = round(vnc - vresid, 2)

                cumul = round(cumul + dotation, 2)
                vnc = round(valeur - cumul, 2)
                annee_restantes -= 1

                conn.execute(
                    """INSERT INTO dotations_amortissement
                       (immo_id, exercice_id, annee, dotation, cumul, vnc)
                       VALUES (?,?,?,?,?,?)""",
                    (immo["id"], exercice_id, annee, dotation, cumul, vnc),
                )
                tableau.append({"annee": annee, "dotation": dotation, "cumul": cumul, "vnc": vnc})

        result.append({
            "immo_id": immo["id"],
            "designation": immo["designation"],
            "mode": mode,
            "tableau": tableau,
        })

    conn.commit()
    conn.close()
    return result


def generer_ecritures_amortissement(exercice_id: int, immo_id: int) -> list[dict]:
    """Crée les écritures OD pour chaque année non comptabilisée.
    Débit 681 (dotations) / Crédit compte_amort.
    Lie l'écriture dans dotations_amortissement.
    """
    conn = get_db()
    immo = conn.execute(
        "SELECT * FROM immobilisations WHERE id = ?", (immo_id,)
    ).fetchone()
    if not immo:
        conn.close()
        raise ValueError(f"Immobilisation {immo_id} introuvable")

    dotations = conn.execute(
        """SELECT * FROM dotations_amortissement
           WHERE immo_id = ? AND ecriture_id IS NULL
           ORDER BY annee""",
        (immo_id,),
    ).fetchall()

    ecritures = []
    for dot in dotations:
        # Calculer la date de l'écriture = fin d'exercice
        ex = conn.execute(
            "SELECT date_fin FROM exercices WHERE id = ?", (exercice_id,)
        ).fetchone()
        date_fin = ex["date_fin"] if ex else datetime.now().strftime("%Y-%m-%d")

        # Créer l'écriture OD
        cur = conn.execute(
            """INSERT INTO ecritures (exercice_id, journal, date, libelle)
               VALUES (?, 'OD', ?, ?)""",
            (exercice_id, date_fin,
             f"Dotation amortissement {immo['designation']} - année {dot['annee']}"),
        )
        ecriture_id = cur.lastrowid

        # Ligne débit 681
        conn.execute(
            """INSERT INTO lignes_ecriture (ecriture_id, compte, debit, credit, libelle)
               VALUES (?, '681120', ?, 0, ?)""",
            (ecriture_id, dot["dotation"],
             f"Dotation {immo['designation']} année {dot['annee']}"),
        )
        # Ligne crédit compte_amort
        conn.execute(
            """INSERT INTO lignes_ecriture (ecriture_id, compte, debit, credit, libelle)
               VALUES (?, ?, 0, ?, ?)""",
            (ecriture_id, immo["compte_amort"], dot["dotation"],
             f"Amort. {immo['designation']} année {dot['annee']}"),
        )

        # Lier l'écriture
        conn.execute(
            "UPDATE dotations_amortissement SET ecriture_id = ? WHERE id = ?",
            (ecriture_id, dot["id"]),
        )
        ecritures.append({"annee": dot["annee"], "ecriture_id": ecriture_id})

    conn.commit()
    conn.close()
    return ecritures


def plan_amortissement(immo_id: int) -> dict:
    """Lit le tableau d'amortissement déjà calculé pour une immo."""
    conn = get_db()
    immo = conn.execute(
        "SELECT * FROM immobilisations WHERE id = ?", (immo_id,)
    ).fetchone()
    if not immo:
        conn.close()
        raise ValueError(f"Immobilisation {immo_id} introuvable")

    dots = conn.execute(
        "SELECT * FROM dotations_amortissement WHERE immo_id = ? ORDER BY annee",
        (immo_id,),
    ).fetchall()

    tableau = []
    for d in dots:
        tableau.append({
            "annee": d["annee"],
            "dotation": d["dotation"],
            "cumul": d["cumul"],
            "vnc": d["vnc"],
            "ecriture_id": d["ecriture_id"],
        })

    conn.close()
    return {
        "immo_id": immo["id"],
        "designation": immo["designation"],
        "compte_immo": immo["compte_immo"],
        "compte_amort": immo["compte_amort"],
        "valeur_acquisition": immo["valeur_acquisition"],
        "duree_annees": immo["duree_annees"],
        "mode": immo["mode"],
        "valeur_residuelle": immo["valeur_residuelle"],
        "date_cession": immo["date_cession"],
        "prix_cession": immo["prix_cession"],
        "tableau": tableau,
    }


def resume_immobilisations(exercice_id: int) -> dict:
    """Résumé global des immobilisations d'un exercice."""
    conn = get_db()
    immos = conn.execute(
        "SELECT * FROM immobilisations WHERE exercice_id = ?", (exercice_id,)
    ).fetchall()

    total_acq = sum(i["valeur_acquisition"] for i in immos)
    nb_actives = sum(1 for i in immos if i["actif"])
    nb_cedees = sum(1 for i in immos if not i["actif"])

    total_amort = 0.0
    for immo in immos:
        d = conn.execute(
            "SELECT SUM(dotation) as total FROM dotations_amortissement WHERE immo_id = ?",
            (immo["id"],),
        ).fetchone()
        total_amort += d["total"] or 0

    vnc_globale = total_acq - total_amort

    conn.close()
    return {
        "total_acquisitions": round(total_acq, 2),
        "total_amortis": round(total_amort, 2),
        "vnc_globale": round(vnc_globale, 2),
        "nb_actives": nb_actives,
        "nb_cedees": nb_cedees,
    }
