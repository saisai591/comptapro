"""
Circuit de validation des achats : workflow a_valider → valide → paye.
Stdlib uniquement.
"""

import sqlite3
from datetime import date, datetime
from typing import Optional

from .db import get_db


def ajouter_achat(
    exercice_id: int,
    fournisseur: str,
    date_facture: str,
    description: str,
    montant_ttc: float,
    compte_charge: str = "607",
    tva_taux: float = 20.0,
    numero_facture: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Ajoute un achat à valider et retourne son ID."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    cur = conn.execute(
        """INSERT INTO validations_achat
           (exercice_id, fournisseur, date_facture, numero_facture, description,
            montant_ttc, compte_charge, tva_taux)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (exercice_id, fournisseur, date_facture, numero_facture, description,
         montant_ttc, compte_charge, tva_taux),
    )
    aid = cur.lastrowid

    if doit_fermer:
        conn.commit()
        conn.close()
    return aid


def lister_achats(
    exercice_id: int,
    statut: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Liste les achats, filtrés par statut si spécifié."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    query = "SELECT * FROM validations_achat WHERE exercice_id = ?"
    params = [exercice_id]
    if statut:
        query += " AND statut = ?"
        params.append(statut)
    query += " ORDER BY date_facture DESC, id DESC"

    rows = conn.execute(query, params).fetchall()

    if doit_fermer:
        conn.close()
    return [dict(r) for r in rows]


def valider_achat(
    id: int,
    valide_par: str = "comptable",
    conn: Optional[sqlite3.Connection] = None,
):
    """Passe un achat en statut 'valide' et log dans piste_audit."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    row = conn.execute(
        "SELECT * FROM validations_achat WHERE id = ?", (id,)
    ).fetchone()
    if not row:
        if doit_fermer:
            conn.close()
        raise ValueError(f"Achat {id} introuvable")
    if row["statut"] != "a_valider":
        if doit_fermer:
            conn.close()
        raise ValueError(f"Achat {id} déjà {row['statut']}")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """UPDATE validations_achat
           SET statut = 'valide', valide_par = ?, valide_le = ?
           WHERE id = ?""",
        (valide_par, now, id),
    )

    if doit_fermer:
        conn.commit()
        conn.close()

    # Log audit (connexion séparée)
    from .audit import log_action
    log_action("validation_achat", id, "valider", {"valide_par": valide_par})


def rejeter_achat(
    id: int,
    commentaire: str = "",
    conn: Optional[sqlite3.Connection] = None,
):
    """Passe un achat en statut 'rejete' avec commentaire."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    row = conn.execute(
        "SELECT * FROM validations_achat WHERE id = ?", (id,)
    ).fetchone()
    if not row:
        if doit_fermer:
            conn.close()
        raise ValueError(f"Achat {id} introuvable")

    conn.execute(
        """UPDATE validations_achat
           SET statut = 'rejete', commentaire = ?
           WHERE id = ?""",
        (commentaire, id),
    )

    if doit_fermer:
        conn.commit()
        conn.close()

    from .audit import log_action
    log_action("validation_achat", id, "rejeter", {"commentaire": commentaire})


def generer_ecriture_achat(
    id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    Génère l'écriture comptable correspondant à un achat validé :
    - Débit compte_charge + 4456 (TVA déductible), Crédit 401 (fournisseur).
    Passe en statut 'paye'. Retourne l'ID de l'écriture créée.
    """
    from .ecritures import saisir_ecriture

    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    row = conn.execute(
        "SELECT * FROM validations_achat WHERE id = ?", (id,)
    ).fetchone()
    if not row:
        if doit_fermer:
            conn.close()
        raise ValueError(f"Achat {id} introuvable")
    if row["statut"] not in ("valide", "a_valider"):
        if doit_fermer:
            conn.close()
        raise ValueError(f"Achat {id} au statut {row['statut']}, attendu valide ou a_valider")
    if row["ecriture_id"]:
        if doit_fermer:
            conn.close()
        raise ValueError("Une écriture existe déjà pour cet achat")

    achat = dict(row)
    tva_taux = achat["tva_taux"] or 20.0
    montant_ttc = achat["montant_ttc"]
    # Calcul HT et TVA
    montant_ht = round(montant_ttc / (1 + tva_taux / 100), 2)
    montant_tva = round(montant_ttc - montant_ht, 2)

    # Déterminer le bon sous-compte 4456 selon le taux
    if tva_taux == 20.0:
        compte_tva = "44566"  # TVA déductible 20%
    elif tva_taux == 10.0:
        compte_tva = "44562"  # TVA déductible 10%
    elif tva_taux == 5.5:
        compte_tva = "44563"  # TVA déductible 5.5%
    else:
        compte_tva = "44566"

    lignes = [
        {"compte": achat["compte_charge"], "debit": montant_ht, "credit": 0,
         "libelle": f"{achat['description']} — {achat['fournisseur']}"},
        {"compte": compte_tva, "debit": montant_tva, "credit": 0,
         "libelle": f"TVA {achat['description']}"},
        {"compte": "401", "debit": 0, "credit": montant_ttc,
         "libelle": achat["fournisseur"]},
    ]

    eid = saisir_ecriture(
        achat["exercice_id"],
        "HA",  # Journal Achats
        achat["date_facture"],
        f"Achat {achat['numero_facture'] or ''} — {achat['fournisseur']}",
        lignes,
        piece=achat["numero_facture"] or None,
    )

    # Marquer comme payé et lier l'écriture
    conn.execute(
        """UPDATE validations_achat
           SET statut = 'paye', ecriture_id = ?
           WHERE id = ?""",
        (eid, id),
    )

    if doit_fermer:
        conn.commit()
        conn.close()

    from .audit import log_action
    log_action("validation_achat", id, "generer_ecriture", {"ecriture_id": eid})
    return eid


def marquer_paye_manuel(
    id: int,
    conn: Optional[sqlite3.Connection] = None,
):
    """Passe en 'paye' sans générer d'écriture (saisie ailleurs)."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    conn.execute(
        "UPDATE validations_achat SET statut = 'paye' WHERE id = ?",
        (id,),
    )

    if doit_fermer:
        conn.commit()
        conn.close()

    from .audit import log_action
    log_action("validation_achat", id, "marquer_paye", {"manuel": True})


def stats_validations(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Statistiques du circuit de validation."""
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    counts = conn.execute(
        """SELECT statut, COUNT(*) as nb, COALESCE(SUM(montant_ttc), 0) as total
           FROM validations_achat
           WHERE exercice_id = ?
           GROUP BY statut""",
        (exercice_id,),
    ).fetchall()

    result = {"a_valider": 0, "valide": 0, "rejete": 0, "paye": 0, "total_ttc_a_valider": 0.0}
    for row in counts:
        statut = row["statut"]
        nb = row["nb"]
        result[statut] = nb
        if statut == "a_valider":
            result["total_ttc_a_valider"] = round(row["total"] or 0, 2)

    if doit_fermer:
        conn.close()
    return result


def export_paiements(
    exercice_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """
    Liste des achats validés non payés, format prêt pour virement SEPA.
    """
    doit_fermer = conn is None
    if conn is None:
        conn = get_db()

    rows = conn.execute(
        """SELECT va.id, va.fournisseur, va.numero_facture, va.description,
                  va.montant_ttc, va.date_facture, va.compte_charge,
                  ca.nom, ca.adresse, ca.siret, ca.email, ca.telephone
           FROM validations_achat va
           LEFT JOIN comptes_aux ca ON ca.nom = va.fournisseur AND ca.type = 'fournisseur'
           WHERE va.exercice_id = ? AND va.statut = 'valide'
           ORDER BY va.date_facture""",
        (exercice_id,),
    ).fetchall()

    result = []
    for r in rows:
        result.append({
            "id": r["id"],
            "beneficiaire": r["nom"] or r["fournisseur"],
            "iban": "",  # Sera à compléter manuellement
            "montant": r["montant_ttc"],
            "reference": r["numero_facture"] or f"Achat-{r['id']}",
            "description": r["description"],
            "date_facture": r["date_facture"],
            "siret": r["siret"] or "",
            "email": r["email"] or "",
        })

    if doit_fermer:
        conn.close()
    return result
